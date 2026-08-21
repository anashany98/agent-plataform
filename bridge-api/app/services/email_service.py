"""Email integrado (P2, T-044): plantillas, firma y tracking.

Sobre el pipeline existente (``automations.send_email`` → SMTP o spool local
con degradación auditada), este módulo añade:

- ``TEMPLATE_VARIABLES``: catálogo estable de variables ``{{key}}``.
- ``render_template_text``: sustitución de variables (las claves más largas
  primero para no colisionar prefijos).
- ``build_tracking_html`` / ``rewrite_click_urls``: inserta el pixel de
  apertura (PNG 1x1) y reescribe los enlaces http/https a
  ``{base}/email-tracking/{token}/click?u=…`` para registrar clics.
- ``send_templated_email``: carga la plantilla activa por nombre, renderiza
  asunto/cuerpo + firma (de plantilla o de ``EmailSettings``), registra el
  evento ``sent`` (token → destinatario/plantilla) y envía por el pipeline
  existente.

El tracking es honesto: sin ``EMAIL_TRACKING_BASE_URL`` no se emiten URLs
rotas (se omite y se audita); los eventos ``open``/``click`` los registran
los endpoints públicos de forma idempotente (uno por token y tipo).
"""

from __future__ import annotations

import datetime
import logging
import re
import urllib.parse
import uuid
from typing import Any

from app.config import settings
from app.models.models import EmailSettings, EmailTemplate, EmailTrackingEvent
from app.services.automations import EmailResult, send_email
from sqlalchemy.orm import Session

_LOG = logging.getLogger("bridge.email_service")

# PNG 1x1 transparente (bytes constantes, sin red ni recursos).
TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Catálogo estable de variables disponibles en plantillas.
TEMPLATE_VARIABLES: list[dict[str, str]] = [
    {
        "key": "store_name",
        "label": "Nombre de la tienda",
        "description": "``COMMERCE_STORE_NAME`` de la instalación.",
    },
    {
        "key": "lead.first_name",
        "label": "Nombre del lead",
        "description": "Nombre de pila del destinatario.",
    },
    {
        "key": "lead.email",
        "label": "Email del lead",
        "description": "Dirección del destinatario.",
    },
    {
        "key": "quote.id",
        "label": "ID del presupuesto",
        "description": "Identificador del presupuesto referenciado.",
    },
    {
        "key": "quote.grand_total",
        "label": "Total del presupuesto",
        "description": "Importe total (formato decimal).",
    },
    {
        "key": "order.id",
        "label": "ID del pedido",
        "description": "Identificador del pedido referenciado.",
    },
]

_URL_RE = re.compile(r"https?://[^\s<>\"']+")

# HTML mínimo usado para decidir si el cuerpo parece HTML (entonces el pixel
# de apertura tiene sentido).
_HTML_HINTS = ("<html", "<body", "<div", "<p ", "<a ", "<table", "<h1", "<h2", "<h3")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render_template_text(text: str, variables: dict[str, Any]) -> str:
    """Sustituye ``{{key}}`` por el valor; las claves más largas primero."""

    rendered = text
    for key in sorted(variables.keys(), key=len, reverse=True):
        rendered = rendered.replace("{{" + key + "}}", _stringify(variables[key]))
    return rendered


def looks_like_html(body: str) -> bool:
    return "<" in body and ">" in body and any(hint in body for hint in _HTML_HINTS)


