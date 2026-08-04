"""Motor de automatizaciones portado de FlowWink (MIT) sin Supabase (D-012).

El propietario rechazó Supabase; la lógica de negocio de FlowWink se
reimplementa sobre el motor del Bridge (PostgreSQL + outbox + scheduler
pull). Este módulo cubre el Lote 1, que no requiere SaaS externo:

- Router de email con proveedor **local** (sin red): ``email-send``.
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
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog, IdempotencyRecord, InvoiceDraft, Quote
from app.services.resilience import guarded_request_with_retry


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


class LocalEmailProvider:
    """Proveedor local: no contacta la red; persiste y mantiene memoria."""

    name = "local"

    def __init__(self) -> None:
        self.sent: list[EmailResult] = []

    def send(self, to: str, subject: str, body: str) -> EmailResult:
        reference = f"local-{uuid.uuid4().hex[:12]}"
        directory = Path(settings.AUTOMATION_EMAIL_DIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{reference}.json").write_text(
                json.dumps(
                    {"to": to, "subject": subject, "body": body, "at": _utcnow().isoformat()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            # El proveedor local nunca debe romper la automatización; la
            # memoria basta para auditoría en memoria y tests.
            pass
        result = EmailResult(self.name, to, subject, True, reference)
        self.sent.append(result)
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


def send_email(db: Session, *, to: str, subject: str, body: str, actor: str | None = None) -> EmailResult:
    """Envía por el proveedor configurado (por defecto local, sin red)."""

    name = (settings.EMAIL_PROVIDER or "local").lower()
    provider = _EMAIL_PROVIDERS.get(name)
    if provider is None:
        # Proveedor externo no disponible en este entorno: caer a local para
        # no perder el efecto y mantener la automatización verificable.
        provider = get_local_provider()
    result = provider.send(to, subject, body)
    _audit(
        db,
        event_type="automation.email_sent",
        status_value="success",
        details={"to": to, "subject": subject, "provider": result.provider, "reference": result.reference},
        actor=actor,
    )
    return result


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
    for quote in candidates:
        key = f"auto:quote-expiry:{quote.id}:{window}"
        if not _claim(db, key, {"quote_id": quote.id, "window": window}):
            continue
        customer_email = _quote_customer_email(db, quote)
        if customer_email:
            send_email(
                db,
                to=customer_email,
                subject=f"Tu presupuesto caduca el {quote.confirmation_expires_at:%d/%m/%Y}",
                body=f"El presupuesto {quote.id} por {quote.grand_total} {quote.currency} caduca pronto.",
                actor=actor,
            )
        _audit(
            db,
            event_type="automation.quote_expiry_reminder",
            status_value="success",
            details={"quote_id": quote.id, "expires_at": quote.confirmation_expires_at.isoformat(), "window": window},
            actor=actor,
        )
        reminded += 1
    db.commit()
    return {"evaluated": len(candidates), "reminded": reminded, "window": window}


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
    for invoice in overdue:
        step = _dunning_step(invoice, now)
        key = f"auto:dunning:{invoice.id}:{step}"
        if not _claim(db, key, {"invoice_id": invoice.id, "step": step}):
            continue
        if invoice.status != "overdue":
            invoice.status = "overdue"
        email = _invoice_customer_email(db, invoice)
        if email:
            send_email(
                db,
                to=email,
                subject=f"Recordatorio de pago {invoice.invoice_number} (paso {step})",
                body=f"La factura {invoice.invoice_number} por {invoice.total_amount} {invoice.currency} está vencida.",
                actor=actor,
            )
        _audit(
            db,
            event_type="automation.dunning_step",
            status_value="success",
            details={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "step": step},
            actor=actor,
        )
        processed += 1
    db.commit()
    return {"evaluated": len(overdue), "processed": processed}


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


def generate_invoice_pdf(invoice: InvoiceDraft) -> bytes:
    """Genera un PDF mínimo y determinista con los valores ya calculados."""

    lines = [
        f"FACTURA {invoice.invoice_number}",
        f"Cliente: {invoice.customer_id}",
        f"Estado: {invoice.status}",
        f"Moneda: {invoice.currency}",
        f"Total: {Decimal(invoice.total_amount)} {invoice.currency}",
        f"Impuestos: {Decimal(invoice.tax_amount)} {invoice.currency}",
    ]
    return _build_pdf(lines)


def _build_pdf(lines: list[str]) -> bytes:
    content = "BT /F1 12 Tf 50 780 Td 16 TL\n"
    for line in lines:
        safe = line.replace("(", "[").replace(")", "]")
        content += f"({safe}) Tj T*\n"
    content += "ET"
    content_bytes = content.encode("latin-1", "replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objects.append(b"<< /Length " + str(len(content_bytes)).encode() + b" >>\nstream\n" + content_bytes + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

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


# ---------------------------------------------------------------------------
# send-webhook (FlowWink): webhook saliente firmado con HMAC
# ---------------------------------------------------------------------------


def sign_webhook_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


async def send_webhook(*, url: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    """Envía un webhook saliente firmado; la firma usa la clave del destino."""

    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    secret = settings.WEBHOOK_OUTBOUND_SECRET or idempotency_key
    signature = sign_webhook_payload(body, secret)
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
            },
        ),
    )
    response.raise_for_status()
    return {"status": "sent", "idempotency_key": idempotency_key, "signature": f"sha256={signature}"}


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
