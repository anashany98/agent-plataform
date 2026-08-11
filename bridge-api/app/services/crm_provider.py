"""Proveedores CRM (Fase B, bloque 1).

Introduce el contrato ``CRMProvider`` con dos implementaciones:

- ``LocalCRMProvider`` — proveedor real **por defecto**: persiste leads y
  oportunidades en la BD local (tablas ``leads``/``opportunities``) sin
  red. Es el corazón del core sin GHL (PR-27): el chat captura el lead y
  el outbox lo entrega localmente con la misma semántica de checkpoint y
  reconciliación por ``external_reference`` que D-010.
- ``GHLAdapter`` (via ``active_crm_provider``) — cuando GHL está
  configurado se usa el adaptador existente, que satisface el mismo
  contrato.

``active_crm_provider`` decide cuál usar según ``CRM_PROVIDER`` (``auto``
= GHL si está configurado, si no local). El dispatcher de outbox y la
captura de oportunidad consumen siempre el proveedor activo.
"""

from __future__ import annotations

import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Lead, Opportunity

EXTERNAL_REFERENCE_KEY = "external_reference"


@runtime_checkable
class CRMProvider(Protocol):
    """Contrato de un proveedor CRM (GHL o local).

    Las firmas son las mismas que expone ``GHLAdapter`` para que el
    dispatcher de outbox y la captura de oportunidad funcionen contra
    cualquiera de los dos sin cambios.
    """

    def configured(self) -> bool: ...

    async def upsert_contact(
        self,
        *,
        email: str,
        first_name: str,
        phone: str | None = None,
        company_name: str | None = None,
    ) -> dict[str, Any]: ...

    async def create_opportunity(
        self,
        *,
        contact_id: str,
        name: str,
        monetary_value: float = 0.0,
        external_id: str,
    ) -> dict[str, Any]: ...

    async def add_note(self, contact_id: str, body: str) -> dict[str, Any]: ...

    async def find_opportunity_by_reference(
        self, *, contact_id: str, external_id: str
    ) -> dict[str, Any] | None: ...

    async def find_note_by_body(
        self, contact_id: str, body: str
    ) -> dict[str, Any] | None: ...


