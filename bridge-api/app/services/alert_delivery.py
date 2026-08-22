"""Entrega externa y durable de alertas (SS-07).

Ciclo de vida de una alerta:

1. ``enqueue_alert`` la persiste en ``alert_deliveries`` con una clave de
   deduplicación ``{rule_id}:{ventana temporal}``: mientras la condición
   persiste, las repeticiones dentro de la ventana colapsan en una sola
   fila (UniqueConstraint + integridad a prueba de carreras).
2. ``deliver_pending`` procesa el lote vencido: webhook firmado (HMAC
   SHA256 con tolerancia anti-replay) y/o email vía el proveedor de email
   configurado (SMTP real o spool local auditado).
3. El fallo programa reintentos con backoff exponencial hasta
   ``max_attempts``; agotados, la alerta queda ``dead`` y visible en
   métricas — nunca se pierde silenciosamente.

El transporte HTTP se inyecta para tests (``httpx.MockTransport``); en
producción se usa un cliente con timeout corto para no bloquear el worker.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
from app.config import settings
from app.models.models import AlertDelivery
from sqlalchemy.orm import Session


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def dedup_key_for(rule_id: str, *, at: datetime.datetime | None = None) -> str:
    """Clave anti-tormenta: regla + ventana temporal configurada."""

    moment = at or utcnow()
    window = max(60, int(settings.ALERT_DEDUP_WINDOW_SEC))
    bucket = int(moment.timestamp()) // window
    return f"{rule_id}:{bucket}"


def enqueue_alert(
    db: Session,
    *,
    rule_id: str,
    summary: str,
    severity: str = "warning",
    details: dict[str, Any] | None = None,
    fired_at: datetime.datetime | None = None,
) -> AlertDelivery | None:
    """Persiste la alerta si no existe ya en la ventana de deduplicación.

    Devuelve la fila creada, o ``None`` si era un duplicado. La carrera
    entre dos workers que insertan la misma clave se resuelve en la BD
    (UniqueConstraint): el perdedor hace rollback limpio.
    """

    from app.models.models import AlertDelivery as Model

    moment = fired_at or utcnow()
    row = Model(
        rule_id=rule_id[:128],
        severity=(severity or "warning")[:16],
        summary=summary,
        details=details or {},
        dedup_key=dedup_key_for(rule_id, at=moment)[:128],
        next_attempt_at=moment,
        max_attempts=int(settings.ALERT_MAX_ATTEMPTS),
    )
    db.add(row)
    try:
        db.commit()
        return row
    except Exception:
        db.rollback()
        return None


def compute_backoff(attempts: int) -> datetime.timedelta:
    """Backoff exponencial desde 30 s, tope 1 hora."""

    seconds = min(3600, 30 * (2 ** max(0, attempts - 1)))
    return datetime.timedelta(seconds=seconds)


def _alert_payload(row: AlertDelivery) -> dict[str, Any]:
    return {
        "rule_id": row.rule_id,
        "severity": row.severity,
        "summary": row.summary,
        "details": row.details or {},
        "installation_id": row.installation_id,
        "alert_id": row.id,
        "fired_at": row.created_at.isoformat() if row.created_at else None,
        "attempt": row.attempts + 1,
    }


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256)
    return mac.hexdigest()


def _deliver_webhook(row: AlertDelivery, *, transport: httpx.BaseTransport | None = None) -> None:
    url = settings.ALERT_WEBHOOK_URL.strip()
    if not url:
        raise RuntimeError("ALERT_WEBHOOK_URL no configurada")
    body = json.dumps(_alert_payload(row), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(utcnow().timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-Bridge-Alert-Timestamp": timestamp,
    }
    if settings.ALERT_WEBHOOK_SECRET:
        headers["X-Bridge-Alert-Signature"] = _sign(settings.ALERT_WEBHOOK_SECRET, timestamp, body)
    with httpx.Client(timeout=5.0, transport=transport) as client:
        response = client.post(url, content=body, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"webhook_status_{response.status_code}")


def _deliver_email(db: Session, row: AlertDelivery) -> None:
    recipients = [item.strip() for item in settings.ALERT_EMAIL_TO.split(",") if item.strip()]
    if not recipients:
        raise RuntimeError("ALERT_EMAIL_TO no configurado")

    from app.services import automations

    payload_lines = [
        f"Regla: {row.rule_id}",
        f"Severidad: {row.severity}",
        "",
        row.summary,
        "",
        "Detalle:",
        json.dumps(row.details or {}, ensure_ascii=False, indent=2),
        "",
        f"Instalación: {row.installation_id}",
        f"Intento: {row.attempts + 1}/{row.max_attempts}",
    ]
    for recipient in recipients:
        result = automations.send_email(
            db,
            to=recipient,
            subject=f"[bridge:{row.severity}] {row.summary}",
            body="\n".join(payload_lines),
            actor="alert-delivery-worker",
        )
        delivered_states = {"sent", "queued_for_manual_delivery"}
        if getattr(result, "status", "") not in delivered_states:
            raise RuntimeError(
                f"email_status_{getattr(result, 'status', 'unknown')}"
            )


def deliver_pending(
    db: Session,
    *,
    now: datetime.datetime | None = None,
    transport: httpx.BaseTransport | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Entrega el lote de alertas pendientes vencidas.

    Un canal fallido NO contamina al otro: si el webhook falla pero el
    email funciona, la alerta queda entregada (el error del webhook se
    registra en ``last_error`` como evidencia).
    """

    moment = now or utcnow()
    due = (
        db.query(AlertDelivery)
        .filter(
            AlertDelivery.status == "pending",
            AlertDelivery.next_attempt_at <= moment,
        )
        .order_by(AlertDelivery.next_attempt_at.asc())
        .limit(limit)
        .all()
    )
    channels = _configured_channels()
    summary: dict[str, Any] = {
        "evaluated": len(due),
        "delivered": 0,
        "retried": 0,
        "dead": 0,
        "webhook_errors": [],
        "email_errors": [],
    }
    for row in due:
        row.attempts = int(row.attempts or 0) + 1
        webhook_error: str | None = None
        if "webhook" in channels:
            try:
                _deliver_webhook(row, transport=transport)
            except Exception as exc:  # noqa: BLE001 - canal degradado, sigue email
                webhook_error = type(exc).__name__
                summary["webhook_errors"].append({"rule_id": row.rule_id, "error": webhook_error})
        email_error: str | None = None
        if "email" in channels:
            try:
                _deliver_email(db, row)
            except Exception as exc:  # noqa: BLE001 - canal degradado, se reintenta
                email_error = type(exc).__name__
                summary["email_errors"].append({"rule_id": row.rule_id, "error": email_error})
        errors = [item for item in (webhook_error, email_error) if item]
        if not channels:
            row.last_error = "no_alert_channel_configured"
            row.next_attempt_at = utcnow() + compute_backoff(row.attempts)
            summary["retried"] += 1
        elif not errors:
            # Todos los canales configurados funcionaron.
            row.status = "delivered"
            row.delivered_at = utcnow()
            summary["delivered"] += 1
        elif len(errors) < len(channels):
            # Algún canal funcionó: entregada, con el fallo como evidencia.
            row.status = "delivered"
            row.delivered_at = utcnow()
            row.last_error = "; ".join(errors)
            summary["delivered"] += 1
        elif row.attempts >= int(row.max_attempts):
            row.status = "dead"
            row.last_error = "; ".join(errors)
            summary["dead"] += 1
        else:
            row.last_error = "; ".join(errors)
            row.next_attempt_at = utcnow() + compute_backoff(row.attempts)
            summary["retried"] += 1
        db.commit()
    return summary


def _configured_channels() -> list[str]:
    channels: list[str] = []
    if settings.ALERT_WEBHOOK_URL.strip():
        channels.append("webhook")
    if settings.ALERT_EMAIL_TO.strip():
        channels.append("email")
    return channels


def new_alert_correlation() -> str:
    return uuid.uuid4().hex
