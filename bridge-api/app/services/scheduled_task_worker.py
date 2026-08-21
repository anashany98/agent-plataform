"""Worker real para tareas persistidas y aprobadas.

El worker comparte el mismo ejecutor que ``POST /scheduled-tasks/run-due``.
La clave durable por tarea/fecha de vencimiento en ``IdempotencyRecord`` hace
que varias réplicas puedan observar la misma tarea sin ejecutar dos veces el
mismo vencimiento.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Callable
from typing import Any

from app.config import settings
from app.installation_context import installation_scope
from app.security import Principal

_LOG = logging.getLogger("bridge.scheduled_task_worker")


class DurableScheduledTaskWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
        installation_id: str | None = None,
        poll_sec: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._installation_id = installation_id or settings.INSTALLATION_ID
        configured_poll = getattr(settings, "SCHEDULED_TASK_WORKER_POLL_SEC", 30.0)
        self._poll_sec = max(1.0, float(poll_sec if poll_sec is not None else configured_poll))
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._last_run_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] = {"processed": 0, "items": []}

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.database import SessionLocal

        return SessionLocal()

    @property
    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "poll_seconds": self._poll_sec,
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": dict(self._last_result),
        }

    async def run_once(self) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            # Import tardío evita un ciclo durante la construcción de FastAPI.
            from app.main import run_due_scheduled_tasks

            db = self._session()
            try:
                principal = Principal(
                    user_id="scheduled-task-worker",
                    username="scheduled-task-worker",
                    role="admin",
                    installation_id=self._installation_id,
                    token_version=0,
                    jti="scheduled-task-worker",
                )
                with installation_scope(self._installation_id):
                    return run_due_scheduled_tasks(principal=principal, db=db)
            finally:
                db.close()

        try:
            result = await asyncio.to_thread(execute)
            self._last_result = dict(result)
            self._last_error = None
            return result
        except Exception as exc:  # noqa: BLE001 - el loop debe sobrevivir
            # El estado de salud no conserva mensajes que puedan incluir
            # payloads o secretos. El detalle queda en la traza interna.
            self._last_error = type(exc).__name__
            _LOG.error("Ciclo del scheduler falló error_type=%s", type(exc).__name__)
            return {"status": "failed", "processed": 0, "items": []}
        finally:
            self._last_run_at = datetime.datetime.now(datetime.UTC).isoformat()

    async def run_forever(self) -> None:
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_sec)
            except TimeoutError:
                continue

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except TimeoutError:
                self._task.cancel()
        self._task = None
        self._stop_event = None
