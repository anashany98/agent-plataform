import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Límite básico por IP/ruta.

    Usa memoria local para no introducir falsos positivos cuando Redis está caído.
    En una instalación multi-worker se debe mantener un solo worker de Bridge o
    sustituir este almacén por Redis; Docker ejecuta un único worker por defecto.
    """

    def __init__(self, app):
        super().__init__(app)
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @staticmethod
    def _client_ip(request: Request) -> str:
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # El proxy de confianza añade la IP remota al final; no se acepta el primer
            # elemento porque puede ser aportado por el cliente.
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED or request.url.path in {"/health", "/ready"}:
            return await call_next(request)

        is_login = request.url.path == "/auth/login"
        limit = settings.LOGIN_RATE_LIMIT_REQUESTS if is_login else settings.RATE_LIMIT_REQUESTS_PER_MINUTE
        window = settings.LOGIN_RATE_LIMIT_WINDOW_SEC if is_login else 60
        now = time.monotonic()
        key = f"{self._client_ip(request)}:{request.url.path}"

        async with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas solicitudes. Inténtalo de nuevo más tarde."},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response
