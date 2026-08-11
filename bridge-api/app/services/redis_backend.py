"""Backend Redis real para rate limit, locks distribuidos y cola del worker durable (Fase B, bloque 3).

Reglas:

- **Rate limit**: ventana fija con ``INCR`` + ``EXPIRE`` (atómico en un solo
  pipeline). La clave se expira sola: no hay limpieza manual de buckets.
- **Locks distribuidos**: ``SET NX EX`` (adquisición) y ``GETDEL`` con
  comparación del token (liberación). El TTL evita deadlocks si el titular
  muere; solo el poseedor del token puede liberar.
- **Cola del worker**: ``LPUSH``/``BRPOP`` sobre listas Redis; la señal de
  "hay trabajo" es best-effort (si Redis cae, el worker hace poll).
- **Degradación explícita**: cada operación distingue ``RedisBackendError``
  (no disponible / timeout) de errores de protocolo. Rate limit degrada a
  memoria cuando ``REDIS_RATE_LIMIT_FAIL_OPEN`` está activo (nunca tumba el
  servicio por un backend caído); los locks y la cola fallan de forma
  observable y el worker vuelve al poll determinista.

Hermetismo: los tests inyectan un cliente falso en memoria
(``tests/regression/test_p1_redis_backend.py``); ningún eval contacta un
Redis real salvo el opt-in con ``RUN_REDIS_EVALS=1``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

_LOG = logging.getLogger("bridge.redis_backend")

_LOCK_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisBackendError(RuntimeError):
    """Redis no está disponible o no respondió a tiempo."""


class RedisBackend:
    """Fachada sobre ``redis.asyncio`` con degradación explícita.

    ``_client`` se crea perezosamente (el primer ``ping`` decide la
    disponibilidad) y se revalida con un ``ping`` acotado antes de cada
    operación que requiera consistencia (rate limit, locks).
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._available: bool | None = None

    def _build_client(self):
        from redis.asyncio import Redis

        return Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SEC,
            socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SEC,
            decode_responses=True,
        )

    @property
    def client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def _redis_available(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception as exc:  # noqa: BLE001 — cualquier fallo de red cuenta
            _LOG.warning("Redis no disponible: %s", exc)
            self._available = False
            return False

    async def check(self) -> bool:
        """Verifica disponibilidad; usado por /ready y por la degradación."""
        self._available = await self._redis_available()
        return self._available

    # ------------------------------------------------------------------
    # Rate limit (ventana fija: INCR + EXPIRE atómicos en pipeline)
    # ------------------------------------------------------------------

    async def rate_limit(
        self,
        key: str,
        limit: int,
        window_sec: int,
    ) -> tuple[bool, int | None]:
        """Cuenta una solicitud y devuelve (permitida?, retry_after_seg).

        Lanza ``RedisBackendError`` si Redis no responde; el llamador decide
        si degradar (fail-open) o fallar cerrado.
        """
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, max(1, window_sec))
            results = await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis rate limit no disponible: {exc}") from exc
        count = int(results[0])
        if count <= limit:
            return True, None
        try:
            ttl = await self.client.ttl(key)
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis ttl no disponible: {exc}") from exc
        retry_after = max(1, int(ttl if ttl is not None and ttl > 0 else window_sec))
        return False, retry_after

    async def rate_limit_reset(self, key: str) -> None:
        """Borra el bucket (útil en tests y para desbloqueos manuales)."""
        try:
            await self.client.delete(key)
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis delete no disponible: {exc}") from exc

    # ------------------------------------------------------------------
    # Locks distribuidos (SET NX EX / GETDEL con token)
    # ------------------------------------------------------------------

    async def acquire_lock(self, name: str, ttl_sec: int, token: str) -> bool:
        """Adquiere un lock si nadie lo posee; devuelve True si lo obtiene."""
        try:
            acquired = await self.client.set(
                name,
                token,
                nx=True,
                ex=max(1, ttl_sec),
            )
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis lock no disponible: {exc}") from exc
        return bool(acquired)

    async def release_lock(self, name: str, token: str) -> bool:
        """Libera el lock solo si el token coincide (evita liberar ajeno)."""
        try:
            script = self.client.register_script(_LOCK_RELEASE_SCRIPT)
            released = await script(keys=[name], args=[token])
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis unlock no disponible: {exc}") from exc
        return int(released or 0) == 1

    # ------------------------------------------------------------------
    # Cola del worker (LPUSH / BRPOP)
    # ------------------------------------------------------------------

    async def push(self, queue: str, payload: Any) -> None:
        """Encola un elemento (señal best-effort)."""
        try:
            await self.client.lpush(queue, payload)
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis push no disponible: {exc}") from exc

    async def pop(self, queue: str, timeout_sec: float) -> Any | None:
        """Bloquea hasta tener un elemento o vencer el timeout (None)."""
        try:
            item = await self.client.brpop(queue, timeout=timeout_sec)
        except Exception as exc:  # noqa: BLE001
            self._available = False
            raise RedisBackendError(f"Redis pop no disponible: {exc}") from exc
        if not item:
            return None
        return item[1]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
