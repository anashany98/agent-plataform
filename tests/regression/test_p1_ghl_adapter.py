"""Evals T-083: adaptador GoHighLevel de entrada y salida.

Cubre:

- Entrada: ``POST /webhooks/gohighlevel`` — firma ``X-Hub-Signature-256``
  (fail-closed), eventos ``ContactCreate``/``OpportunityCreate`` que alimentan
  el CRM local (leads/oportunidades idempotentes por referencia externa) y
  eventos desconocidos ignorados de forma auditable. Anti-replay: un replay
  del mismo evento devuelve la respuesta cacheada sin repetir el efecto.
- Salida: el CEO agent propone (deny-by-default) enviar un SMS/email a un
  lead y dar de alta un contacto en GHL; al aprobarse (humano o autonomía
  autorizada) el efecto se encola en el outbox durable y el dispatcher lo
  entrega con el patrón D-010 (upsert del contacto + checkpoint). Sin GHL
  configurado el envío cae a la DLQ, nunca se pierde.

Hermeticidad D-032: el proveedor GHL se simula con un doble de estado y el
adaptador nunca toca la red; la firma se calcula con el secreto de test del
conftest.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from app import main as bridge_main
from app.database import SessionLocal
from app.models.models import (
    AgentAutonomy,
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    Lead,
    Opportunity,
    OutboxMessage,
)
from app.services.agent_proposals import (
    GHL_CREATE_CONTACT_TOPIC,
    GHL_SEND_MESSAGE_ACTION,
    GHL_SEND_MESSAGE_TOPIC,
)
from app.services.outbox import OutboxPermanentError, OutboxService

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _seed_lead(
    db,
    *,
    first_name: str = "Lead GHL",
    status: str = "new",
    external_reference: str | None = None,
) -> Lead:
    lead = Lead(
        id=_unique("ghl-lead"),
        email=f"{_unique('ghl-lead')}@example.invalid",
        first_name=first_name,
        phone="+34600000000",
        company_name="Empresa GHL",
        source="local",
        status=status,
        external_reference=external_reference,
    )
    db.add(lead)
    db.flush()
    return lead


def _cleanup(ids: dict[str, list[str]]) -> None:
    db = SessionLocal()
    try:
        if ids.get("outbox"):
            db.query(OutboxMessage).filter(OutboxMessage.id.in_(ids["outbox"])).delete()
        if ids.get("decisions"):
            db.query(AgentDecision).filter(AgentDecision.id.in_(ids["decisions"])).delete()
        if ids.get("approvals"):
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(ids["approvals"])).delete()
        if ids.get("opportunities"):
            db.query(Opportunity).filter(Opportunity.id.in_(ids["opportunities"])).delete()
        if ids.get("leads"):
            db.query(Lead).filter(Lead.id.in_(ids["leads"])).delete()
        if ids.get("autonomies"):
            db.query(AgentAutonomy).filter(AgentAutonomy.id.in_(ids["autonomies"])).delete()
        db.commit()
    finally:
        db.close()


def _signed_ghl_request(client, payload: dict[str, Any]):
    """POST firmado con la convención X-Hub-Signature-256 de GHL."""

    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    signature = hmac.new(
        bridge_main.settings.GHL_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/gohighlevel",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={signature}",
        },
    )


def _contact_create_payload(email: str, contact_id: str) -> dict[str, Any]:
    return {
        "type": "ContactCreate",
        "locationId": "loc-test",
        "id": contact_id,
        "data": {
            "id": contact_id,
            "locationId": "loc-test",
            "contactName": "Ana García",
            "firstName": "Ana",
            "lastName": "García",
            "email": email,
            "phone": "+34611111111",
            "companyName": "Acme SL",
        },
        "dateAdded": "2026-08-19T10:00:00.000Z",
    }


class FakeGHLProvider:
    """Doble de estado del proveedor GHL (upsert + mensajes)."""

    def __init__(self) -> None:
        self.contacts: dict[str, dict[str, Any]] = {}
        self.sms_sent: list[dict[str, Any]] = []
        self.emails_sent: list[dict[str, Any]] = []

    async def upsert_contact(self, *, email, first_name, phone=None, company_name=None):
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

    async def send_sms(self, *, contact_id: str, content: str) -> dict[str, Any]:
        self.sms_sent.append({"contactId": contact_id, "content": content})
        return {"id": f"ghl-sms-{len(self.sms_sent)}", "status": "sent"}

    async def send_email(self, *, contact_id: str, subject: str, content: str, html=None) -> dict[str, Any]:
        self.emails_sent.append(
            {"contactId": contact_id, "subject": subject, "content": content}
        )
        return {"id": f"ghl-email-{len(self.emails_sent)}", "status": "sent"}


def _install_provider(monkeypatch: pytest.MonkeyPatch) -> FakeGHLProvider:
    provider = FakeGHLProvider()
    monkeypatch.setattr(bridge_main.ghl_adapter, "base_url", "https://ghl-fake.invalid")
    monkeypatch.setattr(bridge_main.ghl_adapter, "token", "fault-injection-token")
    monkeypatch.setattr(bridge_main.ghl_adapter, "location_id", "fault-injection-location")
    for method in ("upsert_contact", "send_sms", "send_email"):
        monkeypatch.setattr(bridge_main.ghl_adapter, method, getattr(provider, method))
    return provider


def _ceo_chat(client, token, message: str, conversation_id: str | None = None):
    return client.post(
        "/ceo/chat",
        json={
            "message": message,
            "conversation_id": conversation_id or _unique("ghl-conv"),
        },
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Entrada: firma y eventos de GHL
# ---------------------------------------------------------------------------


def test_ghl_webhook_requires_valid_signature(client) -> None:
    payload = _contact_create_payload(
        f"{_unique('ghl-sig')}@example.invalid", _unique("ghl-contact")
    )
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    missing = client.post(
        "/webhooks/gohighlevel",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert missing.status_code == 401

    wrong = client.post(
        "/webhooks/gohighlevel",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )
    assert wrong.status_code == 401

    ok = _signed_ghl_request(client, payload)
    assert ok.status_code == 200, ok.text


def test_ghl_contact_create_webhook_creates_lead_and_is_idempotent(client) -> None:
    ids: dict[str, list[str]] = {"leads": []}
    email = f"{_unique('ghl-inbound')}@example.invalid"
    contact_id = _unique("ghl-contact")
    payload = _contact_create_payload(email, contact_id)

    first = _signed_ghl_request(client, payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "applied"
    assert body["lead_created"] is True
    ids["leads"].append(body["lead_id"])

    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == body["lead_id"]).first()
        assert lead is not None
        assert lead.email == email
        assert lead.source == "ghl"
        assert lead.external_reference == contact_id
        assert lead.first_name == "Ana García"

        replay = _signed_ghl_request(client, payload)
        assert replay.status_code == 200
        assert replay.json() == body  # respuesta cacheada (anti-replay)

        count = (
            db.query(Lead)
            .filter(Lead.external_reference == contact_id)
            .count()
        )
        assert count == 1  # el replay no duplicó el efecto
    finally:
        db.close()
    _cleanup(ids)


def test_ghl_opportunity_create_webhook_creates_opportunity(client) -> None:
    ids: dict[str, list[str]] = {"leads": [], "opportunities": []}
    contact_id = _unique("ghl-contact")
    opportunity_id = _unique("ghl-opp")
    db = SessionLocal()
    try:
        lead = _seed_lead(db, external_reference=contact_id)
        lead_id = lead.id
        ids["leads"].append(lead_id)
        db.commit()
    finally:
        db.close()

    payload = {
        "type": "OpportunityCreate",
        "locationId": "loc-test",
        "id": opportunity_id,
        "data": {
            "id": opportunity_id,
            "name": "Trato Acme 5000",
            "contactId": contact_id,
            "pipelineId": "pipe-test",
            "pipelineStageId": "new",
            "status": "open",
            "monetaryValue": 5000.0,
        },
        "dateAdded": "2026-08-19T11:00:00.000Z",
    }
    response = _signed_ghl_request(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "applied"
    assert body["opportunity_created"] is True
    ids["opportunities"].append(body["opportunity_id"])

    db = SessionLocal()
    try:
        opportunity = (
            db.query(Opportunity)
            .filter(Opportunity.id == body["opportunity_id"])
            .first()
        )
        assert opportunity is not None
        assert opportunity.external_reference == opportunity_id
        assert opportunity.lead_id == lead_id
        assert float(opportunity.monetary_value) == 5000.0
        assert opportunity.name == "Trato Acme 5000"
    finally:
        db.close()
    _cleanup(ids)


def test_ghl_webhook_unknown_event_ignored(client) -> None:
    payload = {"type": "FunnelCreated", "locationId": "loc-test", "id": "funnel-1"}
    response = _signed_ghl_request(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ignored"

    db = SessionLocal()
    try:
        assert (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "ghl_webhook.ignored")
            .count()
            >= 1
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Salida: propuestas del CEO (deny-by-default) + outbox durable
# ---------------------------------------------------------------------------


def test_ceo_chat_proposes_ghl_send_sms(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"leads": [], "approvals": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Ana García")
        lead_id = lead.id
        lead_email = lead.email
        ids["leads"].append(lead_id)
        db.commit()
    finally:
        db.close()
    try:
        token = auth_headers["Authorization"].split()[-1]
        response = _ceo_chat(
            client,
            token,
            f"envía un sms a {lead_email} que diga: tu pedido está listo",
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "ghl_send_message"
        assert len(data["proposals"]) == 1
        assert data["proposals"][0]["status"] == "pending"
        assert "propuesta" in data["answer"].lower()

        proposal_id = data["proposals"][0]["id"]
        ids["approvals"].append(proposal_id)
        db = SessionLocal()
        try:
            proposal = db.query(ApprovalRequest).filter(ApprovalRequest.id == proposal_id).first()
            assert proposal is not None
            assert proposal.action_type == "agent_proposal:ghl_send_message"
            assert proposal.status == "pending"
            assert proposal.payload["channel"] == "sms"
            assert proposal.payload["email"] == lead_email
            # El texto se conserva con acentos (extraído del mensaje original).
            assert proposal.payload["content"] == "tu pedido está listo"
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_send_missing_content_asks_for_text(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"leads": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db)
        lead_email = lead.email
        ids["leads"].append(lead.id)
        db.commit()
    finally:
        db.close()
    try:
        token = auth_headers["Authorization"].split()[-1]
        response = _ceo_chat(client, token, f"envía un sms a {lead_email}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "ghl_send_message"
        assert data["proposals"] == []
        assert "dime el texto" in data["answer"].lower()
    finally:
        _cleanup(ids)


def test_approving_ghl_send_proposal_enqueues_and_delivers(
    client, auth_headers, monkeypatch
) -> None:
    ids: dict[str, list[str]] = {"leads": [], "approvals": [], "outbox": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db)
        lead_email = lead.email
        ids["leads"].append(lead.id)
        db.commit()
    finally:
        db.close()
    provider = _install_provider(monkeypatch)
    token = auth_headers["Authorization"].split()[-1]
    try:
        chat = _ceo_chat(client, token, f"envía un sms a {lead_email} que diga: hola")
        assert chat.status_code == 200, chat.text
        proposal_id = chat.json()["proposals"][0]["id"]
        ids["approvals"].append(proposal_id)

        approved = client.post(
            f"/approvals/{proposal_id}/approve",
            json={},
            headers=auth_headers,
        )
        assert approved.status_code == 200, approved.text
        applied = approved.json()["applied"]
        assert applied["queued"] is True
        ids["outbox"].append(applied["outbox_id"])

        db = SessionLocal()
        try:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == applied["outbox_id"]).first()
            assert message is not None
            assert message.topic == GHL_SEND_MESSAGE_TOPIC
            assert message.state == "pending"

            result = _run(bridge_main._dispatch_ghl_send_message(message))
            db.commit()
            assert result["status"] == "success"
            assert result["channel"] == "sms"
            assert provider.sms_sent == [
                {"contactId": result["contact_id"], "content": "hola"}
            ]
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ghl_send_autonomy_auto_executes(client, auth_headers, monkeypatch) -> None:
    ids: dict[str, list[str]] = {"leads": [], "approvals": [], "outbox": [], "decisions": [], "autonomies": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db)
        lead_email = lead.email
        ids["leads"].append(lead.id)
        # Upsert (get-or-create) para no chocar con la fila de ``ceo_agent``
        # que crean otros tests del mismo proceso (uq por instalación+agente).
        autonomy = (
            db.query(AgentAutonomy)
            .filter(
                AgentAutonomy.installation_id == "test-installation",
                AgentAutonomy.agent_id == "ceo_agent",
            )
            .first()
        )
        if autonomy is None:
            autonomy = AgentAutonomy(
                installation_id="test-installation",
                agent_id="ceo_agent",
            )
            db.add(autonomy)
        autonomy.mode = "autonomous"
        autonomy.max_value_threshold = 0.0
        autonomy.allowed_actions = [GHL_SEND_MESSAGE_ACTION]
        autonomy.max_actions_per_day = 10
        db.flush()
        ids["autonomies"].append(autonomy.id)
        db.commit()
    finally:
        db.close()
    _install_provider(monkeypatch)
    token = auth_headers["Authorization"].split()[-1]
    try:
        response = _ceo_chat(
            client,
            token,
            f"envía un email a {lead_email} que diga: oferta especial",
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "ghl_send_message"
        assert len(data["proposals"]) == 1
        assert data["proposals"][0]["status"] == "approved"
        assert "autonomía" in data["answer"].lower()

        db = SessionLocal()
        try:
            decision = (
                db.query(AgentDecision)
                .filter(
                    AgentDecision.agent_id == "ceo_agent",
                    AgentDecision.action_type == "agent_proposal:ghl_send_message",
                )
                .order_by(AgentDecision.executed_at.desc())
                .first()
            )
            assert decision is not None
            ids["decisions"].append(decision.id)
            applied = (decision.payload or {}).get("applied") or {}
            assert applied["queued"] is True
            ids["outbox"].append(applied["outbox_id"])
            message = db.query(OutboxMessage).filter(OutboxMessage.id == applied["outbox_id"]).first()
            assert message is not None
            assert message.topic == GHL_SEND_MESSAGE_TOPIC
            assert message.payload["channel"] == "email"
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_proposes_ghl_create_contact_and_enqueues(
    client, auth_headers, monkeypatch
) -> None:
    ids: dict[str, list[str]] = {"approvals": [], "outbox": []}
    email = f"{_unique('ghl-contact')}@example.invalid"
    provider = _install_provider(monkeypatch)
    token = auth_headers["Authorization"].split()[-1]
    try:
        response = _ceo_chat(client, token, f"crea un contacto en GHL para Ana García {email}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "ghl_create_contact"
        assert len(data["proposals"]) == 1
        proposal_id = data["proposals"][0]["id"]
        ids["approvals"].append(proposal_id)

        approved = client.post(f"/approvals/{proposal_id}/approve", json={}, headers=auth_headers)
        assert approved.status_code == 200, approved.text
        applied = approved.json()["applied"]
        assert applied["queued"] is True
        ids["outbox"].append(applied["outbox_id"])

        db = SessionLocal()
        try:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == applied["outbox_id"]).first()
            assert message is not None
            assert message.topic == GHL_CREATE_CONTACT_TOPIC

            result = _run(bridge_main._dispatch_ghl_create_contact(message))
            db.commit()
            assert result["status"] == "success"
            assert email in provider.contacts
            assert provider.contacts[email]["firstName"] == "Ana García"
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ghl_send_dispatcher_without_config_dead_letters() -> None:
    db = SessionLocal()
    try:
        outbox = OutboxService(db)
        message, created = outbox.enqueue(
            topic=GHL_SEND_MESSAGE_TOPIC,
            idempotency_key=f"ghl-send-dlq:{uuid.uuid4().hex[:8]}",
            payload={
                "lead_id": "lead-dlq",
                "lead_name": "Lead DLQ",
                "email": "dlq@example.invalid",
                "phone": None,
                "channel": "sms",
                "content": "mensaje sin GHL",
            },
        )
        assert created
        # El conftest deja GHL sin configurar: el dispatch debe fallar de
        # forma permanente (DLQ) y NUNCA intentar red.
        with pytest.raises(OutboxPermanentError):
            _run(bridge_main._dispatch_ghl_send_message(message))
        db.commit()
        assert message.state == "pending"
    finally:
        db.close()
        # limpiar el mensaje de prueba
        db = SessionLocal()
        try:
            db.query(OutboxMessage).filter(OutboxMessage.id == message.id).delete()
            db.commit()
        finally:
            db.close()
