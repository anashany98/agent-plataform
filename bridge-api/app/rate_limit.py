import asyncio
import ipaddress
import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

_LOG = logging.getLogger("bridge.rate_limit")


class RateLimitBackendUnavailable(RuntimeError):
    """El backend distribuido requerido no está operativo."""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Límite por IP/ruta con backend configurable.

    ``RATE_LIMIT_BACKEND``:
    - ``memory`` (default): buckets en memoria local. Útil para un solo
      worker o cuando Redis no está disponible.
    - ``auto``: usa Redis si ``REDIS_ENABLED`` y el ping responde; si cae,
      degrada a memoria cuando ``REDIS_RATE_LIMIT_FAIL_OPEN=true`` (default)
      o devuelve 503 en caso contrario.
    - ``redis``: exige Redis; sin él el middleware falla cerrado (503)
      salvo que ``REDIS_RATE_LIMIT_FAIL_OPEN=true``, que degrada a memoria.

    El rate limit nunca debe tumbar el servicio por un backend caído: la
    degradación a memoria es el comportamiento por defecto (fail-open).
    """

    def __init__(self, app, backend: object | None = None):
        super().__init__(app)
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        # Backend Redis inyectable (tests) o creado perezosamente.
        self._redis = backend

    def _redis_backend(self):
        if self._redis is None and getattr(settings, "REDIS_ENABLED", False):
            from app.services.redis_backend import RedisBackend

            self._redis = RedisBackend()
        return self._redis

    @staticmethod
    def _client_ip(request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        try:
            peer_ip = ipaddress.ip_address(peer)
            trusted_networks = [
                ipaddress.ip_network(cidr, strict=False)
                for cidr in settings.trusted_proxy_cidrs
            ]
        except ValueError:
            return peer
        if not any(peer_ip in network for network in trusted_networks):
            # Cabeceras procedentes de un peer no configurado son datos del
            # atacante, incluso si X-Real-IP parece válida.
            return str(peer_ip)

        trusted_hops = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0))
        forwarded = [
            item.strip()
            for item in request.headers.get("x-forwarded-for", "").split(",")
            if item.strip()
        ]
        if trusted_hops < 1 or len(forwarded) < trusted_hops:
            return str(peer_ip)
        try:
            parsed_forwarded = [ipaddress.ip_address(item) for item in forwarded]
        except ValueError:
            return str(peer_ip)

        candidate_index = len(parsed_forwarded) - trusted_hops
        proxy_hops = [*parsed_forwarded[candidate_index + 1 :], peer_ip]
        if len(proxy_hops) != trusted_hops or any(
            not any(proxy_ip in network for network in trusted_networks)
            for proxy_ip in proxy_hops
        ):
            # Una cadena con un supuesto proxy intermedio fuera de las redes
            # permitidas se rechaza completa en vez de aceptar una identidad
            # parcialmente controlada por el cliente.
            return str(peer_ip)
        return str(parsed_forwarded[candidate_index])

    async def _memory_allowed(self, key: str, limit: int, window: int, now: float) -> tuple[bool, int | None]:
        async with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, None

    async def _redis_allowed(self, key: str, limit: int, window: int) -> tuple[bool, int | None]:
        backend = self._redis_backend()
        if backend is None:
            if not getattr(settings, "REDIS_RATE_LIMIT_FAIL_OPEN", True):
                raise RateLimitBackendUnavailable("Redis no está habilitado")
            return await self._memory_allowed(key, limit, window, time.monotonic())
        try:
            return await backend.rate_limit(key, limit, window)
        except Exception as exc:  # noqa: BLE001 — degradación auditada
            fail_open = getattr(settings, "REDIS_RATE_LIMIT_FAIL_OPEN", True)
            _LOG.warning(
                "Rate limit Redis degradado (%s): %s",
                "fail-open a memoria" if fail_open else "fail-closed",
                exc,
            )
            if not fail_open:
                raise RateLimitBackendUnavailable("Redis no disponible") from exc
            return await self._memory_allowed(key, limit, window, time.monotonic())

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED or request.url.path in {"/health", "/ready"}:
            return await call_next(request)

        is_login = request.url.path == "/auth/login"
        limit = settings.LOGIN_RATE_LIMIT_REQUESTS if is_login else settings.RATE_LIMIT_REQUESTS_PER_MINUTE
        window = settings.LOGIN_RATE_LIMIT_WINDOW_SEC if is_login else 60
        key = f"{self._client_ip(request)}:{request.url.path}"

        backend_name = getattr(settings, "RATE_LIMIT_BACKEND", "memory").lower()
        if backend_name == "redis" and not getattr(settings, "REDIS_ENABLED", False):
            if not getattr(settings, "REDIS_RATE_LIMIT_FAIL_OPEN", True):
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Backend de rate limit no disponible"},
                    headers={"Retry-After": "5"},
                )
            backend_name = "memory"

        try:
            if backend_name in {"redis", "auto"}:
                allowed, retry_after = await self._redis_allowed(key, limit, window)
            else:
                allowed, retry_after = await self._memory_allowed(
                    key,
                    limit,
                    window,
                    time.monotonic(),
                )
        except RateLimitBackendUnavailable:
            return JSONResponse(
                status_code=503,
                content={"detail": "Backend de rate limit no disponible"},
                headers={"Retry-After": "5"},
            )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Demasiadas solicitudes. Inténtalo de nuevo más tarde."},
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response
