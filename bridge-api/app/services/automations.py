"""Motor de automatizaciones portado de FlowWink (MIT) sin Supabase (D-012).

El propietario rechazó Supabase; la lógica de negocio de FlowWink se
reimplementa sobre el motor del Bridge (PostgreSQL + outbox + scheduler
pull). Este módulo cubre el Lote 1, que no requiere SaaS externo:

- Router de email con proveedor **local** (sin red) o **SMTP real**
  (``EMAIL_PROVIDER=smtp``): ``email-send``. Si el SMTP falla y
  ``EMAIL_FALLBACK_TO_LOCAL_SPOOL`` está activo, el correo se encola en el
  spool local para entrega manual, con el error original auditado
  (degradación controlada, nunca pérdida silenciosa ni éxito fingido).
- ``quote-expiry-reminders``: sweep de presupuestos que caducan.
- ``dunning-processor``: secuencia de recordatorios de cobro vencidos.
- ``generate-invoice-pdf``: PDF determinista de un borrador de factura.
- ``send-webhook``: webhook saliente firmado con HMAC sobre el outbox.

Reglas de la misión que se respetan en cada port:

- Idempotencia durable: cada efecto se reclama con ``IdempotencyRecord``
  (clave por entidad+ventana), así un sweep repetido no duplica.
- Auditoría: cada transición relevante queda en ``AuditLog``.
- Sin efecto financiero sin aprobación: estos ports solo *notifican* o
  generan documentos de solo lectura; nunca mutan importes ni emiten
  facturas. El dunning marca estado ``overdue`` (no financiero) y envía
  recordatorios, pero no cobra ni modifica totales.
- Cálculos en Decimal en el backend; el PDF solo imprime valores ya
  calculados.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import io
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from app.config import settings
from app.installation_context import get_current_installation_id
from app.models.models import (
    AuditLog,
    Customer,
    IdempotencyRecord,
    InstallationAppearance,
    InvoiceDraft,
    Product,
    Quote,
    ScheduledTask,
)
from app.services.appearance_service import DEFAULT_ACCENT_COLOR, is_valid_accent_color
from app.services.resilience import guarded_request_with_retry
from sqlalchemy import func
from sqlalchemy.orm import Session


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Idempotencia ligera (reclamo por clave) reutilizando IdempotencyRecord
# ---------------------------------------------------------------------------


def _claim(db: Session, key: str, payload: dict[str, Any]) -> bool:
    """Devuelve True si esta llamada reclama el efecto; False si ya ocurrió."""

    existing = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.idempotency_key == key)
        .first()
    )
    if existing is not None and existing.state == "completed":
        return False
    if existing is None:
        db.add(
            IdempotencyRecord(
                idempotency_key=key,
                state="completed",
                status_code=200,
                attempt_count=1,
                event_payload=payload,
                response_body={"automation": True},
            )
        )
        db.flush()
    else:
        existing.state = "completed"
        existing.event_payload = payload
        db.flush()
    return True


def _mark_claim_failed(db: Session, key: str, error_type: str) -> None:
    record = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    if record is not None:
        record.state = "failed"
        record.status_code = 500
        record.last_error = {"type": error_type}
        db.flush()


def _audit(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: dict[str, Any],
    actor: str | None = None,
) -> None:
    db.add(
        AuditLog(
            correlation_id=f"automation-{uuid.uuid4().hex[:12]}",
            agent_id="automations",
            user_id=actor,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )


# ---------------------------------------------------------------------------
# Router de email con proveedor local (sin red)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EmailResult:
    provider: str
    to: str
    subject: str
    accepted: bool
    reference: str
    error: str | None = None
    status: str = "unknown"


class LocalEmailProvider:
    """Spool local: persiste para entrega manual, nunca afirma entrega."""

    name = "local"

    def __init__(self) -> None:
        self.queued: list[EmailResult] = []

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
        html: str | None = None,
        tracking_token: str | None = None,
    ) -> EmailResult:
        reference = f"queued_for_manual_delivery:{uuid.uuid4().hex[:12]}"
        directory = Path(settings.AUTOMATION_EMAIL_DIR)
        installation_id = get_current_installation_id()
        tenant_key = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()[:16]
        retention_days = max(1, int(settings.LIFECYCLE_DEFAULT_RETENTION_DAYS))
        delete_after = _utcnow() + datetime.timedelta(days=retention_days)
        filename = f"{tenant_key}__{reference.replace(':', '-')}.json"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / filename
            temporary = directory / f".{filename}.{uuid.uuid4().hex}.tmp"
            temporary.write_text(
                json.dumps(
                    {
                        "provider": "local_spool",
                        "delivery_status": "queued_for_manual_delivery",
                        "installation_id": installation_id,
                        "retention_days": retention_days,
                        "delete_after": delete_after.isoformat(),
                        "to": to,
                        "subject": subject,
                        "body": body,
                        "html": html,
                        "tracking_token": tracking_token,
                        "attachments": [
                            {
                                "filename": (att or {}).get("filename", "adjunto"),
                                "mime_type": (att or {}).get("mime_type", "application/octet-stream"),
                                "content_base64": base64.b64encode((att or {}).get("content", b"")).decode("ascii"),
                            }
                            for att in (attachments or [])
                        ],
                        "queued_at": _utcnow().isoformat(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            temporary.replace(target)
        except OSError as exc:
            # El proveedor local debe reportar el error en lugar de fingir
            # éxito: aceptar=False fuerza a la automatización a tratar el
            # envío como fallido y, si está conectada a un outbox/cola, a
            # reintentar o escalar. La auditoría recibe el motivo del fallo.
            return EmailResult(
                "local_spool",
                to,
                subject,
                False,
                reference=reference,
                error=f"local_spool_io_error:{type(exc).__name__}",
                status="failed",
            )
        result = EmailResult(
            "local_spool",
            to,
            subject,
            False,
            reference,
            status="queued_for_manual_delivery",
        )
        self.queued.append(result)
        return result


_EMAIL_PROVIDERS: dict[str, Any] = {"local": LocalEmailProvider()}


def register_email_provider(provider: Any) -> None:
    _EMAIL_PROVIDERS[provider.name] = provider


def get_local_provider() -> LocalEmailProvider:
    provider = _EMAIL_PROVIDERS["local"]
    if not isinstance(provider, LocalEmailProvider):
        provider = LocalEmailProvider()
        _EMAIL_PROVIDERS["local"] = provider
    return provider


def send_email(
    db: Session,
    *,
    to: str,
    subject: str,
    body: str,
    actor: str | None = None,
    provider_fallback: bool | None = None,
    attachments: list[dict[str, Any]] | None = None,
    html: str | None = None,
    tracking_token: str | None = None,
) -> EmailResult:
    """Envía por el proveedor configurado (``EMAIL_PROVIDER``, por defecto local).

    - ``local``: spool sin red (entrega manual), nunca afirma entrega.
    - ``smtp``: envío real vía ``SmtpEmailProvider`` (STARTTLS/SSL). El
      proveedor se registra de forma perezosa la primera vez.
    - ``ghl``: envío real vía ``GhlEmailProvider`` (upsert del contacto y
      mensaje email en GoHighLevel). El proveedor se registra de forma
      perezosa la primera vez.
    - Proveedor desconocido: fallar cerrado con ``accepted=False`` y error
      ``email_provider_not_registered``; el outbox/cola reintenta.

    ``attachments`` es una lista de ``{"filename", "content", "mime_type"}``
    (``content`` en bytes); el spool local los conserva en base64 y el
    proveedor SMTP los adjunta al mensaje.

    Degradación controlada (nunca pérdida silenciosa): si el proveedor
    configurado falla y ``EMAIL_FALLBACK_TO_LOCAL_SPOOL`` está activo (o el
    caller pasa ``provider_fallback=True``), el correo se encola en el spool
    local para entrega manual. El resultado conserva el error original y la
    auditoría registra ``automation.email_degraded_to_local`` con el motivo.
    """

    name = (settings.EMAIL_PROVIDER or "local").lower()
    provider = _EMAIL_PROVIDERS.get(name)
    if provider is None and name == "smtp":
        # Registro perezoso: no acopla el arranque ni la importación a SMTP.
        from app.services.smtp_provider import SmtpEmailProvider

        provider = SmtpEmailProvider()
        _EMAIL_PROVIDERS[name] = provider
    if provider is None and name == "ghl":
        # Registro perezoso: no acopla el arranque al adaptador GHL.
        from app.services.ghl_email_provider import GhlEmailProvider

        provider = GhlEmailProvider()
        _EMAIL_PROVIDERS[name] = provider
    if provider is None:
        # Fallar cerrado: reportar el error y dejar que la cola/outbox
        # reintente. NO fingir éxito cayendo a local sin pedirlo.
        result = EmailResult(
            provider=name,
            to=to,
            subject=subject,
            accepted=False,
            reference=f"failed-{uuid.uuid4().hex[:12]}",
            error=f"email_provider_not_registered:{name}",
            status="failed",
        )
        _audit(
            db,
            event_type="automation.email_failed",
            status_value="error",
            details={
                "to": to,
                "subject": subject,
                "provider": name,
                "error": result.error,
            },
            actor=actor,
        )
        return result
    result = provider.send(
        to,
        subject,
        body,
        attachments=attachments,
        html=html,
        tracking_token=tracking_token,
    )
    fallback_enabled = (
        settings.EMAIL_FALLBACK_TO_LOCAL_SPOOL
        if provider_fallback is None
        else provider_fallback
    )
    if not result.accepted and fallback_enabled and name != "local":
        # Degradación auditada al spool local: el correo NO se pierde; se
        # entrega manualmente. El resultado conserva el error del proveedor.
        original_error = result.error
        degraded = get_local_provider().send(
            to,
            subject,
            body,
            attachments=attachments,
            html=html,
            tracking_token=tracking_token,
        )
        degraded.error = original_error
        _audit(
            db,
            event_type="automation.email_degraded_to_local",
            status_value="pending",
            details={
                "to": to,
                "subject": subject,
                "provider": name,
                "reference": degraded.reference,
                "delivery_status": degraded.status,
                "error": original_error,
            },
            actor=actor,
        )
        return degraded
    queued = result.status == "queued_for_manual_delivery"
    _audit(
        db,
        event_type=(
            "automation.email_queued"
            if queued
            else ("automation.email_sent" if result.accepted else "automation.email_failed")
        ),
        status_value="pending" if queued else ("success" if result.accepted else "error"),
        details={
            "recipient_sha256": hashlib.sha256(to.lower().encode("utf-8")).hexdigest(),
            "subject_sha256": hashlib.sha256(subject.encode("utf-8")).hexdigest(),
            "provider": result.provider,
            "reference": result.reference,
            "delivery_status": result.status,
            "error": result.error,
        },
        actor=actor,
    )
    return result


# ---------------------------------------------------------------------------
# Notificaciones de automatización con HTML + tracking (EMAIL_PROVIDER=ghl)
# ---------------------------------------------------------------------------


def _automation_email_html(
    subject: str,
    body: str,
    base_url: str,
    token: str,
    accent: str,
) -> str:
    """Plantilla HTML de marca para notificaciones de automatización.

    Envuelve el cuerpo plano en un correo con la identidad del portal
    (barra de marca con el acento de la instalación, encabezado con el
    asunto escapado), reescribe los clics a la ruta de tracking y añade el
    pixel de apertura al final. ``subject`` se muestra escapado; ``accent``
    es un color ``#rrggbb`` (o el acento por defecto).
    """

    import html as _html

    from app.services.email_service import rewrite_click_urls

    # 1. Reescritura de clics sobre el texto plano, una sola pasada: la URL
    #    de tracking resultante NO vuelve a reescribirse dentro del wrapper.
    plain = rewrite_click_urls(body, base_url, token)
    paragraphs = "".join(
        f'<p style="margin:0 0 12px;">{_html.escape(p.strip()).replace(chr(10), "<br/>")}</p>'
        for p in plain.split("\n\n")
        if p.strip()
    ) or '<p style="margin:0 0 12px;"></p>'
    subject_escaped = _html.escape(subject)
    accent_hex = (accent or DEFAULT_ACCENT_COLOR).lstrip("#")
    header_bg = f"#{accent_hex}" if len(accent_hex) == 6 else DEFAULT_ACCENT_COLOR
    wrapper = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="margin:0;padding:0;background-color:#f5f5f7;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f7;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e5ea;">
<tr><td style="background-color:{header_bg};padding:18px 24px;">
<span style="color:#ffffff;font-size:16px;font-weight:600;">Agentes IA</span>
<span style="color:rgba(255,255,255,0.85);font-size:12px;"> · Control empresarial</span>
</td></tr>
<tr><td style="padding:24px;">
<h2 style="margin:0 0 14px;color:#1c1c1e;font-size:18px;line-height:1.3;">{subject_escaped}</h2>
<div style="color:#3a3a3c;font-size:14px;line-height:1.6;">{paragraphs}</div>
</td></tr>
<tr><td style="padding:14px 24px;border-top:1px solid #e5e5ea;color:#8e8e93;font-size:11px;">
Enviado automáticamente por Agentes IA. No respondas a este correo.
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    pixel = (
        f'<img src="{base_url.rstrip("/")}/email-tracking/{token}/open.png" '
        'width="1" height="1" alt="" />'
    )
    return wrapper + "\n" + pixel


def _prepare_automation_email(
    db: Session,
    *,
    to: str,
    subject: str,
    body: str,
    actor: str | None,
) -> tuple[str | None, str | None, str]:
    """HTML + tracking por defecto en notificaciones cuando ``EMAIL_PROVIDER=ghl``.

    Con GHL y el tracking activo (``EMAIL_TRACKING_BASE_URL`` configurada y
    ``tracking_enabled`` en el panel de Email integrado), envuelve el cuerpo
    en la plantilla HTML de marca, reescribe los clics, genera el token de
    apertura y registra el evento ``sent`` (idempotente por token).
    Devuelve ``(html, token, body)``; cuando no aplica devuelve
    ``(None, None, body)`` sin cambiar el comportamiento del resto de
    proveedores y audita el motivo (sin base URL / tracking apagado).
    """

    provider = (settings.EMAIL_PROVIDER or "local").strip().lower()
    if provider != "ghl":
        return None, None, body

    def _skip(reason: str) -> tuple[None, None, str]:
        _audit(
            db,
            event_type="automation.email.tracking_skipped",
            status_value="pending",
            details={
                "recipient_sha256": hashlib.sha256(to.lower().encode("utf-8")).hexdigest(),
                "subject_sha256": hashlib.sha256(subject.encode("utf-8")).hexdigest(),
                "provider": provider,
                "reason": reason,
            },
            actor=actor,
        )
        return None, None, body

    base_url = (settings.EMAIL_TRACKING_BASE_URL or "").strip()
    if not base_url:
        return _skip("sin_base_url")
    from app.services.email_service import get_or_create_email_settings

    if not bool(get_or_create_email_settings(db).tracking_enabled):
        return _skip("tracking_disabled")

    token = f"tk-{uuid.uuid4().hex}"
    html = _automation_email_html(
        subject, body, base_url, token, _resolve_pdf_accent(db)
    )
    from app.services.email_service import _register_event, rewrite_click_urls

    rewritten = rewrite_click_urls(body, base_url, token)
    _register_event(
        db,
        token=token,
        event_type="sent",
        to=to,
        template_name="automation",
    )
    return html, token, rewritten


# ---------------------------------------------------------------------------
# quote-expiry-reminders (FlowWink) sobre el modelo Quote del Bridge
# ---------------------------------------------------------------------------


def quote_expiry_reminders(
    db: Session,
    *,
    now: datetime.datetime | None = None,
    horizon_days: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Recuerda presupuestos a punto de caducar, idempotente por ventana."""

    now = now or _utcnow()
    horizon = now + datetime.timedelta(days=horizon_days or settings.AUTOMATION_QUOTE_EXPIRY_HORIZON_DAYS)
    week = now.isocalendar()
    window = f"{week[0]}-W{week[1]:02d}"

    candidates = (
        db.query(Quote)
        .filter(Quote.status == "draft", Quote.confirmation_expires_at <= horizon, Quote.confirmation_expires_at > now)
        .order_by(Quote.confirmation_expires_at.asc())
        .all()
    )

    reminded = 0
    queued = 0
    failed = 0
    for quote in candidates:
        key = f"auto:quote-expiry:{quote.id}:{window}"
        if not _claim(db, key, {"quote_id": quote.id, "window": window}):
            continue
        customer_email = _quote_customer_email(db, quote)
        delivery: EmailResult | None = None
        if customer_email:
            subject = f"Tu presupuesto caduca el {quote.confirmation_expires_at:%d/%m/%Y}"
            body_text = f"El presupuesto {quote.id} por {quote.grand_total} {quote.currency} caduca pronto."
            html, token, body_final = _prepare_automation_email(
                db,
                to=customer_email,
                subject=subject,
                body=body_text,
                actor=actor,
            )
            delivery = send_email(
                db,
                to=customer_email,
                subject=subject,
                body=body_final,
                html=html,
                tracking_token=token,
                actor=actor,
            )
        if delivery is not None and delivery.status == "queued_for_manual_delivery":
            queued += 1
        elif delivery is not None and delivery.accepted:
            reminded += 1
        else:
            failed += 1
            _mark_claim_failed(
                db,
                key,
                (delivery.error if delivery and delivery.error else "recipient_unavailable").split(":", 1)[0],
            )
        _audit(
            db,
            event_type=(
                "automation.quote_expiry_reminder_queued"
                if delivery and delivery.status == "queued_for_manual_delivery"
                else "automation.quote_expiry_reminder"
            ),
            status_value=(
                "pending"
                if delivery and delivery.status == "queued_for_manual_delivery"
                else ("success" if delivery and delivery.accepted else "error")
            ),
            details={
                "quote_id": quote.id,
                "expires_at": quote.confirmation_expires_at.isoformat(),
                "window": window,
                "delivery_status": delivery.status if delivery else "recipient_unavailable",
            },
            actor=actor,
        )
    db.commit()
    return {
        "evaluated": len(candidates),
        "reminded": reminded,
        "queued_for_manual_delivery": queued,
        "failed": failed,
        "window": window,
    }


