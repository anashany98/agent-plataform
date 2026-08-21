"""Worker durable de recordatorios de actividades (T-044).

Barre las actividades ``pending`` con ``remind_at <= now`` y sin
``reminded_at`` (el propio ``reminded_at`` es la llave de idempotencia: se
marca ANTES de enviar para que varias réplicas o un crash entre marca y
envío no dupliquen el recordatorio) y envía el email por el pipeline
existente (``automations.send_email``): proveedor configurado o spool local
con degradación auditada — nunca pérdida silenciosa.

El destinatario es ``remind_email`` o, por defecto, el email del lead; sin
destinatario resoluble se audita ``activity.reminder_skipped`` y la
actividad se salta (no se reintenta en bucle). El barrido usa el índice
compuesto ``ix_activity_due`` (installation_id, status, remind_at).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Callable
from typing import Any

from app.config import settings
from app.installation_context import installation_scope
from app.models.models import Activity, AuditLog, Lead
from app.security import Principal

_LOG = logging.getLogger("bridge.activity_reminder_worker")


def run_due_activity_reminders(
    *,
    principal: Principal | None = None,
    db: Any,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Procesa los recordatorios vencidos y devuelve el resumen.

    Separado del worker (síncrono, testable): recibe la sesión y el instante
    actual para que los tests puedan fijar el tiempo sin reloj real.
    """

    current = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    actor = principal or Principal(
        user_id="activity-reminder-worker",
        username="activity-reminder-worker",
        role="admin",
        installation_id=settings.INSTALLATION_ID,
        token_version=0,
        jti="activity-reminder-worker",
    )

    due = (
        db.query(Activity)
        .filter(
            Activity.status == "pending",
            Activity.remind_at.is_not(None),
            Activity.remind_at <= current,
            Activity.reminded_at.is_(None),
        )
        .order_by(Activity.remind_at.asc())
        .limit(200)
        .all()
    )
    if not due:
        return {"evaluated": 0, "processed": 0, "delivered": 0, "skipped": 0}

    lead_ids = {a.lead_id for a in due if a.lead_id}
    leads = (
        {lead.id: lead for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()}
        if lead_ids
        else {}
    )

    from app.services.automations import send_email

    delivered = 0
    processed = 0
    skipped = 0
    for activity in due:
        processed += 1
        # Idempotencia: marcar ANTES de enviar (véase docstring).
        activity.reminded_at = current
        recipient = activity.remind_email
        if not recipient and activity.lead_id and activity.lead_id in leads:
            recipient = leads[activity.lead_id].email
        if not recipient:
            skipped += 1
            db.add(
                AuditLog(
                    correlation_id=activity.id,
                    agent_id=actor.user_id,
                    event_type="activity.reminder_skipped",
                    provider="internal",
                    model_name="deterministic",
                    status="error",
                    details={
                        "activity_id": activity.id,
                        "reason": "sin_destinatario_resoluble",
                    },
                )
            )
            continue

        result = send_email(
            db,
            to=recipient,
            subject=f"Recordatorio: {activity.title}",
            body=(
                f"Actividad: {activity.title}\n"
                f"Tipo: {activity.kind}\n"
                f"Vencimiento: {activity.due_at.isoformat() if activity.due_at else 'sin fecha'}\n"
                f"Descripción: {activity.description or '—'}\n"
                f"Estado: pendiente"
            ),
            actor=actor.user_id,
        )
        if result.accepted or result.status == "queued_for_manual_delivery":
            delivered += 1
        db.add(
            AuditLog(
                correlation_id=activity.id,
                agent_id=actor.user_id,
                event_type="activity.reminder_sent",
                provider="internal",
                model_name="deterministic",
                status=(
                    "pending"
                    if result.status == "queued_for_manual_delivery"
                    else ("success" if result.accepted else "error")
                ),
                details={
                    "activity_id": activity.id,
                    "provider": result.provider,
                    "reference": result.reference,
                    "delivery_status": result.status,
                },
            )
        )

    db.commit()
    return {
        "evaluated": len(due),
        "processed": processed,
        "delivered": delivered,
        "skipped": skipped,
    }


class DurableActivityReminderWorker:
    """Copia el patrón de ``DurableScheduledTaskWorker`` (poll + install scope)."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
        installation_id: str | None = None,
        poll_sec: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._installation_id = installation_id or settings.INSTALLATION_ID
        configured_poll = getattr(settings, "ACTIVITY_REMINDER_WORKER_POLL_SEC", 30.0)
        self._poll_sec = max(
            1.0, float(poll_sec if poll_sec is not None else configured_poll)
        )
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._last_run_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] = {"evaluated": 0, "processed": 0}

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
            db = self._session()
            try:
                principal = Principal(
                    user_id="activity-reminder-worker",
                    username="activity-reminder-worker",
                    role="admin",
                    installation_id=self._installation_id,
                    token_version=0,
                    jti="activity-reminder-worker",
                )
                with installation_scope(self._installation_id):
                    return run_due_activity_reminders(principal=principal, db=db)
            finally:
                db.close()

        return await asyncio.to_thread(execute)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop())
        _LOG.info("activity reminder worker started (poll %ss)", self._poll_sec)

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None

    async def _loop(self) -> None:
        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                result = await self.run_once()
                self._last_result = result
                self._last_run_at = datetime.datetime.now(datetime.UTC).replace(
                    tzinfo=None
                ).isoformat()
            except Exception as exc:  # noqa: BLE001 — el worker nunca muere
                self._last_error = str(exc)
                _LOG.exception("activity reminder worker error")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_sec
                )
            except asyncio.TimeoutError:
                continue
