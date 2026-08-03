"""Evals D-010: reconciliación GHL para cerrar la microventana efecto→checkpoint.

GHL no acepta claves de idempotencia en la creación de oportunidades ni de
notas. La garantía de "como mucho un efecto externo" se obtiene reconciliando
contra el proveedor antes de crear: si el efecto ya existe con la misma
referencia determinista se reutiliza en lugar de duplicarlo. Una búsqueda de
reconciliación fallida falla cerrada (nunca se crea a ciegas).

Hermetismo: el proveedor GHL se simula con un doble de estado (contactos,
oportunidades y notas en memoria) que se comporta como el proveedor real:
``create_opportunity`` duplicaría si se le llama dos veces. Los crashes se
inyectan con monkeypatches; ninguna prueba contacta servicios externos.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import (
    AuditLog,
    IdempotencyRecord,
    OutboxMessage,
    Product,
    utcnow,
)
from app.security import Principal, get_current_principal
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "test-installation"


class FakeGHLProvider:
    """Doble de estado del proveedor GHL.

    Reproducir el peligro real: ``create_opportunity`` y ``add_note`` añaden
    siempre una entidad nueva, exactamente igual que haría GHL si se invocan
    dos veces. La reconciliación del bridge es lo único que evita duplicados.
    """

    def __init__(self) -> None:
        self.contacts: dict[str, dict[str, Any]] = {}
        self.opportunities: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.create_calls = 0
        self.note_calls = 0
        self.opportunity_search_calls = 0
        self.note_search_calls = 0

    async def upsert_contact(self, *, email: str, first_name: str, phone=None, company_name=None) -> dict[str, Any]:
        existing = self.contacts.get(email)
        if existing is not None:
            return {"contact": existing}
        contact = {
            "id": f"ghl-contact-{len(self.contacts) + 1}",
            "email": email,
            "firstName": first_name,
            "phone": phone,
            "companyName": company_name,
        }
        self.contacts[email] = contact
        return {"contact": contact}

    async def create_opportunity(self, *, contact_id: str, name: str, monetary_value: float = 0.0, external_id: str) -> dict[str, Any]:
        self.create_calls += 1
        opportunity = {
            "id": f"ghl-opp-{self.create_calls}",
            "contactId": contact_id,
            "name": name,
            "monetaryValue": monetary_value,
            "customFields": [{"key": "external_reference", "field_value": external_id}],
        }
        self.opportunities.append(opportunity)
        return opportunity

    async def find_opportunity_by_reference(self, *, contact_id: str, external_id: str) -> dict[str, Any] | None:
        self.opportunity_search_calls += 1
        for opportunity in self.opportunities:
            if str(opportunity.get("contactId") or "") != str(contact_id):
                continue
            for field in opportunity.get("customFields") or []:
                if field.get("key") == "external_reference" and str(field.get("field_value") or "") == str(external_id):
                    return opportunity
        return None

    async def add_note(self, contact_id: str, body: str) -> dict[str, Any]:
        self.note_calls += 1
        note = {"id": f"ghl-note-{self.note_calls}", "contactId": contact_id, "body": body}
        self.notes.append(note)
        return note

    async def find_note_by_body(self, contact_id: str, body: str) -> dict[str, Any] | None:
        self.note_search_calls += 1
        for note in self.notes:
            if str(note.get("contactId") or "") == str(contact_id) and note.get("body") == body:
                return note
        return None


@dataclass
class IsolatedApi:
    client: TestClient
    engine: Engine
    session_factory: sessionmaker


@pytest.fixture
def isolated_api() -> IsolatedApi:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def isolated_db():
        with installation_scope(INSTALLATION_ID):
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

    principal = Principal(
        user_id="ghl-reconciliation-admin",
        username="ghl-reconciliation-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="ghl-reconciliation-jti",
    )
    previous_db_override = app.dependency_overrides.get(get_db)
    previous_principal_override = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_principal] = lambda: principal
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield IsolatedApi(client=client, engine=engine, session_factory=session_factory)
    finally:
        client.close()
        if previous_db_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_db_override
        if previous_principal_override is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = previous_principal_override
        engine.dispose()


@contextmanager
def _isolated_session(api: IsolatedApi):
    with installation_scope(INSTALLATION_ID):
        db = api.session_factory()
        try:
            yield db
        finally:
            db.close()


def _seed_product(api: IsolatedApi) -> None:
    with _isolated_session(api) as db:
        db.add(
            Product(
                id="prod-ghl-reconciliation",
                external_id="prod-ghl-reconciliation",
                sku="SKU-GHL-0001",
                name="Caudalimetro Reconciliacion",
                description="Fixture sintético para pruebas de reconciliación GHL.",
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("75.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=30,
                reserved_stock=0,
            )
        )
        db.commit()


def _signed_chatwoot_request(client: TestClient, payload: dict[str, Any]):
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(dt.datetime.now(dt.UTC).timestamp()))
    signature = hmac.new(
        bridge_main.settings.CHATWOOT_WEBHOOK_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/chatwoot",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )


def _webhook_payload(suffix: str, email: str) -> dict[str, Any]:
    return {
        "event": "message_created",
        "id": f"ghl-rec-{suffix}",
        "message_type": "incoming",
        "content": "Necesito 1 unidad de caudalimetro reconciliacion",
        "private": False,
        "account": {"id": 8181},
        "conversation": {"id": 9191},
        "sender": {"id": 13, "name": "Lead Reconciliacion", "email": email},
    }


def _install_provider(monkeypatch: pytest.MonkeyPatch) -> FakeGHLProvider:
    """Conecta el doble de estado al adapter del bridge y lo configura."""

    provider = FakeGHLProvider()
    monkeypatch.setattr(bridge_main.ghl_adapter, "token", "fault-injection-token")
    monkeypatch.setattr(bridge_main.ghl_adapter, "location_id", "fault-injection-location")
    for method in ("upsert_contact", "create_opportunity", "find_opportunity_by_reference", "add_note", "find_note_by_body"):
        monkeypatch.setattr(bridge_main.ghl_adapter, method, getattr(provider, method))
    return provider


def _force_due(api: IsolatedApi, outbox_id: str) -> None:
    with _isolated_session(api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        message.next_attempt_at = utcnow() - dt.timedelta(seconds=5)
        db.commit()


def test_opportunity_micro_window_closes_via_reconciliation(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash entre ``create_opportunity`` y su checkpoint.

    El efecto externo llega al proveedor pero el checkpoint no se persiste.
    El reintento no tiene la oportunidad checkpointada y debe reconciliar:
    encontrar la oportunidad existente por referencia externa y reutilizarla
    en lugar de crear un duplicado.
    """

    _seed_product(isolated_api)

    async def silent_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", silent_chatwoot)
    provider = _install_provider(monkeypatch)

    real_commit_checkpoint = bridge_main._commit_ghl_checkpoint

    def crash_on_opportunity_checkpoint(message, payload, checkpoint):
        if "opportunity" in checkpoint:
            raise RuntimeError("crash inyectado entre el efecto y el checkpoint")
        return real_commit_checkpoint(message, payload, checkpoint)

    monkeypatch.setattr(bridge_main, "_commit_ghl_checkpoint", crash_on_opportunity_checkpoint)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-rec-{suffix[:10]}@example.com")
    response = _signed_chatwoot_request(isolated_api.client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["lead"]["status"] == "queued_for_retry"
    outbox_id = response.json()["lead"]["outbox_id"]
    assert provider.create_calls == 1, "El primer intento creó la oportunidad en el proveedor"

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        checkpoint = (message.payload or {}).get("checkpoint") or {}
        assert "opportunity" not in checkpoint, (
            "El crash inyectado impidió persistir el checkpoint de la oportunidad"
        )

    monkeypatch.setattr(bridge_main, "_commit_ghl_checkpoint", real_commit_checkpoint)
    _force_due(isolated_api, outbox_id)

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200, response.text
    assert response.json()["sent"] == 1

    assert provider.create_calls == 1, (
        "La reconciliación debe reutilizar la oportunidad existente: crear de nuevo "
        "la duplicaría en el proveedor"
    )
    assert provider.opportunity_search_calls >= 1
    assert provider.note_calls == 1, "La nota sí es nueva y debe enviarse una vez"

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        assert message.state == "sent"
        checkpoint = (message.payload or {}).get("checkpoint") or {}
        assert checkpoint.get("opportunity", {}).get("id") == "ghl-opp-1"
        assert "opportunity" in (checkpoint.get("reconciled") or [])
        assert (message.response_body or {}).get("reconciled") == ["opportunity"]
        reconciled_audits = db.query(AuditLog).filter(
            AuditLog.event_type == "ghl_lead_reconciled"
        ).all()
        assert any(
            (row.details or {}).get("outbox_id") == outbox_id
            and "opportunity" in ((row.details or {}).get("reconciled") or [])
            for row in reconciled_audits
        ), "La reconciliación debe quedar auditada"


def test_note_micro_window_closes_via_reconciliation(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash entre ``add_note`` y su checkpoint: la nota no se duplica."""

    _seed_product(isolated_api)

    async def silent_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", silent_chatwoot)
    provider = _install_provider(monkeypatch)

    real_commit_checkpoint = bridge_main._commit_ghl_checkpoint

    def crash_on_note_checkpoint(message, payload, checkpoint):
        if checkpoint.get("note_completed"):
            raise RuntimeError("crash inyectado entre la nota y el checkpoint")
        return real_commit_checkpoint(message, payload, checkpoint)

    monkeypatch.setattr(bridge_main, "_commit_ghl_checkpoint", crash_on_note_checkpoint)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-note-{suffix[:10]}@example.com")
    response = _signed_chatwoot_request(isolated_api.client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["lead"]["status"] == "queued_for_retry"
    outbox_id = response.json()["lead"]["outbox_id"]
    assert provider.note_calls == 1, "La nota llegó al proveedor en el primer intento"

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        checkpoint = (message.payload or {}).get("checkpoint") or {}
        assert not checkpoint.get("note_completed")

    monkeypatch.setattr(bridge_main, "_commit_ghl_checkpoint", real_commit_checkpoint)
    _force_due(isolated_api, outbox_id)

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200, response.text
    assert response.json()["sent"] == 1

    assert provider.note_calls == 1, (
        "La nota ya existente debe reconciliarse, nunca reenviarse"
    )
    assert provider.create_calls == 1, "La oportunidad checkpointada no se toca"

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        assert message.state == "sent"
        assert (message.response_body or {}).get("reconciled") == ["note"]


def test_direct_endpoint_crash_recovers_via_reconciliation(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash en ``/integrations/ghl/leads`` tras crear la oportunidad.

    El takeover posterior (lease caducado) debe reconciliar contra el
    proveedor y completar sin duplicar la oportunidad.
    """

    provider = _install_provider(monkeypatch)
    real_checkpoint = bridge_main._checkpoint_idempotency

    def crash_on_opportunity_checkpoint(db, key, owner_id, response):
        if "opportunity" in (response or {}):
            raise RuntimeError("crash inyectado tras crear la oportunidad")
        return real_checkpoint(db, key, owner_id, response)

    monkeypatch.setattr(bridge_main, "_checkpoint_idempotency", crash_on_opportunity_checkpoint)

    external_id = f"ghl-rec-{uuid.uuid4().hex}"
    payload = {
        "email": f"endpoint-{uuid.uuid4().hex[:10]}@example.com",
        "first_name": "Endpoint",
        "opportunity_name": "Reconciliación directa",
        "monetary_value": 120,
        "external_id": external_id,
        "note": "Nota del endpoint",
    }

    first = isolated_api.client.post("/integrations/ghl/leads", json=payload)
    assert first.status_code == 500, (
        "El crash tras el efecto debe surfaced como error, no como éxito falso"
    )
    assert provider.create_calls == 1

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == f"ghl-lead:{external_id}"
        ).one()
        # Reconstrucción del crash duro: lease caducado y checkpoint sin oportunidad.
        record.state = "failed"
        record.status_code = 500
        record.owner_id = None
        record.lease_expires_at = None
        record.response_body = {"status": "processing", "contact_id": list(provider.contacts.values())[0]["id"]}
        db.commit()

    monkeypatch.setattr(bridge_main, "_checkpoint_idempotency", real_checkpoint)

    second = isolated_api.client.post("/integrations/ghl/leads", json=payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "success"
    assert body["opportunity"]["id"] == "ghl-opp-1"
    assert body["reconciled"] == ["opportunity"]
    assert provider.create_calls == 1, (
        "El takeover debe reconciliar la oportunidad existente, no duplicarla"
    )
    assert provider.note_calls == 1

    third = isolated_api.client.post("/integrations/ghl/leads", json=payload)
    assert third.status_code == 200
    assert third.json()["status"] == "duplicate_ignored"
    assert provider.create_calls == 1


def test_reconciliation_failure_fails_closed_without_creating(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la búsqueda de reconciliación falla, nunca se crea a ciegas."""

    _seed_product(isolated_api)

    async def silent_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", silent_chatwoot)
    provider = _install_provider(monkeypatch)

    async def search_down(**_kwargs: Any) -> dict[str, Any]:
        raise GHLIntegrationError("avería inyectada en la búsqueda de reconciliación")

    monkeypatch.setattr(bridge_main.ghl_adapter, "find_opportunity_by_reference", search_down)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-closed-{suffix[:10]}@example.com")
    response = _signed_chatwoot_request(isolated_api.client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["lead"]["status"] == "queued_for_retry"
    outbox_id = response.json()["lead"]["outbox_id"]

    assert provider.create_calls == 0, (
        "Sin reconciliación verificable no se puede crear: fail-closed"
    )
    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        assert message.state == "pending"
        assert message.attempt_count == 1


def test_missing_external_reference_is_permanent(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un lead sin referencia externa no puede reconciliarse: DLQ directa."""

    provider = _install_provider(monkeypatch)
    with _isolated_session(isolated_api) as db:
        outbox = bridge_main.OutboxService(db)
        message, _created = outbox.enqueue(
            topic=bridge_main.GHL_LEAD_OUTBOX_TOPIC,
            idempotency_key=f"ghl-lead:sin-referencia-{uuid.uuid4().hex}",
            payload={
                "email": "sin-referencia@example.com",
                "first_name": "Sin Referencia",
                "opportunity_name": "Sin referencia externa",
                "monetary_value": 10.0,
                "external_id": "",
                "note": None,
            },
        )
        asyncio.run(outbox.deliver(message, bridge_main._dispatch_ghl_lead_capture))
        assert message.state == "dead", (
            "Sin referencia externa la reconciliación es imposible y el mensaje no "
            "puede quedarse reintentando para siempre"
        )
        assert (message.last_error or {}).get("permanent") is True
    assert provider.create_calls == 0


def test_adapter_search_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contratos del adaptador: coincidencia exacta y paginación acotada."""

    adapter = GHLAdapter()
    adapter.base_url = "https://provider.invalid"
    adapter.token = "fault-injection-token"
    adapter.location_id = "fault-injection-location"

    pages = {
        "opportunities": [
            [
                {
                    "id": "opp-otra-cuenta",
                    "contactId": "contacto-1",
                    "customFields": [{"key": "external_reference", "field_value": "ref-1"}],
                },
                {
                    "id": "opp-buscada",
                    "contactId": "contacto-1",
                    "customFields": [{"key": "external_reference", "field_value": "ref-buscada"}],
                },
            ],
        ],
        "notes": [
            [
                {"id": "note-1", "body": "otra nota"},
                {"id": "note-2", "body": "nota buscada"},
            ],
        ],
    }

    async def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        assert method == "GET"
        if path.startswith("/opportunities/search"):
            return {"opportunities": pages["opportunities"][0]}
        if "/notes" in path:
            return {"notes": pages["notes"][0]}
        raise AssertionError(f"Ruta inesperada en reconciliación: {path}")

    monkeypatch.setattr(adapter, "_request", fake_request)

    found = asyncio.run(
        adapter.find_opportunity_by_reference(contact_id="contacto-1", external_id="ref-buscada")
    )
    assert found is not None and found["id"] == "opp-buscada"

    missing = asyncio.run(
        adapter.find_opportunity_by_reference(contact_id="contacto-1", external_id="ref-inexistente")
    )
    assert missing is None

    other_contact = asyncio.run(
        adapter.find_opportunity_by_reference(contact_id="contacto-2", external_id="ref-1")
    )
    assert other_contact is None, "La referencia de otro contacto no debe coincidir"

    with pytest.raises(GHLIntegrationError):
        asyncio.run(adapter.find_opportunity_by_reference(contact_id="contacto-1", external_id=""))

    note = asyncio.run(adapter.find_note_by_body("contacto-1", "nota buscada"))
    assert note is not None and note["id"] == "note-2"
    assert asyncio.run(adapter.find_note_by_body("contacto-1", "no existe")) is None


