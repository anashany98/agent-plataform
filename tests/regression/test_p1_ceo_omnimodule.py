"""Evals T-082: CEO agent omnimódulo — 8 nuevas capacidades de gestión.

El chat del dueño gana poder sin romper el deny-by-default:

- **Lectura** (informes, solo datos verificados): resumen de la empresa
  (``weekly_report``), antigüedad del pipeline (``aging_report``), productos
  más vendidos (``top_products``) y mensajes urgentes fuera de SLA
  (``social_sla``).
- **Acción** (siempre propuesta auditada): asignar un lead a un comercial
  (``ceo_assign_lead``), cerrar una oportunidad ganada/perdida
  (``ceo_close_opportunity``), ajustar stock (``ceo_adjust_stock``) y
  actualizar el precio de un producto (``ceo_update_price`` — financiera:
  solo se auto-ejecuta bajo el umbral de autonomía).
- **Autonomía**: las tres primeras acciones son seguras/reversibles y entran
  en ``SAFE_AUTO_ACTIONS``; el cambio de precio queda fuera del sobre seguro
  y depende del umbral ``max_value_threshold`` del CEO agent.

Hermeticidad D-032: la BD del corpus es compartida, así que las aserciones
se acotan SIEMPRE a los ids únicos sembrados por el propio test y se limpian
en ``finally`` (incluidas propuestas, decisiones y conversaciones del chat).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.models.models import (
    Activity,
    AgentAutonomy,
    AgentDecision,
    ApprovalRequest,
    ConversationMessage,
    Lead,
    Opportunity,
    Order,
    Product,
    SocialMessage,
    SocialTriage,
    User,
)
from app.services import ceo_agent


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_lead(db, *, first_name: str, email: str | None = None) -> Lead:
    lead = Lead(
        id=_unique("omni-lead"),
        email=email or f"{_unique('omni-lead')}@example.invalid",
        first_name=first_name,
        status="new",
        source="local",
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_user(db, *, username: str) -> User:
    user = User(
        id=_unique("omni-user"),
        username=username,
        password_hash="x",
        role="commercial",
        is_active=True,
        must_change_password=False,
        token_version=0,
    )
    db.add(user)
    db.flush()
    return user


def _seed_opportunity(
    db, lead_id: str, *, name: str, stage: str, value: Decimal,
    stage_changed_at: datetime.datetime | None = None,
) -> Opportunity:
    opp = Opportunity(
        id=_unique("omni-opp"),
        lead_id=lead_id,
        external_reference=_unique("omni-opp"),
        name=name,
        monetary_value=value,
        stage=stage,
        status="open",
        stage_changed_at=stage_changed_at or datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )
    db.add(opp)
    db.flush()
    return opp


def _seed_product(db, *, sku: str, price: float, stock: int = 10) -> Product:
    product = Product(
        id=_unique("omni-prod"),
        sku=sku,
        name=f"Producto {sku}",
        base_price=Decimal(str(price)),
        stock_quantity=stock,
        reserved_stock=0,
        source="local",
    )
    db.add(product)
    db.flush()
    return product


def _seed_order(db, product: Product, *, qty: int, unit_price: float) -> Order:
    order = Order(
        id=_unique("omni-order"),
        customer_id=_unique("omni-cust"),
        quote_id=_unique("omni-quote"),
        idempotency_key=_unique("omni-idem"),
        items=[{"product_id": product.id, "qty": qty, "unit_price": unit_price}],
        subtotal=Decimal(str(qty * unit_price)),
        tax_total=Decimal("0.00"),
        shipping_total=Decimal("0.00"),
        grand_total=Decimal(str(qty * unit_price)),
        currency="EUR",
        status="confirmed",
    )
    db.add(order)
    db.flush()
    return order


def _seed_urgent_message(db) -> str:
    message = SocialMessage(
        id=_unique("omni-msg"),
        channel_id="ch-omni",
        source_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        body="Mi pedido no ha llegado y no me responden",
        sender_name="Cliente Urgente",
        status="triaged",
        lead_id=None,
    )
    db.add(message)
    db.flush()
    db.add(
        SocialTriage(
            message_id=message.id,
            intent="queja",
            language="es",
            register="formal",
            urgency=80,
            score_social=70,
            summary="Queja sin atender",
            decided_by="deterministic",
        )
    )
    db.flush()
    return message.id


def _cleanup(ids: dict[str, list[str]]) -> None:
    db = SessionLocal()
    try:
        if ids.get("decisions"):
            db.query(AgentDecision).filter(AgentDecision.id.in_(ids["decisions"])).delete()
        if ids.get("approvals"):
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(ids["approvals"])).delete()
        if ids.get("activities"):
            db.query(Activity).filter(Activity.id.in_(ids["activities"])).delete()
        if ids.get("orders"):
            db.query(Order).filter(Order.id.in_(ids["orders"])).delete()
        if ids.get("messages"):
            db.query(SocialTriage).filter(SocialTriage.message_id.in_(ids["messages"])).delete()
            db.query(SocialMessage).filter(SocialMessage.id.in_(ids["messages"])).delete()
        if ids.get("products"):
            db.query(Product).filter(Product.id.in_(ids["products"])).delete()
        if ids.get("opportunities"):
            db.query(Opportunity).filter(Opportunity.id.in_(ids["opportunities"])).delete()
        if ids.get("leads"):
            db.query(Lead).filter(Lead.id.in_(ids["leads"])).delete()
        if ids.get("users"):
            db.query(User).filter(User.id.in_(ids["users"])).delete()
        if ids.get("autonomies"):
            db.query(AgentAutonomy).filter(AgentAutonomy.id.in_(ids["autonomies"])).delete()
        if ids.get("conversations"):
            db.query(ConversationMessage).filter(
                ConversationMessage.account_id == "ceo",
                ConversationMessage.conversation_id.in_(ids["conversations"]),
            ).delete()
        db.commit()
    finally:
        db.close()


def _ceo_chat(client, token: str, message: str) -> dict:
    response = client.post(
        "/ceo/chat",
        json={
            "message": message,
            "conversation_id": _unique("omni-conv"),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_autonomy(
    *,
    mode: str = "autonomous",
    allowed_actions: list[str] | None = None,
    max_value_threshold: float = 0.0,
    max_actions_per_day: int = 20,
) -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(AgentAutonomy)
            .filter(
                AgentAutonomy.installation_id == "test-installation",
                AgentAutonomy.agent_id == "ceo_agent",
            )
            .first()
        )
        if row is None:
            row = AgentAutonomy(
                installation_id="test-installation",
                agent_id="ceo_agent",
                mode="manual",
                max_value_threshold=0,
                allow_follow_ups=False,
                allow_spam_dismissals=False,
                notify_on_deviation_only=False,
            )
            db.add(row)
        row.mode = mode
        row.allowed_actions = allowed_actions
        row.max_value_threshold = max_value_threshold
        row.max_actions_per_day = max_actions_per_day
        db.commit()
        return str(row.id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Resolución determinista de las nuevas intenciones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,intent",
    [
        ("¿resumen de la semana?", "weekly_report"),
        ("¿cómo está la empresa?", "weekly_report"),
        ("¿qué oportunidades llevan más tiempo abiertas?", "aging_report"),
        ("¿qué productos se venden más?", "top_products"),
        ("¿hay mensajes sin atender en la bandeja?", "social_sla"),
        ("asigna el lead de ana@empresa.com a carlos", "lead_assign"),
        ("cierra el trato Q-1 como ganada", "opportunity_close"),
        ("ajusta el stock de SKU-100 a 25", "stock_adjust"),
        ("actualiza el precio de SKU-100 a 45,90", "product_price_update"),
    ],
)
def test_resolve_intent_new_capabilities(message: str, intent: str) -> None:
    assert ceo_agent.resolve_intent(message) == intent


# ---------------------------------------------------------------------------
# Informes de gestión (lectura con datos reales)
# ---------------------------------------------------------------------------

def test_ceo_chat_reads_aging_and_top_products(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "leads": [], "opportunities": [], "products": [], "orders": [],
        "conversations": [],
    }
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Cliente Omni")
        ids["leads"].append(lead.id)
        old = _seed_opportunity(
            db, lead.id, name="Presupuesto Estancado",
            stage="negotiation", value=Decimal("500.00"),
            stage_changed_at=datetime.datetime(2020, 1, 1, 0, 0, 0),
        )
        ids["opportunities"].append(old.id)
        recent = _seed_opportunity(
            db, lead.id, name="Presupuesto Reciente", stage="new",
            value=Decimal("50.00"),
        )
        ids["opportunities"].append(recent.id)
        product = _seed_product(db, sku="OMNI-100", price=10.0)
        ids["products"].append(product.id)
        order = _seed_order(db, product, qty=3, unit_price=10.0)
        ids["orders"].append(order.id)
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        aging = _ceo_chat(client, token, "¿qué oportunidades llevan más tiempo abiertas?")
        assert aging["intent"] == "aging_report"
        assert aging["provider"] == "deterministic"
        assert "Presupuesto Estancado" in aging["answer"]
        assert "500" in aging["answer"]

        top = _ceo_chat(client, token, "¿qué productos se venden más?")
        assert top["intent"] == "top_products"
        assert "OMNI-100" in top["answer"]
        assert "3" in top["answer"]
    finally:
        _cleanup(ids)


def test_ceo_chat_reads_social_sla_and_weekly(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "leads": [], "messages": [], "conversations": [],
    }
    db = SessionLocal()
    try:
        ids["messages"].append(_seed_urgent_message(db))
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        sla = _ceo_chat(client, token, "¿hay mensajes sin atender?")
        assert sla["intent"] == "social_sla"
        assert "Cliente Urgente" in sla["answer"]

        weekly = _ceo_chat(client, token, "resumen de la semana")
        assert weekly["intent"] == "weekly_report"
        assert "Resumen de la empresa" in weekly["answer"]
    finally:
        _cleanup(ids)


# ---------------------------------------------------------------------------
# Acciones de módulo: propuesta + aprobación humana aplica el efecto
# ---------------------------------------------------------------------------

def test_ceo_chat_lead_assign_proposes_and_applies(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "leads": [], "users": [], "approvals": [], "conversations": [],
    }
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Ana Empresa", email="ana.omni@example.com")
        user = _seed_user(db, username="carlos")
        ids["leads"] = [lead.id]
        ids["users"] = [user.id]
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        data = _ceo_chat(client, token, "asigna el lead de ana.omni@example.com a carlos")
        assert data["intent"] == "lead_assign"
        assert data["proposals"], "debe crear la propuesta de asignación"
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_assign_lead"
        assert proposal["status"] == "pending"
        ids["approvals"].append(proposal["id"])

        approve = client.post(
            f"/approvals/{proposal['id']}/approve",
            json={},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text
        applied = approve.json()["applied"]
        assert applied.get("changed") is True
        assert applied.get("assignee") == ids["users"][0]

        db = SessionLocal()
        try:
            lead = db.query(Lead).filter(Lead.id == ids["leads"][0]).first()
            assert lead is not None
            assert lead.assigned_to == ids["users"][0]
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_opportunity_close_proposes_and_applies(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "leads": [], "opportunities": [], "approvals": [], "conversations": [],
    }
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Trato Q1")
        opp = _seed_opportunity(
            db, lead.id, name="Presupuesto Q-1", stage="negotiation",
            value=Decimal("800.00"),
        )
        ids["leads"] = [lead.id]
        ids["opportunities"] = [opp.id]
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        data = _ceo_chat(client, token, "cierra la oportunidad Presupuesto Q-1 como ganada")
        assert data["intent"] == "opportunity_close"
        assert data["proposals"], "debe crear la propuesta de cierre"
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_close_opportunity"
        ids["approvals"].append(proposal["id"])

        approve = client.post(
            f"/approvals/{proposal['id']}/approve",
            json={},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["applied"].get("outcome") == "won"

        db = SessionLocal()
        try:
            opp = db.query(Opportunity).filter(Opportunity.id == ids["opportunities"][0]).first()
            assert opp is not None
            assert opp.stage == "won"
            assert opp.status == "closed"
            assert opp.won_at is not None
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_stock_adjust_proposes_and_applies(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "products": [], "approvals": [], "conversations": [],
    }
    db = SessionLocal()
    try:
        product = _seed_product(db, sku="OMNI-STK", price=5.0, stock=10)
        ids["products"] = [product.id]
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        data = _ceo_chat(client, token, "ajusta el stock de OMNI-STK a 25")
        assert data["intent"] == "stock_adjust"
        assert data["proposals"], "debe crear la propuesta de ajuste"
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_adjust_stock"
        ids["approvals"].append(proposal["id"])

        approve = client.post(
            f"/approvals/{proposal['id']}/approve",
            json={},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["applied"].get("adjusted") is True

        db = SessionLocal()
        try:
            product = db.query(Product).filter(Product.id == ids["products"][0]).first()
            assert product is not None
            assert product.stock_quantity == 25
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_price_update_is_financial_and_threshold_gated(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "products": [], "approvals": [], "decisions": [], "conversations": [],
        "autonomies": [],
    }
    db = SessionLocal()
    try:
        p1 = _seed_product(db, sku="OMNI-PRC1", price=10.0)
        p2 = _seed_product(db, sku="OMNI-PRC2", price=10.0)
        p3 = _seed_product(db, sku="OMNI-PRC3", price=10.0)
        ids["products"] = [p1.id, p2.id, p3.id]
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        # Sin autonomía (manual): la propuesta queda pendiente (deny-by-default).
        manual = _ceo_chat(client, token, "actualiza el precio de OMNI-PRC1 a 45,90")
        assert manual["intent"] == "product_price_update"
        assert manual["proposals"]
        assert manual["proposals"][0]["status"] == "pending"
        ids["approvals"].append(manual["proposals"][0]["id"])

        # Autonomía con umbral alto: el cambio (45,90 < 100) se auto-ejecuta.
        ids["autonomies"].append(
            _set_autonomy(max_value_threshold=100.0, allowed_actions=[])
        )
        auto = _ceo_chat(client, token, "actualiza el precio de OMNI-PRC2 a 45,90")
        executed = [p for p in auto["proposals"] if p["status"] == "approved"]
        assert executed, "bajo el umbral debería auto-ejecutarse"
        ids["decisions"].extend(
            p["decision_id"] for p in executed if p.get("decision_id")
        )

        db = SessionLocal()
        try:
            product = db.query(Product).filter(Product.id == ids["products"][1]).first()
            assert product is not None
            assert float(product.base_price) == 45.90
        finally:
            db.close()

        # Umbral 0: cualquier precio queda por encima → se difiere al humano.
        ids["autonomies"].append(
            _set_autonomy(max_value_threshold=0.0, allowed_actions=[])
        )
        over = _ceo_chat(client, token, "actualiza el precio de OMNI-PRC3 a 99,00")
        pending = [p for p in over["proposals"] if p["status"] == "pending"]
        assert pending, "fuera del umbral debe quedar pendiente de aprobación humana"
        ids["approvals"].extend(p["id"] for p in pending)
    finally:
        _cleanup(ids)


# ---------------------------------------------------------------------------
# Autonomía: acciones seguras del omnimódulo se auto-ejecutan bajo autorización
# ---------------------------------------------------------------------------

def test_ceo_chat_assign_lead_auto_executes_with_autonomy(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {
        "leads": [], "users": [], "approvals": [], "decisions": [],
        "conversations": [], "autonomies": [],
    }
    db = SessionLocal()
    try:
        lead_a = _seed_lead(db, first_name="Ana Auto", email="ana.auto@example.com")
        lead_b = _seed_lead(db, first_name="Berta Auto", email="berta.auto@example.com")
        user = _seed_user(db, username="lucia")
        ids["leads"] = [lead_a.id, lead_b.id]
        ids["users"] = [user.id]
        db.commit()
    finally:
        db.close()

    token = auth_headers["Authorization"].split()[-1]
    try:
        # Sin autorización: la asignación queda pendiente.
        manual = _ceo_chat(client, token, "asigna el lead de ana.auto@example.com a lucia")
        assert manual["proposals"][0]["status"] == "pending"
        ids["approvals"].append(manual["proposals"][0]["id"])

        # Con allowed_actions + modo autónomo: se ejecuta al instante (otro lead).
        ids["autonomies"].append(
            _set_autonomy(allowed_actions=["agent_proposal:ceo_assign_lead"])
        )
        auto = _ceo_chat(client, token, "asigna el lead de berta.auto@example.com a lucia")
        executed = [p for p in auto["proposals"] if p["status"] == "approved"]
        assert executed, "la asignación autorizada debe auto-ejecutarse"
        ids["decisions"].extend(
            p["decision_id"] for p in executed if p.get("decision_id")
        )

        db = SessionLocal()
        try:
            lead = db.query(Lead).filter(Lead.id == ids["leads"][1]).first()
            assert lead is not None
            assert lead.assigned_to == ids["users"][0]
        finally:
            db.close()
    finally:
        _cleanup(ids)
