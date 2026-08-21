"""Evals T-067: CEO agent — mando en lenguaje natural para el dueño.

Cubre:

- Resolución determinista de intención (sin LLM): ventas, pipeline, leads,
  actividades, aprobaciones, inbox social, stock, follow-up de leads fríos,
  ayuda y mensaje sin resolver.
- Chat del dueño: responde con datos reales de la BD (nunca inventa),
  audita cada mensaje como ``ceo_chat.message`` y guarda la conversación en
  la memoria.
- Acciones: «haz follow-up a los leads fríos» NO ejecuta — crea propuestas
  ``agent_proposal:ceo_follow_up`` pendientes; aprobarlas crea la actividad
  (misma transacción, auditado); re-pedir no duplica.
- Registro: ``ceo_agent`` en el registro con módulo ``ceo`` y solo tools
  read-only (aparece en el panel de supervisión).
- RBAC: el chat del dueño exige rol operador (un viewer recibe 403).

Hermeticidad D-032: la BD del corpus es compartida entre módulos, así que
las aserciones de datos se acotan SIEMPRE a los ids únicos sembrados por el
propio test (nunca a totales globales) y se limpian en ``finally``.
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
    ApprovalRequest,
    AuditLog,
    Campaign,
    ConversationMessage,
    Customer,
    InvoiceDraft,
    Lead,
    Opportunity,
    ScheduledTask,
    User,
)
from app.services import ceo_agent
from app.services.agent_proposals import CEO_FOLLOW_UP_ACTION

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_lead(db, *, assigned_to=None, first_name="Lead", status="new", old: bool = False) -> Lead:
    lead = Lead(
        id=_unique("ceo-lead"),
        email=f"{_unique('ceo-lead')}@example.invalid",
        first_name=first_name,
        status=status,
        assigned_to=assigned_to,
        # ``_cold_leads`` ordena por ``created_at`` asc: sembrar con una
        # fecha antigua garantiza que NUESTROS leads entren en la cola de
        # candidatos aunque el corpus haya dejado otros leads sin asignar.
        created_at=(
            datetime.datetime(2020, 1, 1, 0, 0, 0) if old else None
        ),
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_opportunity(db, lead_id: str, *, value: Decimal, stage: str, status: str = "open") -> Opportunity:
    opp = Opportunity(
        id=_unique("ceo-opp"),
        lead_id=lead_id,
        external_reference=_unique("ceo-opp"),
        name="Oportunidad CEO test",
        monetary_value=value,
        stage=stage,
        status=status,
    )
    db.add(opp)
    db.flush()
    return opp


def _cleanup(ids: dict[str, list[str]]) -> None:
    db = SessionLocal()
    try:
        if ids.get("activities"):
            db.query(Activity).filter(Activity.id.in_(ids["activities"])).delete()
        if ids.get("approvals"):
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(ids["approvals"])).delete()
        if ids.get("opportunities"):
            db.query(Opportunity).filter(Opportunity.id.in_(ids["opportunities"])).delete()
        if ids.get("leads"):
            db.query(Lead).filter(Lead.id.in_(ids["leads"])).delete()
        if ids.get("tasks"):
            db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids["tasks"])).delete()
        if ids.get("autonomies"):
            db.query(AgentAutonomy).filter(AgentAutonomy.id.in_(ids["autonomies"])).delete()
        if ids.get("conversations"):
            db.query(ConversationMessage).filter(
                ConversationMessage.account_id == "ceo",
                ConversationMessage.conversation_id.in_(ids["conversations"]),
            ).delete()
        if ids.get("campaigns"):
            db.query(Campaign).filter(Campaign.id.in_(ids["campaigns"])).delete()
        if ids.get("invoices"):
            db.query(InvoiceDraft).filter(InvoiceDraft.id.in_(ids["invoices"])).delete()
        if ids.get("customers"):
            db.query(Customer).filter(Customer.id.in_(ids["customers"])).delete()
        db.commit()
    finally:
        db.close()


def _ceo_chat(client, token, message: str, conversation_id: str | None = None):
    return client.post(
        "/ceo/chat",
        json={
            "message": message,
            "conversation_id": conversation_id or _unique("ceo-conv"),
        },
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Resolución determinista de intención
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,intent",
    [
        ("¿cómo van las ventas?", "sales_summary"),
        ("cuéntame las ventas de este mes", "sales_summary"),
        ("¿cuánto hemos facturado?", "sales_summary"),
        ("¿cómo va el pipeline?", "pipeline_status"),
        ("muéstrame el embudo de oportunidades", "pipeline_status"),
        ("¿cuántos leads hay?", "leads_summary"),
        ("dime cuántos leads tenemos", "leads_summary"),
        ("¿qué actividades tengo pendientes?", "activities_due"),
        ("qué tareas vencen hoy", "activities_due"),
        ("¿qué hay que aprobar?", "approvals_pending"),
        ("muéstrame las aprobaciones pendientes", "approvals_pending"),
        ("¿hay mensajes urgentes en la bandeja social?", "social_inbox"),
        ("¿qué hay en el inbox de whatsapp?", "social_inbox"),
        ("¿hay stock bajo?", "stock_alert"),
        ("qué productos están agotados", "stock_alert"),
        ("haz follow-up a los leads fríos", "follow_up_cold_leads"),
        ("contacta a los leads sin asignar", "follow_up_cold_leads"),
        ("muestra las automatizaciones", "automations_status"),
        ("¿qué automatizaciones hay programadas?", "automations_status"),
        ("estado de los agentes", "agents_status"),
        ("¿quién gestiona cada módulo?", "agents_status"),
        ("pausa el sync de prestashop", "automation_toggle"),
        ("activa la alerta de stock bajo", "automation_toggle"),
        ("¿qué puedes hacer?", "help"),
        ("ayúdame con el resumen diario", "help"),
        ("hola", "greeting"),
        ("buenos días", "greeting"),
        ("hdfgsd qwzxcv", "unknown"),
    ],
)
def test_resolve_intent_is_deterministic(message: str, intent: str) -> None:
    assert ceo_agent.resolve_intent(message) == intent


# ---------------------------------------------------------------------------
# Chat del dueño: lectura con datos reales + auditoría + memoria
# ---------------------------------------------------------------------------

def test_ceo_chat_sales_summary_reads_real_data(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"leads": [], "opportunities": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Cliente CEO")
        ids["leads"].append(lead.id)
        _seed_opportunity(db, lead.id, value=Decimal("120.00"), stage="new")
        _seed_opportunity(db, lead.id, value=Decimal("300.00"), stage="won", status="won")
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(client, auth_headers["Authorization"].split()[-1], "¿cómo van las ventas?")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "sales_summary"
        assert data["answer"], "Debe responder siempre"
        assert "oportunidades" in data["answer"].lower()
        # El chat es texto plano: nunca markdown crudo ni viñetas (T-… 2026-08-19)
        assert "**" not in data["answer"] and "*" not in data["answer"]
        assert not data["answer"].lstrip().startswith(("-", "·", "*", "#"))
        assert data["provider"] == "deterministic"  # sin LLM real: plantilla honesta

        db = SessionLocal()
        try:
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "ceo_chat.message")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert audit.agent_id == "ceo_agent"
            assert audit.details.get("intent") == "sales_summary"
            assert audit.details.get("answer")
            messages = (
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.account_id == "ceo",
                    ConversationMessage.conversation_id == data["conversation_id"],
                )
                .order_by(ConversationMessage.sequence.asc())
                .all()
            )
            assert [m.role for m in messages] == ["client", "assistant"]
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_unknown_offers_help(client, auth_headers) -> None:
    response = _ceo_chat(client, auth_headers["Authorization"].split()[-1], "zxqwy asdñ")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["intent"] == "unknown"
    assert "No he entendido" in data["answer"]
    assert data["proposals"] == []


# ---------------------------------------------------------------------------
# Acción: follow-up de leads fríos → propuesta con aprobación humana
# ---------------------------------------------------------------------------

def test_ceo_chat_follow_up_proposes_and_approval_applies(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"leads": [], "opportunities": [], "approvals": [], "activities": []}
    db = SessionLocal()
    try:
        cold_a = _seed_lead(db, first_name="Lead Frio A", old=True)
        cold_b = _seed_lead(db, first_name="Lead Frio B", old=True)
        assigned = _seed_lead(db, first_name="Lead Asignado", assigned_to="commercial-1")
        cold_a_id, cold_b_id, assigned_id = cold_a.id, cold_b.id, assigned.id
        ids["leads"] = [cold_a_id, cold_b_id, assigned_id]
        db.commit()
    finally:
        db.close()
    cold_a_id = str(cold_a_id)
    cold_b_id = str(cold_b_id)
    assigned_id = str(assigned_id)
    try:
        token = auth_headers["Authorization"].split()[-1]
        response = _ceo_chat(client, token, "haz follow-up a los leads fríos")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "follow_up_cold_leads"
        # Solo los leads SIN asignar entran en la propuesta: acotamos la
        # aserción a nuestros seeds (la BD del corpus es compartida).
        targets = {p["target_key"] for p in data["proposals"]}
        assert {cold_a_id, cold_b_id}.issubset(targets), "Los leads fríos propios deben entrar"
        assert assigned_id not in targets, "Un lead con comercial asignado nunca se propone"
        assert all(p["requested_by"] == "ceo_agent" for p in data["proposals"])
        assert all(p["action_type"] == CEO_FOLLOW_UP_ACTION for p in data["proposals"])
        ids["approvals"] = [p["id"] for p in data["proposals"] if p["target_key"] == cold_a_id]

        db = SessionLocal()
        try:
            pending = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.id.in_(ids["approvals"]),
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.requested_by == "ceo_agent",
                )
                .count()
            )
            assert pending == 1
        finally:
            db.close()

        # Aprobar la propuesta de cold_a crea la actividad (misma transacción).
        approve = client.post(
            f"/approvals/{ids['approvals'][0]}/approve",
            json={},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text
        applied = approve.json()["applied"]
        assert applied.get("activity_id")
        ids["activities"].append(applied["activity_id"])

        db = SessionLocal()
        try:
            activity = db.query(Activity).filter(Activity.id == applied["activity_id"]).first()
            assert activity is not None
            assert activity.status == "pending"
            assert activity.created_by == "agent:ceo_agent"
            assert activity.lead_id == cold_a_id
            executed = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "agent_proposal.executed")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert executed is not None
            assert executed.agent_id == "ceo_agent"
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_approvals_humanize_target_keys(client, auth_headers) -> None:
    """Las claves objetivo (UUID del lead, «inv-…») se traducen al nombre
    humano en el chat: el nombre del lead y el cliente de la factura."""

    ids: dict[str, list[str]] = {
        "leads": [],
        "approvals": [],
        "customers": [],
        "invoices": [],
    }
    lead_id = invoice_id = invoice_number = ""
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Cliente María")
        lead_id = str(lead.id)
        ids["leads"].append(lead_id)
        follow_up = ApprovalRequest(
            id=f"appr-{uuid.uuid4().hex[:12]}",
            action_type=CEO_FOLLOW_UP_ACTION,
            target_key=lead_id,
            payload={"title": f"Follow-up CEO: {lead.first_name}"},
            requested_by="ceo_agent",
            status="pending",
        )
        db.add(follow_up)
        ids["approvals"].append(follow_up.id)

        customer = Customer(
            id=_unique("ceo-cust"),
            name="Acme SL",
            email=f"{_unique('ceo-cust')}@example.invalid",
        )
        db.add(customer)
        invoice = InvoiceDraft(
            id=f"inv-{uuid.uuid4().hex[:10]}",
            invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
            order_id=_unique("ceo-order"),
            customer_id=str(customer.id),
            items=[{"sku": "SKU-1", "quantity": 1}],
            total_amount=Decimal("121.00"),
            tax_amount=Decimal("21.00"),
            currency="EUR",
            status="draft",
        )
        db.add(invoice)
        invoice_id = str(invoice.id)
        invoice_number = str(invoice.invoice_number)
        inv_approval = ApprovalRequest(
            id=f"appr-{uuid.uuid4().hex[:12]}",
            action_type="issue_invoice",
            target_key=invoice_id,
            payload={
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
            },
            requested_by="sales_agent",
            status="pending",
        )
        db.add(inv_approval)
        ids["approvals"].append(inv_approval.id)
        ids["invoices"].append(invoice_id)
        ids["customers"].append(str(customer.id))
        db.commit()
    finally:
        db.close()

    try:
        db = SessionLocal()
        try:
            gathered = ceo_agent._gather_approvals(db)
        finally:
            db.close()
        by_target = {i["target_key"]: i["target_label"] for i in gathered["items"]}
        assert by_target.get(lead_id) == "Cliente María"
        assert by_target.get(invoice_id) == f"Acme SL ({invoice_number})"

        # El chat nunca vuelca nuestras claves técnicas: o muestra el nombre
        # humano o (si la propuesta queda fuera de la muestra) nada de ella.
        response = _ceo_chat(
            client, auth_headers["Authorization"].split()[-1], "¿qué hay que aprobar?"
        )
        assert response.status_code == 200, response.text
        answer = response.json()["answer"]
        assert lead_id not in answer
        assert invoice_id not in answer
        assert "agent_proposal:" not in answer
        assert "issue_invoice" not in answer
    finally:
        _cleanup(ids)


def test_ceo_chat_follow_up_dedupes(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"leads": [], "opportunities": [], "approvals": []}
    db = SessionLocal()
    try:
        lead = _seed_lead(db, first_name="Lead Unico", old=True)
        lead_id = str(lead.id)
        ids["leads"].append(lead_id)
        db.commit()
    finally:
        db.close()
    try:
        token = auth_headers["Authorization"].split()[-1]
        first = _ceo_chat(client, token, "haz seguimiento a los leads sin asignar")
        assert first.status_code == 200, first.text
        first_targets = {p["target_key"] for p in first.json()["proposals"]}
        assert lead_id in first_targets
        ids["approvals"] = [p["id"] for p in first.json()["proposals"] if p["target_key"] == lead_id]

        second = _ceo_chat(client, token, "haz seguimiento a los leads sin asignar")
        assert second.status_code == 200, second.text
        second_targets = {p["target_key"] for p in second.json()["proposals"]}
        assert lead_id not in second_targets, "Re-pedir no debe duplicar la propuesta de un lead"
    finally:
        _cleanup(ids)


# ---------------------------------------------------------------------------
# Registro: ceo_agent en AGENT_REGISTRY con tools read-only
# ---------------------------------------------------------------------------

def test_ceo_agent_registered_with_module_and_read_tools() -> None:
    from app.main import AGENT_REGISTRY
    from app.services.tool_policy import TOOL_SPECS, authorized_tools_for

    agent = AGENT_REGISTRY.get("ceo_agent")
    assert agent is not None, "El CEO agent debe estar registrado"
    assert agent["module"] == "ceo"
    assert agent["module_label"] == "Dirección (CEO)"
    assert agent["autonomy_level"] == "L0_Respuesta_Limitada"
    assert agent["status"] == "active"
    authorized = authorized_tools_for(agent)
    assert authorized, "Debe autorizar tools de lectura"
    for tool in authorized:
        assert TOOL_SPECS[tool]["kind"] == "read", f"{tool} debe ser read-only"


def test_ceo_chat_requires_operator_role(client, auth_headers) -> None:
    username = _unique("viewer-ceo")
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": PORTAL_TEST_PASSWORD,
            "role": "viewer",
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    viewer_token = login.json()["access_token"]
    try:
        response = _ceo_chat(client, viewer_token, "¿cómo van las ventas?")
        assert response.status_code == 403, response.text
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# T-071: gestión desde el chat — automatizaciones, agentes y acciones
# ---------------------------------------------------------------------------

def _seed_task(db, *, name: str | None = None, status: str = "active") -> ScheduledTask:
    uid = _unique("ceo-task")
    task = ScheduledTask(
        id=uid,
        name=name or f"Sync PrestaShop {uid[-4:]}",
        task_type="prestashop_sync",
        payload={},
        interval_seconds=86_400,
        status=status,
        version=1,
        created_by="test",
        updated_by="test",
    )
    db.add(task)
    db.flush()
    return task


def test_ceo_chat_automations_status_reads_real_data(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"tasks": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    db = SessionLocal()
    try:
        task = _seed_task(db, name="Sync PrestaShop Diario T071")
        ids["tasks"].append(task.id)
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "muestra las automatizaciones",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "automations_status"
        assert "Sync PrestaShop Diario T071" in data["answer"]
        assert data["provider"] == "deterministic"
    finally:
        _cleanup(ids)


def test_ceo_chat_agents_status_reads_real_data(client, auth_headers) -> None:
    # La BD del corpus es compartida: otra prueba puede haber creado la fila de
    # autonomía del crm_agent. Se hace get-or-update y se restaura el estado
    # previo (modo anterior o borrado si la creó esta prueba) en el cleanup.
    from app.services.autonomy import get_config

    ids: dict[str, list[str]] = {"autonomies": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    created_row = False
    previous_mode: str | None = None
    db = SessionLocal()
    try:
        autonomy = get_config(db, agent_id="crm_agent")
        # Detectamos si la fila ya existía consultando antes del get-or-create.
        pre = (
            db.query(AgentAutonomy)
            .filter(AgentAutonomy.agent_id == "crm_agent")
            .first()
        )
        previous_mode = pre.mode if pre else None
        if pre is None:
            created_row = True
            ids["autonomies"].append(autonomy.id)
        autonomy.mode = "autonomous"
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "estado de los agentes",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "agents_status"
        assert "agentes de ia" in data["answer"].lower()
        assert "autónomo" in data["answer"].lower()
    finally:
        db = SessionLocal()
        try:
            row = (
                db.query(AgentAutonomy)
                .filter(AgentAutonomy.agent_id == "crm_agent")
                .first()
            )
            if row is not None:
                if created_row:
                    db.delete(row)
                elif previous_mode is not None:
                    row.mode = previous_mode
            db.commit()
        finally:
            db.close()
        _cleanup(ids)


def test_ceo_chat_automation_toggle_proposes_and_approval_applies(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {"tasks": [], "approvals": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    db = SessionLocal()
    try:
        task = _seed_task(db, name="Sync PrestaShop Pausa T071")
        ids["tasks"].append(task.id)
        # El id se captura como string dentro del bloque de seed: al cerrar la
        # sesión el objeto queda detached y cualquier atributo no cargado
        # lanzaría DetachedInstanceError.
        task_id = str(task.id)
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "pausa el sync PrestaShop Pausa T071",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "automation_toggle"
        assert len(data["proposals"]) == 1, data
        assert data["proposals"][0]["action_type"] == "agent_proposal:automation_toggle"
        assert data["proposals"][0]["status"] == "pending"
        approval_id = data["proposals"][0]["id"]
        ids["approvals"].append(approval_id)

        # Aprobar desde el panel aplica el cambio (pausa) en la misma transacción.
        approve = client.post(
            f"/approvals/{approval_id}/approve",
            json={"rejection_reason": None},
            headers=auth_headers,
        )
        assert approve.status_code == 200, approve.text

        db = SessionLocal()
        try:
            task_row = (
                db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            )
            assert task_row is not None
            assert task_row.status == "paused"
            assert task_row.next_run_at is None
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_automation_toggle_matches_partial_name(client, auth_headers) -> None:
    """El usuario puede nombrar solo una parte del nombre (hallazgo en vivo)."""

    ids: dict[str, list[str]] = {"tasks": [], "approvals": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    db = SessionLocal()
    try:
        task = _seed_task(db, name="Barrido E2E e2ef409435f495e")
        ids["tasks"].append(task.id)
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "pausa el barrido E2E",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "automation_toggle", data
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:automation_toggle"
        assert proposal["status"] == "pending"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)
        # El payload queda en la BD: la tarea correcta es la del nombre completo.
        from app.models.models import ApprovalRequest

        db = SessionLocal()
        try:
            row = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
            assert row is not None
            assert row.payload.get("name") == "Barrido E2E e2ef409435f495e"
            assert row.payload.get("action") == "pause"
        finally:
            db.close()
    finally:
        _cleanup(ids)


# ---------------------------------------------------------------------------
# T-075: órdenes de acción por módulo desde el chat (crear lead, mover
# oportunidad, crear tarea, lanzar campaña) — siempre como propuestas
# auditadas (deny-by-default; se aplican al aprobar).
# ---------------------------------------------------------------------------


def _approve_proposal(client, auth_headers, approval_id: str) -> None:
    response = client.post(
        f"/approvals/{approval_id}/approve",
        json={"rejection_reason": None},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


def test_ceo_chat_create_lead_proposes_and_approval_creates(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {"approvals": [], "leads": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    email = f"ana-{_unique('ceo-lead')}@example.invalid"
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            f"crea un lead {email} de Empresa SL",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "lead_create"
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_create_lead"
        assert proposal["status"] == "pending"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)

        # Aprobar desde el panel crea el lead real.
        _approve_proposal(client, auth_headers, approval_id)
        db = SessionLocal()
        try:
            lead = db.query(Lead).filter(Lead.email == email).first()
            assert lead is not None
            assert lead.first_name == "Empresa SL" or lead.first_name == "Lead vía chat"
            ids["leads"].append(lead.id)
        finally:
            db.close()

        # Dedupe: repetir el mismo mensaje no crea una segunda propuesta.
        repeat = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            f"crea un lead {email} de Empresa SL",
            conversation_id=conv,
        )
        assert repeat.status_code == 200, repeat.text
        assert repeat.json()["intent"] == "lead_create"
        assert len(repeat.json()["proposals"]) == 0, repeat.text
    finally:
        _cleanup(ids)


def test_ceo_chat_create_lead_requires_email(client, auth_headers) -> None:
    ids: dict[str, list[str]] = {"conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "crea un lead sin email",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "lead_create"
        assert len(data["proposals"]) == 0
        assert "email" in data["answer"].lower()
    finally:
        _cleanup(ids)


def test_ceo_chat_move_opportunity_proposes_and_approval_moves(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {
        "approvals": [],
        "leads": [],
        "opportunities": [],
        "conversations": [],
    }
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    db = SessionLocal()
    try:
        lead = _seed_lead(db)
        ids["leads"].append(lead.id)
        opp = _seed_opportunity(db, lead.id, value=Decimal("500"), stage="new")
        ids["opportunities"].append(opp.id)
        opp_id = str(opp.id)
        db.commit()
    finally:
        db.close()
    try:
        # Se usa el id (no el nombre) para un match determinista: el nombre
        # «Oportunidad CEO test» es compartido por todos los seeds del módulo.
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            f"mueve la oportunidad {opp_id} a negociacion",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "opportunity_move", data
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_move_opportunity"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)

        _approve_proposal(client, auth_headers, approval_id)
        db = SessionLocal()
        try:
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            assert opp is not None
            assert opp.stage == "negotiation"
            assert opp.stage_changed_at is not None
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_move_opportunity_not_found_replies_helpfully(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {"conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "mueve la oportunidad Oportunidad Inexistente a negociacion",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "opportunity_move"
        assert len(data["proposals"]) == 0
        assert "No he encontrado" in data["answer"]
    finally:
        _cleanup(ids)


def test_ceo_chat_create_task_proposes_and_approval_creates_activity(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {
        "approvals": [],
        "activities": [],
        "conversations": [],
    }
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            "crea una tarea para llamar a Carlos",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "task_create", data
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_create_task"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)

        _approve_proposal(client, auth_headers, approval_id)
        db = SessionLocal()
        try:
            activity = (
                db.query(Activity)
                .filter(Activity.created_by == "agent:ceo_agent")
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert activity is not None
            assert activity.status == "pending"
            assert activity.kind == "call"
            ids["activities"].append(activity.id)
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_launch_campaign_proposes_and_approval_creates_draft(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {"approvals": [], "campaigns": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    name = f"Campana chat {_unique('ceo-camp')}"
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            f"lanza una campana «{name}»",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "campaign_launch", data
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_launch_campaign"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)

        _approve_proposal(client, auth_headers, approval_id)
        db = SessionLocal()
        try:
            campaign = db.query(Campaign).filter(Campaign.name == name).first()
            assert campaign is not None
            assert campaign.status == "draft"
            ids["campaigns"].append(campaign.id)
        finally:
            db.close()
    finally:
        _cleanup(ids)


def test_ceo_chat_launch_existing_campaign_proposes_activation(
    client, auth_headers
) -> None:
    ids: dict[str, list[str]] = {"approvals": [], "campaigns": [], "conversations": []}
    conv = _unique("ceo-conv")
    ids["conversations"].append(conv)
    db = SessionLocal()
    try:
        campaign = Campaign(
            name=f"Campana existente {_unique('ceo-camp')}",
            description="previa",
            template_name="welcome",
            segment={},
            status="draft",
        )
        db.add(campaign)
        db.flush()
        campaign_name = str(campaign.name)
        db.commit()
    finally:
        db.close()
    try:
        response = _ceo_chat(
            client,
            auth_headers["Authorization"].split()[-1],
            f"lanza la campana «{campaign_name}»",
            conversation_id=conv,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["intent"] == "campaign_launch", data
        assert len(data["proposals"]) == 1, data
        proposal = data["proposals"][0]
        assert proposal["action_type"] == "agent_proposal:ceo_launch_campaign"
        approval_id = proposal["id"]
        ids["approvals"].append(approval_id)

        _approve_proposal(client, auth_headers, approval_id)
        db = SessionLocal()
        try:
            campaign = db.query(Campaign).filter(Campaign.name == campaign_name).first()
            assert campaign is not None
            assert campaign.status == "active"
            ids["campaigns"].append(campaign.id)
        finally:
            db.close()
    finally:
        _cleanup(ids)
