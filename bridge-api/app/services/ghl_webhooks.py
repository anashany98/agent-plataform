"""Webhooks de entrada de GoHighLevel (T-083).

Conecta GHL como canal de captación: los eventos ``ContactCreate``,
``ContactUpdate``, ``FormSubmit`` y ``OpportunityCreate``/``OpportunityUpdate``
alimentan el CRM local (tablas ``leads``/``opportunities``) con la misma
semántica de idempotencia que el resto del proyecto:

- La firma se verifica con ``X-Hub-Signature-256`` (convención de GHL:
  HMAC-SHA256 del body crudo con el secreto del webhook, hex, opcionalmente
  con prefijo ``sha256=``). Sin secreto configurado o sin cabecera → 401
  (fail-closed, deny-by-default).
- El anti-replay lo aporta la capa de idempotencia del endpoint: la clave
  ``ghl-inbound:<evento>:<id>`` hace que un replay del mismo evento devuelva
  la respuesta cacheada sin repetir el efecto.
- El efecto es determinista y sin red: upsert del lead por email (o por
  ``external_reference`` = id de contacto GHL cuando no hay email) y, si el
  evento trae oportunidad, upsert por ``external_reference`` = id de
  oportunidad GHL. Nunca borra ni descarta datos locales.

Hermeticidad: este módulo no toca la red; toda la verificación es HMAC local
y la aplicación es SQL. Los tests inyectan la firma y comprueban el efecto en
la BD del harness.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AuditLog, Lead, Opportunity, PipelineStage

_LOG = logging.getLogger("bridge.ghl_webhooks")

# Eventos de GHL que este adaptador entiende (mapeo a forma canónica).
# Cualquier otro evento se reconoce y se ignora de forma auditable.
_GHL_EVENT_TYPES: dict[str, str] = {
    "ContactCreate": "contact.created",
    "ContactUpdate": "contact.updated",
    "FormSubmit": "contact.created",
    "OpportunityCreate": "opportunity.created",
    "OpportunityUpdate": "opportunity.updated",
}


def verify_ghl_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verifica la firma ``X-Hub-Signature-256`` de GHL (HMAC-SHA256 del body).

    Sin secreto configurado o sin cabecera → ``False`` (fail-closed): el
    endpoint rechaza con 401. Acepta el valor con o sin el prefijo
    ``sha256=`` que envía GHL.
    """

    if not secret or not signature_header:
        return False
    supplied = signature_header.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, supplied)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _installation_id(db: Session) -> str:
    from app.installation_context import get_current_installation_id

    return get_current_installation_id() or "unknown"