def rewrite_click_urls(text: str, base_url: str, token: str) -> str:
    """Reescribe enlaces http/https a la ruta de tracking de clics."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:!?)")
        redirect = f"{base_url.rstrip('/')}/email-tracking/{token}/click"
        encoded = urllib.parse.quote(url, safe="")
        return f"{redirect}?u={encoded}"

    return _URL_RE.sub(_replace, text)


def build_tracking_html(body: str, base_url: str, token: str) -> str:
    """Cuerpo HTML con clics reescritos y el pixel de apertura al final."""

    html = rewrite_click_urls(body, base_url, token)
    pixel = (
        f'<img src="{base_url.rstrip("/")}/email-tracking/{token}/open.png" '
        'width="1" height="1" alt="" />'
    )
    if "</body>" in html:
        return html.replace("</body>", f"{pixel}</body>")
    return f"{html}\n{pixel}"


def get_or_create_email_settings(db: Session) -> EmailSettings:
    """Devuelve (creando si falta) la fila única de settings por instalación."""

    row = db.query(EmailSettings).first()
    if row is None:
        row = EmailSettings(signature=None, tracking_enabled=True)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def email_settings_response(row: EmailSettings) -> dict[str, Any]:
    return {
        "signature": row.signature,
        "tracking_enabled": row.tracking_enabled,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def template_response(template: EmailTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "subject": template.subject,
        "body": template.body,
        "signature": template.signature,
        "is_active": template.is_active,
        "created_by": template.created_by,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def _register_event(
    db: Session,
    *,
    token: str,
    event_type: str,
    url: str | None = None,
    to: str | None = None,
    template_name: str | None = None,
) -> EmailTrackingEvent | None:
    """Registra un evento de tracking (idempotente por token y tipo).

    Devuelve None si el evento ya existía (p. ej. recarga del pixel). El
    commit lo hace el caller (para los eventos ``sent`` viaja con el de
    ``send_email``; para open/click lo hace este helper).
    """

    existing = (
        db.query(EmailTrackingEvent)
        .filter(
            EmailTrackingEvent.token == token,
            EmailTrackingEvent.event_type == event_type,
        )
        .first()
    )
    if existing is not None:
        return None
    event = EmailTrackingEvent(
        token=token,
        event_type=event_type,
        url=url,
        to=to,
        template_name=template_name,
    )
    db.add(event)
    db.commit()
    return event


def send_templated_email(
    db: Session,
    *,
    template_name: str,
    to: str,
    variables: dict[str, Any] | None = None,
    actor: str | None = None,
    provider_fallback: bool | None = None,
) -> tuple[EmailResult, str | None]:
    """Envía un email usando una plantilla activa por nombre.

    Renderiza asunto/cuerpo con las variables del catálogo, añade la firma
    (de plantilla o la de instalación) y, si el tracking está activo y hay
    ``EMAIL_TRACKING_BASE_URL``, inserta el pixel de apertura y reescribe los
    clics. Devuelve ``(EmailResult, tracking_token)``; sin base URL el token
    es ``None`` y el envío se audita como ``email.tracking_skipped``.
    """

    template = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.name == template_name, EmailTemplate.is_active.is_(True))
        .first()
    )
    if template is None:
        _audit_email_event(
            db,
            event_type="email.template_not_found",
            details={"template_name": template_name},
            actor=actor,
        )
        result = EmailResult(
            provider="template",
            to=to,
            subject=template_name,
            accepted=False,
            reference=f"template-not-found-{uuid.uuid4().hex[:12]}",
            error=f"email_template_not_found:{template_name}",
            status="failed",
        )
        return result, None

    variables = variables or {}
    settings_row = get_or_create_email_settings(db)
    subject = render_template_text(template.subject, variables)
    signature = (template.signature or settings_row.signature or "").strip()
    body = render_template_text(template.body, variables).strip()
    if signature:
        body = f"{body}\n\n--\n{signature}"

    base_url = (settings.EMAIL_TRACKING_BASE_URL or "").strip()
    tracking_enabled = bool(settings_row.tracking_enabled)
    token = None
    html_body = None
    if tracking_enabled and base_url:
        token = f"tk-{uuid.uuid4().hex}"
        if looks_like_html(body):
            html_body = build_tracking_html(body, base_url, token)
        # Los clics se reescriben también en el texto plano (funciona en
        # ambos formatos); el pixel de apertura solo en HTML.
        body = rewrite_click_urls(body, base_url, token)
    elif tracking_enabled and not base_url:
        _audit_email_event(
            db,
            event_type="email.tracking_skipped",
            details={"template_name": template.name, "reason": "sin_base_url"},
            actor=actor,
        )

    result = send_email(
        db,
        to=to,
        subject=subject,
        body=body,
        html=html_body,
        tracking_token=token,
        actor=actor,
        provider_fallback=provider_fallback,
    )
    if token and (result.accepted or result.status == "queued_for_manual_delivery"):
        _register_event(
            db,
            token=token,
            event_type="sent",
            to=to,
            template_name=template.name,
        )
    return result, token


def _audit_email_event(
    db: Session,
    *,
    event_type: str,
    details: dict[str, Any],
    actor: str | None,
) -> None:
    from app.models.models import AuditLog

    db.add(
        AuditLog(
            correlation_id=str(uuid.uuid4()),
            agent_id="system",
            user_id=actor,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status="error" if "not_found" in event_type else "pending",
            details=details,
        )
    )
    db.commit()
