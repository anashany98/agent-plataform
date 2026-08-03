"""Outbox durable con reintentos acotados y dead-letter queue.

Reglas:

- Cada efecto externo pendiente es una fila ``OutboxMessage`` con clave de
  idempotencia única por instalación y tema: encolar dos veces el mismo
  efecto no duplica el trabajo.
- El procesamiento usa claim CAS (``pending → processing``): dos workers no
  pueden despachar el mismo mensaje.
- Fallo transitorio: backoff exponencial determinista y ``attempt_count``
  persistente. Al agotar ``max_attempts`` el mensaje pasa a ``dead`` (DLQ)
  con su payload y error; nunca se borra ni se reintenta sin límite.
- Fallo permanente (``OutboxPermanentError``): directo a DLQ.
- Toda transición relevante queda auditada: envío, reintento programado,
  DLQ y reencolado manual.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog, OutboxMessage, utcnow

OUTBOX_STATES = ("pending", "processing", "sent", "dead")

Dispatcher = Callable[[OutboxMessage], Awaitable[dict[str, Any]]]


class OutboxTransientError(RuntimeError):
    """Fallo reintentable del proveedor externo."""


class OutboxPermanentError(RuntimeError):
    """Fallo definitivo: el mensaje va a la DLQ sin más reintentos."""


def _error_payload(exc: Exception, *, permanent: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
    }
    if permanent:
        payload["permanent"] = True
    return payload


class OutboxService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(
        self,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
        max_attempts: int | None = None,
    ) -> tuple[OutboxMessage, bool]:
        """Encola un efecto externo; devuelve (mensaje, creado?)."""

        if not topic.strip() or not idempotency_key.strip():
            raise ValueError("topic e idempotency_key son obligatorios")
        existing = self._find(topic, idempotency_key)
        if existing is not None:
            return existing, False
        message = OutboxMessage(
            topic=topic.strip(),
            idempotency_key=idempotency_key.strip(),
            payload=payload,
            max_attempts=int(max_attempts or settings.OUTBOX_MAX_ATTEMPTS),
        )
        self.db.add(message)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._find(topic, idempotency_key)
            if existing is None:
                raise
            return existing, False
        return message, True

    def _find(self, topic: str, idempotency_key: str) -> OutboxMessage | None:
        return (
            self.db.query(OutboxMessage)
            .filter(
                OutboxMessage.topic == topic,
                OutboxMessage.idempotency_key == idempotency_key,
            )
            .first()
        )

    @staticmethod
    def backoff_seconds(attempt: int) -> float:
        base = max(0.0, float(settings.OUTBOX_RETRY_BASE_DELAY_SEC))
        cap = max(base, float(settings.OUTBOX_RETRY_MAX_DELAY_SEC))
        return min(cap, base * (2 ** max(0, int(attempt) - 1)))

    def _audit_transition(
        self,
        message: OutboxMessage,
        *,
        event_type: str,
        status_value: str,
        details: dict[str, Any],
    ) -> None:
        self.db.add(
            AuditLog(
                correlation_id=str(uuid.uuid4()),
                agent_id="outbox_worker",
                user_id=None,
                event_type=event_type,
                provider="internal",
                model_name="deterministic",
                status=status_value,
                details={
                    "outbox_id": message.id,
                    "topic": message.topic,
                    "idempotency_key": message.idempotency_key,
                    **details,
                },
            )
        )

    async def deliver(self, message: OutboxMessage, dispatcher: Dispatcher) -> OutboxMessage:
        """Intento inmediato sobre un mensaje concreto (p. ej. en línea)."""

        if message.state != "pending":
            return message
        await self._claim_and_process(message, dispatcher, utcnow())
        return message

    async def process_due(
        self,
        *,
        dispatchers: dict[str, Dispatcher],
        now: datetime.datetime | None = None,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Procesa mensajes pendientes vencidos; devuelve un resumen."""

        now = now or utcnow()
        batch_size = max(1, min(int(limit or settings.OUTBOX_BATCH_SIZE), 64))
        due = (
            self.db.query(OutboxMessage)
            .filter(
                OutboxMessage.state == "pending",
                OutboxMessage.next_attempt_at <= now,
            )
            .order_by(OutboxMessage.next_attempt_at, OutboxMessage.created_at)
            .limit(batch_size)
            .all()
        )
        summary = {
            "evaluated": len(due),
            "sent": 0,
            "retry_scheduled": 0,
            "dead": 0,
            "skipped": 0,
        }
        for message in due:
            dispatcher = dispatchers.get(message.topic)
            if dispatcher is None:
                summary["skipped"] += 1
                continue
            await self._claim_and_process(message, dispatcher, now)
            if message.state == "sent":
                summary["sent"] += 1
            elif message.state == "dead":
                summary["dead"] += 1
            elif message.state == "pending":
                summary["retry_scheduled"] += 1
            else:
                summary["skipped"] += 1
        return summary

    async def _claim_and_process(
        self,
        message: OutboxMessage,
        dispatcher: Dispatcher,
        now: datetime.datetime,
    ) -> None:
        claimed = self.db.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == message.id,
                OutboxMessage.state == "pending",
            )
            .values(state="processing", updated_at=now)
        ).rowcount
        self.db.commit()
        if claimed != 1:
            self.db.refresh(message)
            return
        message.state = "processing"
        await self._process(message, dispatcher, now)

    async def _process(
        self,
        message: OutboxMessage,
        dispatcher: Dispatcher,
        now: datetime.datetime,
    ) -> None:
        try:
            response = await dispatcher(message)
        except OutboxPermanentError as exc:
            self._mark_dead(message, exc, now, permanent=True)
            return
        except Exception as exc:  # noqa: BLE001 — todo fallo acaba acotado por intentos/DLQ
            self._register_failure(message, exc, now)
            return
        message.state = "sent"
        message.response_body = response if isinstance(response, dict) else {"result": response}
        message.sent_at = now
        message.last_error = None
        message.updated_at = now
        self._audit_transition(
            message,
            event_type="outbox_sent",
            status_value="success",
            details={"attempts": int(message.attempt_count or 0) + 1},
        )
        self.db.commit()

    def _register_failure(
        self,
        message: OutboxMessage,
        exc: Exception,
        now: datetime.datetime,
    ) -> None:
        self.db.rollback()
        attempt_count = int(message.attempt_count or 0) + 1
        if attempt_count >= int(message.max_attempts):
            # El contador debe asignarse DESPUÉS del rollback y antes de
            # _mark_dead; si no, el rollback interno de la transición a DLQ
            # descarta la actualización y el mensaje muere con intentos de menos.
            message.attempt_count = attempt_count
            self._mark_dead(message, exc, now, permanent=False, session_rolled_back=True)
            return
        message.attempt_count = attempt_count
        message.last_error = _error_payload(exc)
        message.updated_at = now
        message.state = "pending"
        message.next_attempt_at = now + datetime.timedelta(
            seconds=self.backoff_seconds(message.attempt_count)
        )
        self._audit_transition(
            message,
            event_type="outbox_retry_scheduled",
            status_value="retry",
            details={
                "attempt_count": message.attempt_count,
                "next_attempt_at": message.next_attempt_at.isoformat(),
                "error": message.last_error,
            },
        )
        self.db.commit()

    def _mark_dead(
        self,
        message: OutboxMessage,
        exc: Exception,
        now: datetime.datetime,
        *,
        permanent: bool,
        session_rolled_back: bool = False,
    ) -> None:
        if not session_rolled_back:
            self.db.rollback()
        message.state = "dead"
        message.last_error = _error_payload(exc, permanent=permanent)
        message.updated_at = now
        self._audit_transition(
            message,
            event_type="outbox_dead",
            status_value="error",
            details={
                "attempt_count": message.attempt_count,
                "permanent": permanent,
                "error": message.last_error,
            },
        )
        self.db.commit()

    def retry_dead(self, message_id: str) -> OutboxMessage:
        """Reencola un mensaje de la DLQ para un nuevo ciclo de intentos."""

        message = self.db.query(OutboxMessage).filter(OutboxMessage.id == message_id).first()
        if message is None:
            raise LookupError("Mensaje de outbox no encontrado")
        if message.state != "dead":
            raise ValueError("Solo los mensajes en la DLQ pueden reencolarse")
        now = utcnow()
        previous_error = message.last_error
        message.state = "pending"
        message.attempt_count = 0
        message.next_attempt_at = now
        message.last_error = None
        message.updated_at = now
        self._audit_transition(
            message,
            event_type="outbox_requeued",
            status_value="success",
            details={"previous_error": previous_error},
        )
        self.db.commit()
        return message

    def counts(self) -> dict[str, int]:
        result = {state: 0 for state in OUTBOX_STATES}
        rows = (
            self.db.query(OutboxMessage.state, func.count(OutboxMessage.id))
            .group_by(OutboxMessage.state)
            .all()
        )
        for state, count in rows:
            if state in result:
                result[state] = int(count)
        result["total"] = sum(result[state] for state in OUTBOX_STATES)
        return result
