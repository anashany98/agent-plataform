"""Worker durable de alertas (SS-07).

Cada ciclo:

1. Evalúa las reglas de observabilidad contra el estado real (circuit
   breakers, outbox/DLQ y tasa de abstención RAG).
2. Persiste las alertas disparadas en ``alert_deliveries`` con
   deduplicación por ventana — sobreviven reinicios del proceso.
3. Entrega el lote pendiente por los canales configurados (webhook
   firmado y/o email) con reintentos y backoff.

Así la detección NO depende de que alguien abra ``/metrics``: una caída
nocturna se detecta y notifica aunque nadie mire. Sigue el patrón de los
workers durables existentes (outbox/scheduled/reminders): bucle async con
ejecución síncrona en hilo, parada limpia y estado para /health.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Callable
from typing import Any

from app.config import settings

_LOG = logging.getLogger("bridge.alert_delivery_worker")


class DurableAlertDeliveryWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
        installation_id: str | None = None,
        poll_sec: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._installation_id = installation_id or settings.INSTALLATION_ID
        self._poll_sec = max(
            5.0,
            float(poll_sec if poll_sec is not None else settings.ALERT_DELIVERY_WORKER_POLL_SEC),
        )
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._last_run_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] = {}

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
            "channels": {
                "webhook": bool(settings.ALERT_WEBHOOK_URL.strip()),
                "email": bool(settings.ALERT_EMAIL_TO.strip()),
            },
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": dict(self._last_result),
        }

    def evaluate_and_enqueue(self, db: Any) -> dict[str, Any]:
        """Evalúa reglas sobre estado real y persiste las alertas nuevas."""

        from app.installation_context import installation_scope
        from app.services.alert_delivery import enqueue_alert
        from app.services.observability import (
            evaluate_breaker_rule,
            evaluate_outbox_rule,
        )
        from app.services.outbox import OutboxService
        from app.services.resilience import all_breaker_states

        with installation_scope(self._installation_id):
            fired = [
                *evaluate_breaker_rule(all_breaker_states()),
                *evaluate_outbox_rule(OutboxService(db).counts()),
            ]
        enqueued = 0
        duplicates = 0
        for event in fired:
            row = enqueue_alert(
                db,
                rule_id=event.rule_id,
                summary=event.summary,
                severity=event.severity,
                details=event.details,
                fired_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            )
            if row is None:
                duplicates += 1
            else:
                enqueued += 1
        return {"fired": len(fired), "enqueued": enqueued, "duplicates": duplicates}

    def _cycle(self) -> dict[str, Any]:
        from app.services.alert_delivery import deliver_pending

        db = self._session()
        try:
            evaluation = self.evaluate_and_enqueue(db)
            delivery = deliver_pending(db)
            return {**evaluation, **delivery}
        finally:
            db.close()

    async def run_once(self) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._cycle)
            self._last_result = dict(result)
            self._last_error = None
            return result
        except Exception as exc:  # noqa: BLE001 - el loop debe sobrevivir
            self._last_error = type(exc).__name__
            _LOG.error("Ciclo de entrega de alertas falló error_type=%s", type(exc).__name__)
            return {"status": "failed"}
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