class LocalCRMProvider:
    """CRM local: persiste leads/oportunidades/notas en la BD (sin red).

    El lead (contacto) vive en ``leads`` con unicidad por email y por
    ``external_reference``; la oportunidad en ``opportunities`` con
    unicidad por ``external_reference`` (p. ej. el id del presupuesto),
    lo que hace la creación idempotente de la misma forma que la
    reconciliación D-010 de GHL: un replay nunca crea un efecto duplicado.

    Las notas se guardan en la columna ``notes`` JSON de la oportunidad
    más reciente del lead, con el mismo contrato ``find_note_by_body``
    que el adaptador GHL (cuerpo exacto) para que el checkpoint del
    outbox reutilice notas ya creadas tras un crash.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def configured(self) -> bool:
        return True

    @staticmethod
    def _lead_dict(lead: Lead) -> dict[str, Any]:
        return {
            "id": lead.id,
            "email": lead.email,
            "firstName": lead.first_name,
            "phone": lead.phone,
            "companyName": lead.company_name,
            "source": lead.source,
            "status": lead.status,
        }

    @staticmethod
    def _opportunity_dict(opportunity: Opportunity) -> dict[str, Any]:
        return {
            "id": opportunity.id,
            "name": opportunity.name,
            "monetaryValue": float(opportunity.monetary_value or 0),
            "contactId": opportunity.lead_id,
            "pipelineId": opportunity.pipeline,
            "pipelineStageId": opportunity.stage,
            "status": opportunity.status,
            "customFields": [
                {
                    "key": EXTERNAL_REFERENCE_KEY,
                    "field_value": opportunity.external_reference,
                }
            ],
        }

    async def upsert_contact(
        self,
        *,
        email: str,
        first_name: str,
        phone: str | None = None,
        company_name: str | None = None,
    ) -> dict[str, Any]:
        lead = (
            self._db.query(Lead)
            .filter(Lead.email == email.strip().lower())
            .order_by(Lead.created_at.asc())
            .first()
        )
        if lead is None:
            lead = Lead(
                email=email.strip().lower(),
                first_name=first_name,
                phone=phone,
                company_name=company_name,
                source="local",
                status="new",
            )
            self._db.add(lead)
        else:
            lead.first_name = first_name
            if phone is not None:
                lead.phone = phone
            if company_name is not None:
                lead.company_name = company_name
        self._db.flush()
        return self._lead_dict(lead)

    async def create_opportunity(
        self,
        *,
        contact_id: str,
        name: str,
        monetary_value: float = 0.0,
        external_id: str,
    ) -> dict[str, Any]:
        reference = str(external_id or "").strip()
        if not reference:
            raise ValueError("La oportunidad local exige una referencia externa")
        existing = (
            self._db.query(Opportunity)
            .filter(Opportunity.external_reference == reference)
            .first()
        )
        if existing is not None:
            return self._opportunity_dict(existing)
        opportunity = Opportunity(
            lead_id=contact_id,
            external_reference=reference,
            name=name,
            monetary_value=monetary_value,
            currency=settings.CURRENCY,
            pipeline="default",
            stage="new",
            status="open",
            notes=[],
        )
        self._db.add(opportunity)
        self._db.flush()
        return self._opportunity_dict(opportunity)

    async def add_note(self, contact_id: str, body: str) -> dict[str, Any]:
        target = self._latest_opportunity(contact_id)
        if target is None:
            raise ValueError(f"No hay oportunidad local para el lead {contact_id}")
        notes = list(target.notes or [])
        notes.append(
            {
                "body": body,
                "created_at": datetime.datetime.now(datetime.UTC)
                .replace(tzinfo=None)
                .isoformat(),
            }
        )
        target.notes = notes
        self._db.flush()
        return {"id": f"note-{target.id}-{len(notes)}", "body": body}

    async def find_opportunity_by_reference(
        self, *, contact_id: str, external_id: str
    ) -> dict[str, Any] | None:
        reference = str(external_id or "").strip()
        if not reference:
            return None
        opportunity = (
            self._db.query(Opportunity)
            .filter(
                Opportunity.external_reference == reference,
                Opportunity.lead_id == contact_id,
            )
            .first()
        )
        if opportunity is None:
            return None
        return self._opportunity_dict(opportunity)

    async def find_note_by_body(
        self, contact_id: str, body: str
    ) -> dict[str, Any] | None:
        target_body = str(body or "")
        if not target_body:
            return None
        for opportunity in self._lead_opportunities(contact_id):
            for note in opportunity.notes or []:
                if str(note.get("body") or "") == target_body:
                    return {"id": "note-existing", "body": target_body}
        return None

    def _lead_opportunities(self, contact_id: str) -> list[Opportunity]:
        return (
            self._db.query(Opportunity)
            .filter(Opportunity.lead_id == contact_id)
            .order_by(Opportunity.created_at.asc())
            .all()
        )

    def _latest_opportunity(self, contact_id: str) -> Opportunity | None:
        return (
            self._db.query(Opportunity)
            .filter(Opportunity.lead_id == contact_id)
            .order_by(Opportunity.created_at.desc())
            .first()
        )


def _ghl_is_configured() -> bool:
    try:
        from app.main import ghl_adapter

        return bool(ghl_adapter.configured())
    except Exception:
        return False


def active_crm_provider(db: Session) -> CRMProvider:
    """Devuelve el proveedor CRM activo según configuración.

    ``CRM_PROVIDER`` acepta ``auto`` (GHL si está configurado, si no
    local), ``local`` (fuerza LocalCRMProvider) o ``ghl`` (fuerza el
    adaptador GHL). Ante un valor inválido se cae a ``auto``.
    """

    choice = str(settings.CRM_PROVIDER or "auto").strip().lower()
    if choice == "local":
        return LocalCRMProvider(db)
    if choice == "ghl":
        from app.main import ghl_adapter

        return ghl_adapter
    if choice == "auto" and _ghl_is_configured():
        from app.main import ghl_adapter

        return ghl_adapter
    return LocalCRMProvider(db)