def parse_ghl_webhook(body: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza el payload de GHL a un sobre canónico (o ``None`` si no
    se soporta el tipo de evento).

    GHL entrega el payload con ``type`` (p. ej. ``ContactCreate``) y los
    campos del evento en ``data`` (con fallback al propio cuerpo, que es lo
    que entregan algunos disparadores). El sobre devuelto es:

    - ``event_type``: forma canónica (``contact.created``, ...).
    - ``raw_type``: el ``type`` original de GHL.
    - ``contact_id`` / ``opportunity_id``: ids externos (si presentes).
    - ``email``, ``first_name``, ``last_name``, ``phone``, ``company_name``.
    - ``opportunity_name``, ``monetary_value``, ``stage``, ``status``.
    """

    if not isinstance(body, dict):
        return None
    raw_type = str(body.get("type") or "")
    event_type = _GHL_EVENT_TYPES.get(raw_type)
    if event_type is None:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        data = body

    def _pick(*keys: str) -> Any:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
            value = body.get(key)
            if value not in (None, ""):
                return value
        return None

    contact_id = str(_pick("contactId", "id") or "").strip()
    opportunity_id = str(
        _pick("opportunityId", "id") if raw_type.startswith("Opportunity") else ""
    ).strip()
    if raw_type.startswith("Opportunity"):
        # En eventos de oportunidad, ``id`` es la oportunidad; el contacto va
        # en ``contactId`` (o anidado en ``contact``).
        opportunity_id = str(_pick("opportunityId", "id") or "").strip()
        contact_id = str(_pick("contactId") or "").strip()
        contact_data = data.get("contact")
        if isinstance(contact_data, dict):
            for key in ("email", "firstName", "lastName", "phone", "companyName"):
                if not _pick(key) and contact_data.get(key):
                    data = {**data, key: contact_data.get(key)}

    first_name = str(_pick("firstName", "first_name", "contactName") or "").strip()
    last_name = str(_pick("lastName", "last_name") or "").strip()
    if first_name and last_name:
        first_name = f"{first_name} {last_name}".strip()

    monetary = _pick("monetaryValue", "monetary_value")
    try:
        monetary_value = float(monetary) if monetary not in (None, "") else None
    except (TypeError, ValueError):
        monetary_value = None

    stage = str(_pick("pipelineStageId", "pipelineStageKey") or "").strip() or None

    return {
        "event_type": event_type,
        "raw_type": raw_type,
        "contact_id": contact_id,
        "opportunity_id": opportunity_id,
        "email": str(_pick("email") or "").strip().lower() or None,
        "first_name": first_name or None,
        "phone": str(_pick("phone") or "").strip() or None,
        "company_name": str(_pick("companyName", "company_name") or "").strip() or None,
        "opportunity_name": str(_pick("name") or "").strip() or None,
        "monetary_value": monetary_value,
        "stage": stage,
        "status": str(_pick("status") or "").strip() or None,
    }


def _resolve_local_stage(db: Session, ghl_stage: str | None) -> str | None:
    """Mapea el id/etapa de GHL a una etapa local configurada, si existe.

    GHL manda el id opaco de su pipeline (``pipelineStageId``). Si coincide
    con el ``id`` o el ``key`` de una ``PipelineStage`` local se usa su key;
    si no, no se toca la etapa (nunca se inventa una etapa).
    """

    if not ghl_stage:
        return None
    for stage in db.query(PipelineStage).all():
        if str(stage.id) == ghl_stage or (stage.key and stage.key == ghl_stage):
            return stage.key
    return None


def apply_ghl_webhook(db: Session, envelope: dict[str, Any]) -> dict[str, Any]:
    """Aplica el evento GHL al CRM local (determinista, sin red, idempotente).

    - Contacto: upsert del ``Lead`` por email (o por ``external_reference``
      = id de contacto GHL cuando no hay email). Si no hay email ni id de
      contacto, el evento se ignora de forma auditable.
    - Oportunidad: upsert por ``external_reference`` = id de oportunidad GHL
      sobre el lead resuelto (por email o id de contacto).

    Todo queda auditado como ``ghl_webhook.inbound`` con la misma transacción
    del endpoint.
    """

    event_type = str(envelope.get("event_type") or "")
    email = envelope.get("email")
    contact_id = str(envelope.get("contact_id") or "").strip() or None
    opportunity_id = str(envelope.get("opportunity_id") or "").strip() or None

    lead: Lead | None = None
    if email:
        lead = (
            db.query(Lead)
            .filter(Lead.email == email)
            .order_by(Lead.created_at.asc())
            .first()
        )
    if lead is None and contact_id:
        lead = (
            db.query(Lead)
            .filter(Lead.external_reference == contact_id)
            .order_by(Lead.created_at.asc())
            .first()
        )
    if lead is None and not email and not contact_id:
        return {
            "status": "ignored",
            "reason": "missing_contact_data",
            "event_type": event_type,
        }

    if lead is None:
        if not email:
            return {
                "status": "ignored",
                "reason": "missing_email",
                "event_type": event_type,
                "contact_id": contact_id,
            }
        lead = Lead(
            email=email,
            first_name=str(envelope.get("first_name") or "Lead vía GHL")[:120],
            phone=envelope.get("phone"),
            company_name=envelope.get("company_name"),
            source="ghl",
            status="new",
        )
        if contact_id:
            lead.external_reference = contact_id
        db.add(lead)
        db.flush()
        created_lead = True
    else:
        created_lead = False
        if lead.source != "ghl" and envelope.get("event_type", "").startswith(
            "contact."
        ):
            lead.source = "ghl"
        if envelope.get("first_name"):
            lead.first_name = str(envelope["first_name"])[:120]
        if envelope.get("phone"):
            lead.phone = envelope["phone"]
        if envelope.get("company_name"):
            lead.company_name = envelope["company_name"]
        if contact_id:
            lead.external_reference = contact_id
        db.flush()

    opportunity: Opportunity | None = None
    created_opportunity = False
    if opportunity_id:
        opportunity = (
            db.query(Opportunity)
            .filter(Opportunity.external_reference == opportunity_id)
            .first()
        )
        if opportunity is None:
            opportunity = Opportunity(
                lead_id=lead.id,
                external_reference=opportunity_id,
                name=str(envelope.get("opportunity_name") or "Oportunidad GHL")[:200],
                monetary_value=envelope.get("monetary_value") or 0,
                pipeline="default",
                stage=_resolve_local_stage(db, envelope.get("stage")) or "new",
                stage_changed_at=_utcnow(),
                status=str(envelope.get("status") or "open")[:16] or "open",
                notes=[],
            )
            db.add(opportunity)
            db.flush()
            created_opportunity = True
        else:
            if envelope.get("opportunity_name"):
                opportunity.name = str(envelope["opportunity_name"])[:200]
            if envelope.get("monetary_value") is not None:
                opportunity.monetary_value = envelope["monetary_value"]
            if envelope.get("status"):
                opportunity.status = str(envelope["status"])[:16]
            local_stage = _resolve_local_stage(db, envelope.get("stage"))
            if local_stage and local_stage != opportunity.stage:
                opportunity.stage = local_stage
                opportunity.stage_changed_at = _utcnow()
            db.flush()

    result = {
        "status": "applied",
        "event_type": event_type,
        "raw_type": envelope.get("raw_type"),
        "lead_id": lead.id,
        "lead_created": created_lead,
        "lead_email": lead.email,
    }
    if opportunity is not None:
        result["opportunity_id"] = opportunity.id
        result["opportunity_created"] = created_opportunity

    db.add(
        AuditLog(
            installation_id=_installation_id(db),
            agent_id="ghl_webhook",
            user_id=None,
            event_type="ghl_webhook.inbound",
            provider="gohighlevel",
            model_name="deterministic",
            status="success",
            details=result,
        )
    )
    return result
