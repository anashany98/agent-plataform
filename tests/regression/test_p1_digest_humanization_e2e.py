"""E2E del humanizado del digest en una sola pasada: API + email.

Una decisión auto-ejecutada sobre un lead real y una propuesta pendiente de
factura (cliente + borrador reales) recorren el mismo contrato en una única
ejecución:

- ``GET /agents/digest`` (supervisión técnica) entrega ``target_label`` /
  ``target_kind`` / ``target_focus_id`` humanos para la decisión del lead.
- ``POST /digest/send?dry_run=true`` construye el email con el lead y la
  factura por sus nombres humanos, la pista de módulo («(en Clientes)» /
  «(en Ventas)») y **ninguna** clave técnica (UUID ni ``inv-…``), y su JSON
  expone el mismo contrato.

La pierna de portal (la tabla del digest en «Agentes de IA» renderizando
esos campos como enlaces) se valida en ``productionModules.test.tsx`` con el
mismo fixture (``target_kind: lead/invoice`` → ``href`` ``#clientes`` /
``#ventas``). Hermeticidad D-032: SQLite de test, spool local, limpieza en
``finally`` y dueño inyectado con ``monkeypatch``.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from app.config import settings
from app.database import SessionLocal
from app.models.models import (
    Activity,
    AgentDecision,
    ApprovalRequest,
    Customer,
    InvoiceDraft,
    Lead,
    ScheduledTask,
)

OWNER_EMAIL = "dueno-e2e@miempresa.com"
CEO_FOLLOW_UP_ACTION = "agent_proposal:create_follow_up"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _seed_lead(db, *, first_name: str = "María E2E") -> Lead:
    lead = Lead(
        id=_unique("e2e-lead"),
        email=f"{_unique('e2e-lead')}@example.invalid",
        first_name=first_name,
        status="new",
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_invoice(db) -> tuple[Customer, InvoiceDraft]:
    customer = Customer(
        id=_unique("e2e-cust"),
        name="Acme E2E",
        email=f"{_unique('e2e-cust')}@example.invalid",
    )
    db.add(customer)
    db.flush()
    invoice = InvoiceDraft(
        id=f"inv-{uuid.uuid4().hex[:10]}",
        invoice_number=f"INV-2026-E2E-{uuid.uuid4().hex[:6].upper()}",
        order_id=_unique("e2e-order"),
        customer_id=str(customer.id),
        items=[{"sku": "SKU-E2E", "quantity": 1}],
        total_amount=Decimal("121.00"),
        tax_amount=Decimal("21.00"),
        currency="EUR",
        status="draft",
    )
    db.add(invoice)
    db.flush()
    return customer, invoice


def _seed_activity(db, *, lead_id: str) -> Activity:
    activity = Activity(
        id=_unique("e2e-act"),
        lead_id=lead_id,
        title="Follow-up del agente CRM (E2E)",
        kind="follow_up",
        description="Generada por el agente de forma autónoma",
        due_at=_now() + datetime.timedelta(hours=24),
        status="pending",
        created_by="crm_agent",
    )
    db.add(activity)
    db.flush()
    return activity


def _seed_decision(db, *, target_key: str, activity_id: str) -> AgentDecision:
    decision = AgentDecision(
        id=_unique("e2e-dec"),
        agent_id="crm_agent",
        action_type=CEO_FOLLOW_UP_ACTION,
        target_key=target_key,
        executed_at=_now() - datetime.timedelta(hours=3),
        executed_by="crm_agent",
        payload={
            "summary": "Follow-up automático sobre un lead frío (E2E)",
            "applied": {"activity_id": activity_id},
        },
        deviation=False,
    )
    db.add(decision)
    db.flush()
    return decision


def _seed_invoice_proposal(db, *, invoice: InvoiceDraft) -> ApprovalRequest:
    proposal = ApprovalRequest(
        id=_unique("e2e-appr"),
        action_type="issue_invoice",
        target_key=str(invoice.id),
        payload={"rationale": "Factura pendiente de aprobación (E2E)"},
        requested_by="finance_agent",
        status="pending",
        # La más antigua: el digest muestra las 8 primeras por antigüedad y
        # el corpus deja propuestas pendientes de otros tests.
        created_at=_now() - datetime.timedelta(days=30),
    )
    db.add(proposal)
    db.flush()
    return proposal


def _cleanup(
    *,
    decision_ids: list[str],
    activity_ids: list[str],
    proposal_ids: list[str],
    lead_ids: list[str],
    invoice_ids: list[str],
    customer_ids: list[str],
) -> None:
    db = SessionLocal()
    try:
        if decision_ids:
            db.query(AgentDecision).filter(AgentDecision.id.in_(decision_ids)).delete()
        if activity_ids:
            db.query(Activity).filter(Activity.id.in_(activity_ids)).delete()
        if proposal_ids:
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(proposal_ids)).delete()
        if invoice_ids:
            db.query(InvoiceDraft).filter(InvoiceDraft.id.in_(invoice_ids)).delete()
        if customer_ids:
            db.query(Customer).filter(Customer.id.in_(customer_ids)).delete()
        if lead_ids:
            db.query(Lead).filter(Lead.id.in_(lead_ids)).delete()
        db.query(ScheduledTask).filter(ScheduledTask.task_type == "daily_digest").delete()
        db.commit()
    finally:
        db.close()


def test_digest_humanization_e2e_single_pass(client, auth_headers, monkeypatch) -> None:
    """Siembra lead + factura, y valida el humanizado en API y email de una vez."""
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    lead_ids: list[str] = []
    invoice_ids: list[str] = []
    customer_ids: list[str] = []
    try:
        lead = _seed_lead(db)
        lead_id = str(lead.id)
        lead_ids.append(lead_id)
        customer, invoice = _seed_invoice(db)
        customer_ids.append(str(customer.id))
        invoice_id = str(invoice.id)
        invoice_number = str(invoice.invoice_number)
        invoice_ids.append(invoice_id)
        activity = _seed_activity(db, lead_id=lead_id)
        activity_ids.append(str(activity.id))
        decision = _seed_decision(db, target_key=lead_id, activity_id=str(activity.id))
        decision_id = str(decision.id)
        decision_ids.append(decision_id)
        proposal = _seed_invoice_proposal(db, invoice=invoice)
        proposal_id = str(proposal.id)
        proposal_ids.append(proposal_id)
        db.commit()
    finally:
        db.close()

    try:
        # 1) API: supervisión técnica (/agents/digest) — la decisión del
        #    lead llega humanizada, con su tipo y el id enfocable.
        digest = client.get("/agents/digest?days=7", headers=auth_headers)
        assert digest.status_code == 200, digest.text
        decision_row = next(
            d
            for d in digest.json()["decisions"]
            if d["id"] == decision_id
        )
        assert decision_row["action_label"] == "crear un seguimiento"
        assert decision_row["target_label"] == "María E2E"
        assert decision_row["target_kind"] == "lead"
        assert decision_row["target_focus_id"] == lead_id
        assert lead_id not in decision_row["target_label"]

        # 2) Email del digest: lead y factura por nombre humano + pista de
        #    módulo, y ninguna clave técnica (UUID ni inv-…).
        response = client.post("/digest/send?dry_run=true", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "dry_run"
        body = data["body"]
        assert "María E2E (en Clientes)" in body
        assert f"Acme E2E ({invoice_number}) (en Ventas)" in body
        assert lead_id not in body
        assert invoice_id not in body
        assert "REVERTIR " + decision_id in body

        # 3) El JSON del digest expone el mismo contrato humanizado.
        digest_json = data["digest"]
        seeded_decision = next(
            d for d in digest_json["decisions"] if d["id"] == decision_id
        )
        assert seeded_decision["target_label"] == "María E2E"
        assert seeded_decision["target_kind"] == "lead"
        assert seeded_decision["target_focus_id"] == lead_id
        seeded_proposal = next(
            p for p in digest_json["pending"] if p["id"] == proposal_id
        )
        assert seeded_proposal["target_label"] == f"Acme E2E ({invoice_number})"
        assert seeded_proposal["target_kind"] == "invoice"
        assert seeded_proposal["target_focus_id"] == invoice_id
    finally:
        _cleanup(
            decision_ids=decision_ids,
            activity_ids=activity_ids,
            proposal_ids=proposal_ids,
            lead_ids=lead_ids,
            invoice_ids=invoice_ids,
            customer_ids=customer_ids,
        )