def _quote_customer_email(db: Session, quote: Quote) -> str | None:
    from app.models.models import Customer

    customer = db.query(Customer).filter(Customer.id == quote.customer_id).first()
    return customer.email if customer else None


# ---------------------------------------------------------------------------
# dunning-processor (FlowWink): recordatorios de cobro, sin mutar importes
# ---------------------------------------------------------------------------


def dunning_processor(
    db: Session,
    *,
    now: datetime.datetime | None = None,
    overdue_days: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Avanza recordatorios de facturas vencidas; solo notifica y marca estado."""

    now = now or _utcnow()
    threshold = now - datetime.timedelta(days=overdue_days or settings.AUTOMATION_DUNNING_OVERDUE_DAYS)

    overdue = (
        db.query(InvoiceDraft)
        .filter(InvoiceDraft.created_at <= threshold, InvoiceDraft.status.in_(["draft", "sent", "overdue"]))
        .order_by(InvoiceDraft.created_at.asc())
        .all()
    )

    processed = 0
    queued = 0
    delivered = 0
    failed = 0
    for invoice in overdue:
        step = _dunning_step(invoice, now)
        key = f"auto:dunning:{invoice.id}:{step}"
        if not _claim(db, key, {"invoice_id": invoice.id, "step": step}):
            continue
        if invoice.status != "overdue":
            invoice.status = "overdue"
        email = _invoice_customer_email(db, invoice)
        delivery: EmailResult | None = None
        if email:
            subject = f"Recordatorio de pago {invoice.invoice_number} (paso {step})"
            body_text = f"La factura {invoice.invoice_number} por {invoice.total_amount} {invoice.currency} está vencida."
            html, token, body_final = _prepare_automation_email(
                db,
                to=email,
                subject=subject,
                body=body_text,
                actor=actor,
            )
            delivery = send_email(
                db,
                to=email,
                subject=subject,
                body=body_final,
                html=html,
                tracking_token=token,
                actor=actor,
            )
        if delivery is not None and delivery.status == "queued_for_manual_delivery":
            queued += 1
        elif delivery is not None and delivery.accepted:
            delivered += 1
        else:
            failed += 1
            _mark_claim_failed(
                db,
                key,
                (delivery.error if delivery and delivery.error else "recipient_unavailable").split(":", 1)[0],
            )
        _audit(
            db,
            event_type="automation.dunning_step",
            status_value=(
                "pending"
                if delivery and delivery.status == "queued_for_manual_delivery"
                else ("success" if delivery and delivery.accepted else "error")
            ),
            details={
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "step": step,
                "delivery_status": delivery.status if delivery else "recipient_unavailable",
            },
            actor=actor,
        )
        processed += 1
    db.commit()
    return {
        "evaluated": len(overdue),
        "processed": processed,
        "delivered": delivered,
        "queued_for_manual_delivery": queued,
        "failed": failed,
    }


def _dunning_step(invoice: InvoiceDraft, now: datetime.datetime) -> int:
    days = (now - invoice.created_at).days
    return max(1, min(4, days // max(1, settings.AUTOMATION_DUNNING_OVERDUE_DAYS)))


def _invoice_customer_email(db: Session, invoice: InvoiceDraft) -> str | None:
    from app.models.models import Customer

    customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    return customer.email if customer else None


# ---------------------------------------------------------------------------
# generate-invoice-pdf (FlowWink): PDF determinista de solo lectura
# ---------------------------------------------------------------------------


# Factores de anchura Helvetica (deterministas) para alinear a la derecha.
_HELV_AVG_WIDTH = 0.56


def _pdf_escape(text: str) -> str:
    """Escapa el contenido textual del PDF a latin-1 sin perder legibilidad.

    Paréntesis fuera del stream (patrón histórico) y normalización de la
    puntuación que no existe en latin-1 (em/en-dash, bullet, middot) a su
    equivalente ASCII para que la etiqueta del cliente nunca muestre ``?``.
    """

    text = text.replace("(", "[").replace(")", "]").replace("\\", "/")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("•", "*").replace("·", ".")
    return text


def _pdf_rgb(hex_color: str) -> str:
    """Convierte #RRGGBB al operador de relleno RGB del PDF (determinista)."""

    h = (hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        h = DEFAULT_ACCENT_COLOR.lstrip("#")
    try:
        r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        r, g, b = 0x24 / 255.0, 0x6B / 255.0, 0xFD / 255.0
    return f"{r:.3f} {g:.3f} {b:.3f}"


def _pdf_text_width(text: str, size: float) -> float:
    """Ancho aproximado determinista de un texto en Helvetica."""

    return len(text) * _HELV_AVG_WIDTH * size


def _resolve_pdf_accent(db: Session | None) -> str:
    """Acento de la instalación (T-061) sin efectos secundarios.

    Solo lectura: nunca crea la fila de apariencia (un generador de PDF no
    debe escribir). Sin ``db`` (tests herméticos) se usa el acento por
    defecto.
    """

    if db is None:
        return DEFAULT_ACCENT_COLOR
    row = db.query(InstallationAppearance).first()
    if row is not None and is_valid_accent_color(row.accent_color):
        return row.accent_color
    return DEFAULT_ACCENT_COLOR


def _invoice_customer_label(db: Session | None, customer_id: str) -> str:
    """Etiqueta legible del cliente (nombre + email) si está en la BD."""

    if db is not None:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer is not None:
            name = (customer.name or "").strip()
            email = (customer.email or "").strip()
            if name and email:
                return f"{name} — {email}"
            return name or email
    return str(customer_id)


# ---------------------------------------------------------------------------
# generate-invoice-pdf (FlowWink): PDF determinista de solo lectura
# ---------------------------------------------------------------------------


def generate_invoice_pdf(invoice: InvoiceDraft, db: Session | None = None) -> bytes:
    """Genera el PDF de la factura con la identidad del rediseño del portal.

    Tipografía del sistema (Helvetica regular/bold, el equivalente PDF de
    SF Pro/Segoe UI) y barra de marca con el acento de la instalación
    (T-061). Determinista: los mismos datos producen exactamente los mismos
    bytes. Sin ``db`` se usa el acento por defecto y el id del cliente.
    """

    accent = _resolve_pdf_accent(db)
    customer_label = _invoice_customer_label(db, invoice.customer_id)
    created_at = (
        invoice.created_at.strftime("%d/%m/%Y %H:%M") if invoice.created_at else "—"
    )
    meta: list[tuple[str, str]] = [
        ("Cliente", customer_label),
        ("Pedido", str(invoice.order_id)),
        ("Estado", str(invoice.status)),
        ("Moneda", str(invoice.currency)),
        ("Emitida", created_at),
    ]
    total_label = f"{Decimal(invoice.total_amount)} {invoice.currency}"
    return _build_pdf(
        blocks={
            "invoice_number": str(invoice.invoice_number),
            "meta": meta,
            "total": total_label,
        },
        accent=accent,
    )


def _build_pdf(blocks: dict[str, Any], accent: str) -> bytes:
    """Construye un PDF A4 determinista con la identidad del rediseño.

    Sin dependencias externas: barra de marca del color de acento, marca
    blanca, título de factura Helvetica-Bold y filas de metadatos con
    etiqueta gris y valor oscuro. El color del acento es el único dato
    variable del layout.
    """

    accent_rgb = _pdf_rgb(accent)
    dark = "0.11 0.11 0.12"  # #1C1C1E (texto primario iOS)
    gray = "0.45 0.45 0.47"  # texto secundario
    hairline = "0.85 0.85 0.87"
    commands: list[str] = []

    def text(x: float, y: float, size: float, font: str, rgb: str, value: str) -> None:
        commands.append(
            f"BT /{font} {size} Tf {rgb} rg {x:.1f} {y:.1f} Td ({_pdf_escape(value)}) Tj ET"
        )

    # Barra de marca con el acento de la instalación.
    commands.append(f"{accent_rgb} rg 0 782 612 60 re f")
    text(40, 814, 15, "F2", "1 1 1", "Agentes IA")
    text(40, 800, 9, "F1", "0.92 0.92 0.95", "Control empresarial")
    # Etiqueta y título de la factura.
    text(40, 764, 11, "F2", accent_rgb, "FACTURA")
    text(40, 736, 20, "F2", dark, blocks["invoice_number"])
    # Hairline de separación.
    commands.append(f"{hairline} rg 40 716 532 0.7 re f")
    # Metadatos: etiqueta gris + valor oscuro.
    y = 694
    for label, value in blocks["meta"]:
        text(40, y, 9, "F1", gray, label)
        text(180, y - 1, 11, "F1", dark, value)
        y -= 20
    # Bloque TOTAL.
    commands.append(f"{hairline} rg 40 560 532 0.7 re f")
    text(40, 528, 12, "F2", accent_rgb, "TOTAL")
    total_x = 572 - _pdf_text_width(blocks["total"], 14)
    text(total_x, 526, 14, "F2", dark, blocks["total"])
    # Pie: hairline + nota.
    commands.append(f"{hairline} rg 40 60 532 0.7 re f")
    text(40, 46, 8, "F1", gray, "Generado por Agentes IA - documento determinista de solo lectura")

    content = "\n".join(commands)
    content_bytes = content.encode("latin-1", "replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>"
    )
    objects.append(
        b"<< /Length " + str(len(content_bytes)).encode() + b" >>\nstream\n"
        + content_bytes
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_start = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode())
    return out.getvalue()


def send_invoice_email(
    db: Session,
    *,
    invoice: InvoiceDraft,
    order_id: str,
    customer_email: str,
    actor: str | None = None,
    store: str | None = None,
) -> EmailResult:
    """Envía la factura (PDF determinista) por email al cliente del pedido.

    Cierra la venta del chat: el correo lleva el PDF generado por
    ``generate_invoice_pdf`` como adjunto y el asunto incluye el número de
    factura y, si está configurada, la tienda de la persona por cliente. La
    entrega usa ``send_email``: SMTP real o spool local, con degradación
    auditada si el proveedor falla (nunca pérdida silenciosa).
    """

    pdf = generate_invoice_pdf(invoice, db=db)
    store_phrase = f" de {store}" if (store or "").strip() else ""
    subject = f"Tu factura {invoice.invoice_number}{store_phrase}"
    body = (
        f"Hola,\n\nGracias por tu compra. Adjuntamos la factura "
        f"{invoice.invoice_number} correspondiente al pedido {order_id}.\n\n"
        "Si tienes cualquier duda sobre el pedido o la factura, responde a "
        "este correo.\nUn saludo."
    )
    return send_email(
        db,
        to=customer_email,
        subject=subject,
        body=body,
        actor=actor,
        attachments=[
            {
                "filename": f"factura-{invoice.invoice_number}.pdf",
                "content": pdf,
                "mime_type": "application/pdf",
            }
        ],
    )


# ---------------------------------------------------------------------------
# send-webhook (FlowWink): webhook saliente firmado con HMAC
# ---------------------------------------------------------------------------


def sign_webhook_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _resolve_outbound_webhook_secret() -> tuple[str, str]:
    """Resuelve (secret, key_id) para firmar webhooks salientes.

    Política estricta: NO se usa la ``idempotency_key`` ni el ``url`` como
    secreto HMAC. Si ``WEBHOOK_OUTBOUND_SECRET`` no está configurado,
    abortamos el envío para no exponer un secreto derivado.
    """

    secret = settings.WEBHOOK_OUTBOUND_SECRET
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "WEBHOOK_OUTBOUND_SECRET ausente o demasiado corto. "
            "Configura un secreto de al menos 32 caracteres; NO se usa la "
            "idempotency_key como fallback (ver auditoría 2026-08-10)."
        )
    key_id = getattr(settings, "WEBHOOK_OUTBOUND_KEY_ID", None) or "primary"
    return secret, key_id


def _assert_outbound_url_allowed(url: str) -> None:
    """Valida que la URL destino NO apunte a redes privadas o loopback.

    Defensa SSRF: bloquea RFC1918 (10/8, 172.16/12, 192.168/16),
    loopback (127/8, ::1), link-local (169.254/16, fe80::/10) y
    metadata cloud (169.254.169.254). Permite HTTPS público y dominios
    explícitamente allowlistados vía ``WEBHOOK_OUTBOUND_ALLOWED_HOSTS``.
    """

    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"webhook_scheme_not_allowed:{parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("webhook_host_missing")

    # Allowlist explícita tiene prioridad.
    allowed_hosts = {
        h.strip().lower()
        for h in (getattr(settings, "WEBHOOK_OUTBOUND_ALLOWED_HOSTS", "") or "").split(",")
        if h.strip()
    }
    if host in allowed_hosts:
        return

    # Si la URL es pública (HTTPS) y el host NO se resuelve a IP privada
    # en este momento, la dejamos pasar. La resolución DNS se valida en
    # ``_assert_outbound_ip_allowed`` justo antes de abrir la conexión.
    try:
        import ipaddress
        import socket

        infos = socket.getaddrinfo(host, parsed.port or 443)
        for info in infos:
            sockaddr = info[4]
            ip = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                raise ValueError(
                    f"webhook_private_network_blocked:{host}->{ip}"
                )
    except socket.gaierror as exc:
        raise ValueError(f"webhook_dns_resolution_failed:{host}") from exc


async def send_webhook(*, url: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    """Envía un webhook saliente firmado; la firma usa la clave del destino.

    Política endurecida (auditoría 2026-08-10):
    - Secreto obligatorio desde configuración (``WEBHOOK_OUTBOUND_SECRET``);
      no se usa la ``idempotency_key`` como HMAC.
    - Cabeceras con ``key_id`` y ``timestamp`` para rotación y anti-replay.
    - Validación SSRF previa al envío (allowlist + bloqueo de redes
      privadas / loopback / metadata cloud).
    - Errores devueltos con ``accepted=False`` en lugar de fingir éxito.
    """

    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    try:
        _assert_outbound_url_allowed(url)
        secret, key_id = _resolve_outbound_webhook_secret()
    except (RuntimeError, ValueError) as exc:
        # Devolver sin lanzar excepción: la automatización debe saber
        # que el envío no ocurrió y el orquestador puede reencolarlo o
        # escalarlo.
        return {
            "status": "rejected",
            "idempotency_key": idempotency_key,
            "error": str(exc),
            "accepted": False,
        }

    timestamp = str(int(_utcnow().timestamp()))
    signature = sign_webhook_payload(body, secret)
    try:
        response = await guarded_request_with_retry(
            "webhook",
            lambda: httpx.AsyncClient(timeout=20).request(
                "POST",
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bridge-Webhook-Id": idempotency_key,
                    "X-Bridge-Webhook-Signature": f"sha256={signature}",
                    "X-Bridge-Webhook-Key-Id": key_id,
                    "X-Bridge-Webhook-Timestamp": timestamp,
                },
            ),
        )
        response.raise_for_status()
    except Exception as exc:
        return {
            "status": "failed",
            "idempotency_key": idempotency_key,
            "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            "accepted": False,
        }
    return {
        "status": "sent",
        "idempotency_key": idempotency_key,
        "signature": f"sha256={signature}",
        "key_id": key_id,
        "timestamp": timestamp,
        "accepted": True,
    }


# ---------------------------------------------------------------------------
# Sweep agregado (scheduler pull): lo invoca un cron externo
# ---------------------------------------------------------------------------


def run_automation_sweep(
    db: Session,
    *,
    now: datetime.datetime | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    quote = quote_expiry_reminders(db, now=now, actor=actor)
    dunning = dunning_processor(db, now=now, actor=actor)
    return {"quote_expiry": quote, "dunning": dunning, "ran_at": now.isoformat()}


# ---------------------------------------------------------------------------
# Catálogo de tareas programadas: tipos soportados por /scheduled-tasks y
# por los triggers por webhook (todos pasan por el gate de aprobación).
# ---------------------------------------------------------------------------

SCHEDULED_TASK_TYPES = (
    "automation_sweep",
    "prestashop_sync",
    "low_stock_alert",
    "cart_abandonment",
    "daily_digest",
    "agents_round",
)

# Patrón validado en ScheduledTaskRequest/ScheduledTaskPatchRequest (422 si
# un tipo no está en el catálogo).
SCHEDULED_TASK_TYPE_PATTERN = r"^(" + "|".join(SCHEDULED_TASK_TYPES) + r")$"


def run_scheduled_task(
    db: Session,
    *,
    task_type: str,
    payload: dict[str, Any] | None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el tipo de tarea del catálogo (dispatch centralizado).

    ``prestashop_sync`` NO se despacha aquí: es async y vive en ``main.py``
    (usa el adaptador y el lock Redis del sync). El resto se ejecuta en este
    módulo. Un tipo desconocido lanza ``ValueError``: el scheduler lo trata
    como fallo de tarea y lo audita (nunca se ignora en silencio).
    """

    if task_type == "automation_sweep":
        return run_automation_sweep(db, actor=actor)
    if task_type == "low_stock_alert":
        return low_stock_alert(db, payload=payload or {}, actor=actor)
    if task_type == "cart_abandonment":
        return cart_abandonment(db, payload=payload or {}, actor=actor)
    if task_type == "daily_digest":
        from app.services.daily_digest import send_daily_digest

        return send_daily_digest(db, actor=actor or "system")
    if task_type == "agents_round":
        from app.services.agent_proposals import run_agent_proposals

        return run_agent_proposals(db)
    raise ValueError(f"Tipo de tarea no soportado: {task_type}")


def ensure_agents_round_task(db: Session) -> dict[str, Any]:
    """Garantiza la ronda periódica de propuestas de agentes (dedupe por
    tipo). No reactiva una tarea pausada manualmente: el humano manda.

    Es la pieza que hace autónomo el ciclo CRM/social: el scheduler pull
    lanza ``agents_round`` cada hora y, según la configuración de autonomía
    de cada agente, las propuestas dentro del sobre autorizado se
    auto-ejecutan al instante; el resto queda pendiente en Aprobaciones.
    """

    existing = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.task_type == "agents_round")
        .first()
    )
    if existing is not None:
        return {"task_id": existing.id, "status": existing.status, "created": False}
    task = ScheduledTask(
        id=f"task-{uuid.uuid4().hex[:12]}",
        name="Ronda de propuestas de agentes",
        task_type="agents_round",
        payload={},
        interval_seconds=3_600,
        status="active",
        version=1,
        next_run_at=_utcnow() + datetime.timedelta(hours=1),
        created_by="system",
        updated_by="system",
    )
    db.add(task)
    db.commit()
    return {"task_id": task.id, "status": task.status, "created": True}


# ---------------------------------------------------------------------------
# low-stock-alert: una alerta resumen por ventana por producto con stock bajo
# ---------------------------------------------------------------------------


def low_stock_alert(
    db: Session,
    *,
    payload: dict[str, Any] | None = None,
    now: datetime.datetime | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Alerta por email de productos con stock disponible bajo el umbral.

    - Solo catálogo de confianza (``TRUSTED_PRODUCTION_CATALOG_SOURCES``:
      prestashop/import/local) — nunca demo ni fixtures.
    - Idempotente por producto y ventana ISO (semana): un producto ya
      alertado no se repite hasta la ventana siguiente.
    - Un único email resumen por ejecución a los destinatarios del payload
      (``recipients`` obligatorio, ``threshold`` por defecto 5,
      ``max_items`` por defecto 20).
    - Sin destinatarios → no se reclaman productos (nada se alerta en vacío).
    """

    from app.catalog_policy import TRUSTED_PRODUCTION_CATALOG_SOURCES

    payload = payload or {}
    now = now or _utcnow()
    threshold = max(0, min(100_000, int(payload.get("threshold", 5))))
    max_items = max(1, min(200, int(payload.get("max_items", 20))))
    recipients = [
        item.strip()
        for item in str(payload.get("recipients", "") or "").split(",")
        if item.strip()
    ]
    week = now.isocalendar()
    window = f"{week[0]}-W{week[1]:02d}"

    candidates = (
        db.query(Product)
        .filter(
            func.lower(func.trim(Product.source)).in_(
                tuple(sorted(TRUSTED_PRODUCTION_CATALOG_SOURCES))
            ),
            (Product.stock_quantity - Product.reserved_stock) <= threshold,
        )
        .order_by(
            (Product.stock_quantity - Product.reserved_stock).asc(),
            Product.name.asc(),
        )
        .limit(500)
        .all()
    )

    if not recipients:
        _audit(
            db,
            event_type="automation.low_stock_alert",
            status_value="error",
            details={
                "window": window,
                "threshold": threshold,
                "error": "recipients_missing",
            },
            actor=actor,
        )
        db.commit()
        return {
            "evaluated": len(candidates),
            "alerted": 0,
            "recipients": 0,
            "window": window,
            "error": "recipients_missing",
        }

    newly_low: list[Product] = []
    for product in candidates:
        key = f"auto:low-stock:{product.id}:{window}"
        if _claim(db, key, {"product_id": product.id, "window": window, "threshold": threshold}):
            newly_low.append(product)
    if not newly_low:
        db.commit()
        return {
            "evaluated": len(candidates),
            "alerted": 0,
            "recipients": len(recipients),
            "window": window,
            "threshold": threshold,
        }

    body_lines = [
        f"Productos con stock disponible por debajo del umbral ({threshold}) "
        f"en la ventana {window}:"
    ]
    for product in newly_low[:max_items]:
        available = int(product.stock_quantity) - int(product.reserved_stock)
        body_lines.append(
            f"- {product.name} (SKU {product.sku}): {available} disponibles"
        )
    if len(newly_low) > max_items:
        body_lines.append(f"... y {len(newly_low) - max_items} productos más.")

    delivered = 0
    failed = 0
    for recipient in recipients:
        subject = f"Alerta de stock bajo ({len(newly_low)} productos)"
        body_text = "\n".join(body_lines)
        html, token, body_final = _prepare_automation_email(
            db,
            to=recipient,
            subject=subject,
            body=body_text,
            actor=actor,
        )
        delivery = send_email(
            db,
            to=recipient,
            subject=subject,
            body=body_final,
            html=html,
            tracking_token=token,
            actor=actor,
        )
        if delivery.accepted or delivery.status == "queued_for_manual_delivery":
            delivered += 1
        else:
            failed += 1
    _audit(
        db,
        event_type="automation.low_stock_alert",
        status_value="success" if failed == 0 else "partial",
        details={
            "window": window,
            "threshold": threshold,
            "evaluated": len(candidates),
            "alerted": len(newly_low),
            "recipients": len(recipients),
            "delivered": delivered,
            "failed": failed,
        },
        actor=actor,
    )
    db.commit()
    return {
        "evaluated": len(candidates),
        "alerted": len(newly_low),
        "recipients": len(recipients),
        "delivered": delivered,
        "failed": failed,
        "window": window,
        "threshold": threshold,
    }


# ---------------------------------------------------------------------------
# cart-abandonment: follow-up de presupuestos en borrador olvidados
# ---------------------------------------------------------------------------


def cart_abandonment(
    db: Session,
    *,
    payload: dict[str, Any] | None = None,
    now: datetime.datetime | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Follow-up por email de presupuestos en ``draft`` sin confirmar.

    Un "carrito abandonado" es un presupuesto en borrador creado hace al
    menos ``abandoned_days`` (por defecto 3) y todavía confirmable
    (``confirmation_expires_at`` en el futuro). Idempotente por presupuesto
    y ventana ISO; solo notifica, nunca confirma ni muta importes.
    """

    payload = payload or {}
    now = now or _utcnow()
    abandoned_days = max(1, min(365, int(payload.get("abandoned_days", 3))))
    threshold_date = now - datetime.timedelta(days=abandoned_days)
    week = now.isocalendar()
    window = f"{week[0]}-W{week[1]:02d}"

    candidates = (
        db.query(Quote)
        .filter(
            Quote.status == "draft",
            Quote.created_at <= threshold_date,
            Quote.confirmation_expires_at > now,
        )
        .order_by(Quote.created_at.asc())
        .limit(500)
        .all()
    )

    reminded = 0
    queued = 0
    failed = 0
    for quote in candidates:
        key = f"auto:cart-abandon:{quote.id}:{window}"
        if not _claim(db, key, {"quote_id": quote.id, "window": window}):
            continue
        customer_email = _quote_customer_email(db, quote)
        delivery: EmailResult | None = None
        if customer_email:
            subject = f"Tu presupuesto {quote.id} sigue disponible"
            body_text = (
                f"Te recordamos tu presupuesto {quote.id} por "
                f"{quote.grand_total} {quote.currency}. Sigue vigente "
                f"hasta el {quote.confirmation_expires_at:%d/%m/%Y}."
            )
            html, token, body_final = _prepare_automation_email(
                db,
                to=customer_email,
                subject=subject,
                body=body_text,
                actor=actor,
            )
            delivery = send_email(
                db,
                to=customer_email,
                subject=subject,
                body=body_final,
                html=html,
                tracking_token=token,
                actor=actor,
            )
        if delivery is not None and delivery.status == "queued_for_manual_delivery":
            queued += 1
        elif delivery is not None and delivery.accepted:
            reminded += 1
        else:
            failed += 1
            _mark_claim_failed(
                db,
                key,
                (delivery.error if delivery and delivery.error else "recipient_unavailable").split(":", 1)[0],
            )
        _audit(
            db,
            event_type=(
                "automation.cart_abandonment_queued"
                if delivery and delivery.status == "queued_for_manual_delivery"
                else "automation.cart_abandonment"
            ),
            status_value=(
                "pending"
                if delivery and delivery.status == "queued_for_manual_delivery"
                else ("success" if delivery and delivery.accepted else "error")
            ),
            details={
                "quote_id": quote.id,
                "created_at": quote.created_at.isoformat(),
                "expires_at": quote.confirmation_expires_at.isoformat(),
                "window": window,
                "delivery_status": delivery.status if delivery else "recipient_unavailable",
            },
            actor=actor,
        )
    db.commit()
    return {
        "evaluated": len(candidates),
        "reminded": reminded,
        "queued_for_manual_delivery": queued,
        "failed": failed,
        "window": window,
        "abandoned_days": abandoned_days,
    }
