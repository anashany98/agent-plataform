"""Worker durable del outbox (Fase B, bloque 3).

Procesa la cola de efectos externos en segundo plano sin intervención
manual, con tres garantías:

- **Señal Redis**: cuando ``OutboxService.enqueue`` encola un mensaje
  publica su id en ``bridge:outbox:signal``; el worker hace ``BRPOP`` con
  timeout corto y procesa al instante. Si Redis no está disponible, el
  worker vuelve al poll determinista (``OUTBOX_WORKER_POLL_SEC``).
- **Lock de dispatch distribuido**: solo un worker procesa ``process_due``
  a la vez (``SET NX EX`` sobre ``bridge:outbox:dispatch``). El lease TTL
  evita deadlocks si el titular muere.
- **Reclaim de leases vencidos**: si un worker muere con mensajes en
  ``processing``, ``process_due`` los reclama (contador + 1) en cuanto el
  lease vence — el efecto nunca queda atascado para siempre.

El worker es un componente opcional del proceso Bridge: se arranca desde el
lifespan de FastAPI solo cuando ``OUTBOX_WORKER_ENABLED=true``. En tests
está deshabilitado por defecto (hermeticidad D-032); los evals inyectan un
backend falso.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import settings
from app.installation_context import installation_scope
from app.services.outbox import OutboxMessage, OutboxService

_LOG = logging.getLogger("bridge.outbox_worker")

SIGNAL_QUEUE = "bridge:outbox:signal"
DISPATCH_LOCK = "bridge:outbox:dispatch"

Dispatcher = Callable[[OutboxMessage], Awaitable[dict[str, Any]]]


class DurableOutboxWorker:
    """Loop asíncrono de despacho con señal Redis, lock y reclaim."""

    def __init__(
        self,
        dispatchers: dict[str, Dispatcher],
        *,
        backend: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        installation_id: str | None = None,
        poll_sec: float | None = None,
        lease_sec: int | None = None,
        lock_sec: int | None = None,
    ) -> None:
        self._dispatchers = dispatchers
        self._backend = backend
        self._session_factory = session_factory
        self._installation_id = installation_id or settings.INSTALLATION_ID
        self._poll_sec = float(poll_sec if poll_sec is not None else settings.OUTBOX_WORKER_POLL_SEC)
        self._lease_sec = int(lease_sec if lease_sec is not None else settings.OUTBOX_WORKER_LEASE_SEC)
        self._lock_sec = int(
            lock_sec if lock_sec is not None else settings.OUTBOX_WORKER_DISPATCH_LOCK_SEC
        )
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._last_summary: dict[str, int] = {}

    @property
    def last_summary(self) -> dict[str, int]:
        return dict(self._last_summary)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _redis(self):
        if self._backend is not None:
            return self._backend
        from app.services.redis_backend import RedisBackend

        return RedisBackend()

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.database import SessionLocal as _SessionLocal

        return _SessionLocal()

    async def run_once(self, *, now: Any | None = None) -> dict[str, int]:
        """Un ciclo de despacho: lock → process_due → unlock.

        Si el lock de dispatch ya está tomado (otro worker activo), el ciclo
        no procesa nada y devuelve el resumen anterior: no hay doble envío.
        """
        token = uuid.uuid4().hex
        redis = self._redis()
        lock_held = False
        try:
            lock_held = await redis.acquire_lock(DISPATCH_LOCK, self._lock_sec, token)
        except Exception as exc:  # noqa: BLE001 - disponibilidad se decide por configuración
            if not settings.REDIS_RATE_LIMIT_FAIL_OPEN:
                raise RuntimeError("Redis no disponible para el lock de outbox") from exc
            # Sólo desarrollo/single-worker puede continuar sin lock. El
            # perfil production valida fail-open=false y por tanto no entra.
            _LOG.warning("Worker outbox en poll sin lock distribuido")
            lock_held = True
            redis = None
        if not lock_held:
            return {
                "evaluated": 0,
                "reclaimed": 0,
                "sent": 0,
                "retry_scheduled": 0,
                "dead": 0,
                "skipped": 0,
            }
        try:
            db = self._session()
            try:
                with installation_scope(self._installation_id):
                    summary = await OutboxService(db).process_due(
                        dispatchers=self._dispatchers,
                        now=now,
                    )
                    db.commit()
                self._last_summary = summary
                _LOG.info(
                    "Ciclo outbox completado evaluated=%s sent=%s dead=%s",
                    summary.get("evaluated", 0),
                    summary.get("sent", 0),
                    summary.get("dead", 0),
                )
                return dict(summary)
            finally:
                db.close()
        finally:
            if lock_held and redis is not None:
                try:
                    await redis.release_lock(DISPATCH_LOCK, token)
                except Exception:  # noqa: BLE001
                    _LOG.warning("No se pudo liberar el lock de dispatch (TTL lo hará)")

    async def _cycle(self) -> dict[str, int]:
        try:
            return await self.run_once()
        except Exception as exc:  # noqa: BLE001 — el loop nunca debe morir
            _LOG.error("Ciclo del worker falló: %s", exc)
            return dict(self._last_summary)

    async def run_forever(self) -> None:
        """Bucle principal: señal Redis o poll; el stop_event corta el loop."""
        self._stop_event = asyncio.Event()
        redis = self._redis()
        while not self._stop_event.is_set():
            # Espera corta por señal; si hay timeout, procesa por poll.
            try:
                await asyncio.wait_for(
                    redis.pop(SIGNAL_QUEUE, timeout=self._poll_sec),
                    timeout=self._poll_sec + 1.0,
                )
            except Exception:  # noqa: BLE001
                pass
            await self._cycle()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:  # noqa: BLE001
                self._task.cancel()
        self._task = None
        self._stop_event = None
