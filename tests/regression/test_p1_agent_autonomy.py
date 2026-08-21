"""Evals T-068: autonomía por excepción (umbrales, digest diario, revert).

Convierte la aprobación por caso en **supervisión por excepción**: cada
agente tiene una configuración por instalación (``AgentAutonomy``); las
propuestas dentro de lo autorizado se auto-ejecutan al instante y quedan
registradas como ``AgentDecision`` (auditado, con bandera de desviación y
reversible desde el digest); el resto sigue pendiente de aprobación humana.

Cubre:

- Deny-by-default: sin configuración, la ronda de propuestas NO auto-ejecuta
  nada (comportamiento anterior intacto).
- Configuración: GET/PUT de la autonomía por agente, auditoría
  ``agents.autonomy_updated`` y RBAC (viewer → 403, modo inválido → 422).
- Auto-ejecución por tipo de acción: follow-up del CRM y descarte de spam,
  cada uno gateado por su flag; efecto aplicado en la misma transacción que
  la aprobación humana (``reviewed_by=agent:<id>``).
- Flags fuera → la propuesta se difiere al panel humano.
- Digest diario: agrega decisiones por agente (totales, desviaciones,
  reverts) y cuenta las pendientes humanas.
- Revert: follow-up → ``cancelled``, spam → ``triaged`` de nuevo; doble
  revert → 409; auditoría ``agent_decision.reverted``.
- CEO chat: con el agente en autónomo, «haz follow-up a los leads fríos»
  ejecuta al instante y la respuesta lo dice.

Hermeticidad D-032: SQLite de test, seeds por ORM con ids únicos y limpieza
en ``finally`` (incluida la configuración de autonomía, que se restaura a
``manual`` para no contaminar el resto del corpus).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    Activity,
    AgentAutonomy,
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    Lead,
    ScheduledTask,
    SocialMessage,
    SocialTriage,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module", autouse=True)
def _restore_agent_side_effects():
    """Hermeticidad sobre la BD compartida del corpus.

    Los rounds con autonomía auto-ejecutan sobre TODA la instalación: si
    otro test dejó un lead social urgente, mi ronda le crea un follow-up
    que mi limpieza por id no conoce. Este fixture del módulo elimina en
    bloque (delta) las actividades de agentes, propuestas y decisiones
    creadas durante este módulo, para que ningún test posterior vea sus
    efectos (p. ej. los totales del calendario/agenda).
    """

    db = SessionLocal()
    try:
        before_acts = {
            row[0]
            for row in db.query(Activity.id)
            .filter(Activity.created_by.like("agent:%"))
            .all()
        }
        before_appr = {
            row[0]
            for row in db.query(ApprovalRequest.id)
            .filter(ApprovalRequest.action_type.like("agent_proposal:%"))
            .all()
        }
        before_dec = {row[0] for row in db.query(AgentDecision.id).all()}
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        new_acts = {
            row[0]
            for row in db.query(Activity.id)
            .filter(Activity.created_by.like("agent:%"))
            .all()
        } - before_acts
        if new_acts:
            db.query(Activity).filter(Activity.id.in_(new_acts)).delete()
        new_appr = {
            row[0]
            for row in db.query(ApprovalRequest.id)
            .filter(ApprovalRequest.action_type.like("agent_proposal:%"))
            .all()
        } - before_appr
        if new_appr:
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(new_appr)).delete()
        new_dec = {row[0] for row in db.query(AgentDecision.id).all()} - before_dec
        if new_dec:
            db.query(AgentDecision).filter(AgentDecision.id.in_(new_dec)).delete()
        db.commit()
    finally:
        db.close()


def _set_autonomy(
    agent_id: str,
    *,
    mode: str = "autonomous",
    allow_follow_ups: bool = False,
    allow_spam_dismissals: bool = False,
    max_value_threshold: float = 0.0,
    allowed_actions: list[str] | None = None,
    max_actions_per_day: int = 10,
) -> None:
    db = SessionLocal()
    try:
        row = (
            db.query(AgentAutonomy)
            .filter(
                AgentAutonomy.installation_id == "test-installation",
                AgentAutonomy.agent_id == agent_id,
            )
            .first()
        )
        if row is None:
            row = AgentAutonomy(
                installation_id="test-installation",
                agent_id=agent_id,
                mode="manual",
                max_value_threshold=0,
                allow_follow_ups=False,
                allow_spam_dismissals=False,
                notify_on_deviation_only=False,
            )
            db.add(row)
        row.mode = mode
        row.allow_follow_ups = allow_follow_ups
        row.allow_spam_dismissals = allow_spam_dismissals
        row.max_value_threshold = max_value_threshold
        row.allowed_actions = allowed_actions
        row.max_actions_per_day = max_actions_per_day
        db.commit()
    finally:
        db.close()


def _reset_autonomy(agent_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.query(AgentAutonomy).filter(
            AgentAutonomy.installation_id == "test-installation",
            AgentAutonomy.agent_id.in_(agent_ids),
        ).delete()
        db.commit()
    finally:
        db.close()


def _seed_urgent_lead() -> tuple[str, str]:
    """Lead con mensaje social urgente (queja) sin actividad pendiente."""

    db = SessionLocal()
    lead_id = _unique("aut-lead")
    message_id = _unique("aut-msg")
    try:
        db.add(
            Lead(
                id=lead_id,
                email=f"{_unique('aut')}@example.com",
                first_name="Urgencia Autonomía",
                source="social",
                status="new",
            )
        )
        db.flush()
        db.add(
            SocialMessage(
                id=message_id,
                channel_id="ch-aut",
                source_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
                body="Mi pedido llegó roto, necesito una solución ya",
                sender_name="Cliente Urgente",
                status="triaged",
                lead_id=lead_id,
            )
        )
        db.flush()
        db.add(
            SocialTriage(
                message_id=message_id,
                intent="queja",
                language="es",
                register="formal",
                urgency=80,
                score_social=70,
                summary="Queja por pedido dañado",
                decided_by="deterministic",
            )
        )
        db.commit()
    finally:
        db.close()
    return lead_id, message_id


def _seed_spam() -> str:
    db = SessionLocal()
    message_id = _unique("aut-spam")
    try:
        db.add(
            SocialMessage(
                id=message_id,
                channel_id="ch-aut",
                source_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
                body="COMPRA AHORA descuento increíble",
                sender_name="Spammer",
                status="triaged",
                lead_id=None,
            )
        )
        db.flush()
        db.add(
            SocialTriage(
                message_id=message_id,
                intent="spam",
                language="es",
                register="informal",
                urgency=0,
                score_social=0,
                summary="Spam promocional",
                decided_by="deterministic",
            )
        )
        db.commit()
    finally:
        db.close()
    return message_id


def _cleanup(
    *,
    leads: list[str] | None = None,
    messages: list[str] | None = None,
    activities: list[str] | None = None,
    approvals: list[str] | None = None,
    decisions: list[str] | None = None,
) -> None:
    db = SessionLocal()
    try:
        if decisions:
            db.query(AgentDecision).filter(AgentDecision.id.in_(decisions)).delete()
        if activities:
            db.query(Activity).filter(Activity.id.in_(activities)).delete()
        if approvals:
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(approvals)).delete()
        if messages:
            db.query(SocialTriage).filter(SocialTriage.message_id.in_(messages)).delete()
            db.query(SocialMessage).filter(SocialMessage.id.in_(messages)).delete()
        if leads:
            db.query(Lead).filter(Lead.id.in_(leads)).delete()
        db.commit()
    finally:
        db.close()


def _run_round(client, auth_headers):
    return client.post("/agent-proposals/run", headers=auth_headers)


# ---------------------------------------------------------------------------
# Deny-by-default: sin configuración nada se auto-ejecuta
# ---------------------------------------------------------------------------

def test_autonomy_defaults_deny_by_default(client, auth_headers) -> None:
    response = client.get("/agents/autonomy", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["default_mode"] == "manual"
    assert set(data["safe_actions"]) >= {
        "agent_proposal:create_follow_up",
        "agent_proposal:dismiss_message",
    }
    assert len(data["agents"]) >= 5
    for agent in data["agents"]:
        assert agent["mode"] == "manual"
        assert agent["max_value_threshold"] == 0.0
        assert agent["allow_follow_ups"] is False
        assert agent["allowed_actions"] == []
        assert agent["max_actions_per_day"] == 10

    lead_id, message_id = _seed_urgent_lead()
    spam_id = _seed_spam()
    try:
        result = _run_round(client, auth_headers).json()
        # Con defaults, la ronda propone pero NO ejecuta nada.
        assert result["auto_executed"] == 0
        assert result["deferred"] == result["proposed"]
        assert result["proposed"] >= 2
        for proposal in result["proposals"]:
            assert proposal["status"] == "pending"
    finally:
        _cleanup(leads=[lead_id], messages=[message_id, spam_id])


# ---------------------------------------------------------------------------
# Configuración: auditoría + RBAC + validación
# ---------------------------------------------------------------------------

def test_autonomy_config_update_audited(client, auth_headers) -> None:
    try:
        response = client.put(
            "/agents/autonomy/crm_agent",
            json={
                "mode": "autonomous",
                "max_value_threshold": 500.0,
                "allow_follow_ups": True,
                "allow_spam_dismissals": False,
                "notify_on_deviation_only": False,
                "allowed_actions": [
                    "agent_proposal:create_follow_up",
                    "agent_proposal:ceo_create_lead",
                ],
                "max_actions_per_day": 25,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "autonomous"
        assert body["max_value_threshold"] == 500.0
        assert body["allow_follow_ups"] is True
        assert body["allowed_actions"] == [
            "agent_proposal:create_follow_up",
            "agent_proposal:ceo_create_lead",
        ]
        assert body["max_actions_per_day"] == 25
        assert body["updated_by"] == "admin"

        listed = client.get("/agents/autonomy", headers=auth_headers).json()
        row = next(a for a in listed["agents"] if a["agent_id"] == "crm_agent")
        assert row["mode"] == "autonomous"
        assert row["allow_follow_ups"] is True
        assert row["allowed_actions"] == [
            "agent_proposal:create_follow_up",
            "agent_proposal:ceo_create_lead",
        ]
        assert row["max_actions_per_day"] == 25

        db = SessionLocal()
        try:
            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.installation_id == "test-installation",
                    AuditLog.event_type == "agents.autonomy_updated",
                    AuditLog.agent_id == "crm_agent",
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            details = audit.details or {}
            assert details["updated"]["mode"] == "autonomous"
            assert details["previous"]["mode"] == "manual"
        finally:
            db.close()

        # Modo inválido → 422; campo extra → 422.
        invalid = client.put(
            "/agents/autonomy/crm_agent",
            json={"mode": "autopilot"},
            headers=auth_headers,
        )
        assert invalid.status_code == 422
        extra = client.put(
            "/agents/autonomy/crm_agent",
            json={"mode": "manual", "surprise": 1},
            headers=auth_headers,
        )
        assert extra.status_code == 422
        # Acción no segura (financiera/desconocida) en allowed_actions → 422.
        unsafe = client.put(
            "/agents/autonomy/crm_agent",
            json={
                "mode": "autonomous",
                "allowed_actions": ["issue_invoice"],
            },
            headers=auth_headers,
        )
        assert unsafe.status_code == 422
        # Agente inexistente → 404.
        missing = client.put(
            "/agents/autonomy/ghost_agent",
            json={"mode": "manual"},
            headers=auth_headers,
        )
        assert missing.status_code == 404
    finally:
        _reset_autonomy(["crm_agent"])


def test_autonomy_config_requires_admin(client, auth_headers) -> None:
    username = _unique("aut-viewer")
    created = client.post(
        "/users",
        json={
            "username": username,
            "password": "Portal-Test-123!",
            "role": "viewer",
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    try:
        login = client.post(
            "/auth/login", json={"username": username, "password": "Portal-Test-123!"}
        )
        viewer_headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        response = client.put(
            "/agents/autonomy/crm_agent",
            json={"mode": "autonomous", "allow_follow_ups": True},
            headers=viewer_headers,
        )
        assert response.status_code == 403
    finally:
        _reset_autonomy(["crm_agent"])
        db = SessionLocal()
        try:
            from app.models.models import User

            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Auto-ejecución por tipo de acción (gated por flags)
# ---------------------------------------------------------------------------

def test_auto_execute_crm_follow_up(client, auth_headers) -> None:
    lead_id, message_id = _seed_urgent_lead()
    activities: list[str] = []
    approvals: list[str] = []
    decisions: list[str] = []
    try:
        _set_autonomy(
            "crm_agent",
            mode="autonomous",
            allow_follow_ups=True,
            max_value_threshold=200.0,
        )
        result = _run_round(client, auth_headers).json()
        assert result["auto_executed"] >= 1
        executed = [p for p in result["proposals"] if p["status"] == "approved"]
        assert any(p["target_key"] == lead_id for p in executed)
        decision_ids = [d["id"] for d in result["decisions"]]
        decisions.extend(decision_ids)
        for p in executed:
            approvals.append(p["id"])

        db = SessionLocal()
        try:
            # La propuesta quedó aprobada por el agente (no por un humano).
            approval = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.action_type == "agent_proposal:create_follow_up",
                    ApprovalRequest.target_key == lead_id,
                )
                .order_by(ApprovalRequest.created_at.desc())
                .first()
            )
            assert approval is not None
            assert approval.status == "approved"
            assert approval.reviewed_by == "agent:crm_agent"

            # La actividad se creó con la marca del agente.
            activity = (
                db.query(Activity)
                .filter(
                    Activity.lead_id == lead_id,
                    Activity.created_by == "agent:crm_agent",
                    Activity.status == "pending",
                )
                .order_by(Activity.created_at.desc())
                .first()
            )
            assert activity is not None
            activities.append(activity.id)

            # La decisión quedó registrada con el efecto y sin desviación.
            decision = (
                db.query(AgentDecision)
                .filter(
                    AgentDecision.action_type == "agent_proposal:create_follow_up",
                    AgentDecision.target_key == lead_id,
                )
                .first()
            )
            assert decision is not None
            assert decision.deviation is False
            assert (decision.payload or {}).get("applied", {}).get("activity_id") == activity.id
        finally:
            db.close()
    finally:
        _cleanup(
            leads=[lead_id],
            messages=[message_id],
            activities=activities,
            approvals=approvals,
            decisions=decisions,
        )
        _reset_autonomy(["crm_agent"])


def test_auto_execute_social_spam_dismissal(client, auth_headers) -> None:
    spam_id = _seed_spam()
    decisions: list[str] = []
    try:
        _set_autonomy(
            "social_agent",
            mode="autonomous",
            allow_spam_dismissals=True,
        )
        result = _run_round(client, auth_headers).json()
        assert result["auto_executed"] >= 1
        assert any(
            p["target_key"] == spam_id and p["status"] == "approved"
            for p in result["proposals"]
        )
        decisions.extend(d["id"] for d in result["decisions"])

        db = SessionLocal()
        try:
            message = (
                db.query(SocialMessage)
                .filter(SocialMessage.id == spam_id)
                .first()
            )
            assert message is not None
            assert message.status == "dismissed"
            decision = (
                db.query(AgentDecision)
                .filter(
                    AgentDecision.action_type == "agent_proposal:dismiss_message",
                    AgentDecision.target_key == spam_id,
                )
                .first()
            )
            assert decision is not None
            assert decision.deviation is False
        finally:
            db.close()
    finally:
        _cleanup(messages=[spam_id], decisions=decisions)
        _reset_autonomy(["social_agent"])


def test_flags_gate_auto_execution(client, auth_headers) -> None:
    lead_id, message_id = _seed_urgent_lead()
    try:
        # Autónomo pero sin el flag de follow-ups → se difiere al humano.
        _set_autonomy("crm_agent", mode="autonomous", allow_follow_ups=False)
        result = _run_round(client, auth_headers).json()
        assert result["auto_executed"] == 0
        follow_up = next(
            (
                p
                for p in result["proposals"]
                if p["action_type"] == "agent_proposal:create_follow_up"
                and p["target_key"] == lead_id
            ),
            None,
        )
        assert follow_up is not None
        assert follow_up["status"] == "pending"
    finally:
        _cleanup(leads=[lead_id], messages=[message_id])
        _reset_autonomy(["crm_agent"])


def test_allowed_actions_authorize_without_legacy_flags(
    client, auth_headers
) -> None:
    lead_id, message_id = _seed_urgent_lead()
    decisions: list[str] = []
    approvals: list[str] = []
    activities: list[str] = []
    try:
        # allowed_actions basta por sí solo: sin allow_follow_ups=True.
        _set_autonomy(
            "crm_agent",
            mode="autonomous",
            allowed_actions=["agent_proposal:create_follow_up"],
        )
        result = _run_round(client, auth_headers).json()
        assert result["auto_executed"] >= 1
        executed = [p for p in result["proposals"] if p["status"] == "approved"]
        assert any(p["target_key"] == lead_id for p in executed)
        approvals.extend(p["id"] for p in executed)
        decisions.extend(d["id"] for d in result["decisions"])

        db = SessionLocal()
        try:
            activity = (
                db.query(Activity)
                .filter(
                    Activity.lead_id == lead_id,
                    Activity.created_by == "agent:crm_agent",
                    Activity.status == "pending",
                )
                .first()
            )
            assert activity is not None
            activities.append(activity.id)
        finally:
            db.close()
    finally:
        _cleanup(
            leads=[lead_id],
            messages=[message_id],
            activities=activities,
            approvals=approvals,
            decisions=decisions,
        )
        _reset_autonomy(["crm_agent"])


def test_max_actions_per_day_caps_daily_autonomy(client, auth_headers) -> None:
    first = _seed_urgent_lead()
    second = _seed_urgent_lead()
    decisions: list[str] = []
    approvals: list[str] = []
    activities: list[str] = []
    try:
        _set_autonomy(
            "crm_agent",
            mode="autonomous",
            allow_follow_ups=True,
            max_actions_per_day=1,
        )
        result = _run_round(client, auth_headers).json()
        assert result["proposed"] >= 2
        assert result["auto_executed"] == 1
        assert result["deferred"] >= 1
        approvals.extend(
            p["id"] for p in result["proposals"] if p["status"] == "approved"
        )
        decisions.extend(d["id"] for d in result["decisions"])

        db = SessionLocal()
        try:
            activities.extend(
                row.id
                for row in db.query(Activity)
                .filter(
                    Activity.lead_id.in_([first[0], second[0]]),
                    Activity.created_by == "agent:crm_agent",
                    Activity.status == "pending",
                )
                .all()
            )
            assert len(activities) == 1
        finally:
            db.close()
    finally:
        _cleanup(
            leads=[first[0], second[0]],
            messages=[first[1], second[1]],
            activities=activities,
            approvals=approvals,
            decisions=decisions,
        )
        _reset_autonomy(["crm_agent"])


# ---------------------------------------------------------------------------
# Digest diario + revert
# ---------------------------------------------------------------------------

def test_digest_aggregates_and_revert_follow_up(client, auth_headers) -> None:
    lead_id, message_id = _seed_urgent_lead()
    decisions: list[str] = []
    approvals: list[str] = []
    activities: list[str] = []
    try:
        _set_autonomy("crm_agent", mode="autonomous", allow_follow_ups=True)
        result = _run_round(client, auth_headers).json()
        decisions.extend(d["id"] for d in result["decisions"])
        approvals.extend(p["id"] for p in result["proposals"] if p["status"] == "approved")

        digest = client.get("/agents/digest?days=1", headers=auth_headers).json()
        assert digest["total_decisions"] >= 1
        assert digest["window_days"] == 1
        crm = next(a for a in digest["by_agent"] if a["agent_id"] == "crm_agent")
        assert crm["total"] >= 1
        # El digest de la supervisión usa los mismos labels en lenguaje llano
        # que el chat del CEO (T-… 2026-08-19): agente, acción y objetivo
        # humanos, sin nombres técnicos ni UUIDs.
        assert crm["agent_label"] == "el agente de clientes (CRM)"
        decision_row = next(
            d
            for d in digest["decisions"]
            if d["action_type"] == "agent_proposal:create_follow_up"
            and d["target_key"] == lead_id
        )
        assert decision_row["action_label"] == "crear un seguimiento"
        assert decision_row["target_label"] == "Urgencia Autonomía"
        # El objetivo humanizado también expone el tipo y el id enfocable
        # para que el portal lo enlace a la ficha del lead en Clientes.
        assert decision_row["target_kind"] == "lead"
        assert decision_row["target_focus_id"] == lead_id
        decision_id = decision_row["id"]

        db = SessionLocal()
        try:
            activity_id = (
                db.query(AgentDecision)
                .filter(AgentDecision.id == decision_id)
                .first()
            )
            applied = (activity_id.payload or {}).get("applied", {})
            activities.append(applied["activity_id"])
        finally:
            db.close()

        # Revert: la actividad pasa a cancelled y la decisión queda revertida.
        reverted = client.post(
            f"/agents/decisions/{decision_id}/revert", headers=auth_headers
        )
        assert reverted.status_code == 200, reverted.text
        body = reverted.json()
        assert body["reverted_by"] == "admin"

        db = SessionLocal()
        try:
            activity = db.query(Activity).filter(Activity.id == activities[0]).first()
            assert activity is not None
            assert activity.status == "cancelled"
            decision = db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
            assert decision.reverted_at is not None
            assert decision.reverted_by == "admin"
            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.installation_id == "test-installation",
                    AuditLog.event_type == "agent_decision.reverted",
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert (audit.details or {}).get("decision_id") == decision_id
        finally:
            db.close()

        # Doble revert → 409.
        again = client.post(
            f"/agents/decisions/{decision_id}/revert", headers=auth_headers
        )
        assert again.status_code == 409
        # Decisión inexistente → 404.
        missing = client.post(
            f"/agents/decisions/{_unique('ghost')}/revert", headers=auth_headers
        )
        assert missing.status_code == 404
    finally:
        _cleanup(
            leads=[lead_id],
            messages=[message_id],
            activities=activities,
            approvals=approvals,
            decisions=decisions,
        )
        _reset_autonomy(["crm_agent"])


def test_revert_spam_restores_triaged(client, auth_headers) -> None:
    spam_id = _seed_spam()
    decisions: list[str] = []
    try:
        _set_autonomy("social_agent", mode="autonomous", allow_spam_dismissals=True)
        result = _run_round(client, auth_headers).json()
        decision_id = next(
            d["id"]
            for d in result["decisions"]
            if d["action_type"] == "agent_proposal:dismiss_message"
            and d["target_key"] == spam_id
        )
        decisions.append(decision_id)

        reverted = client.post(
            f"/agents/decisions/{decision_id}/revert", headers=auth_headers
        )
        assert reverted.status_code == 200
        db = SessionLocal()
        try:
            message = db.query(SocialMessage).filter(SocialMessage.id == spam_id).first()
            assert message is not None
            assert message.status == "triaged"
        finally:
            db.close()
    finally:
        _cleanup(messages=[spam_id], decisions=decisions)
        _reset_autonomy(["social_agent"])


# ---------------------------------------------------------------------------
# CEO chat: autonomía en la acción del dueño
# ---------------------------------------------------------------------------

def _seed_cold_lead(old: bool = True) -> str:
    db = SessionLocal()
    lead_id = _unique("aut-cold")
    try:
        db.add(
            Lead(
                id=lead_id,
                email=f"{_unique('autcold')}@example.com",
                first_name="Frío Autonomía",
                source="web",
                status="new",
                created_at=(
                    datetime.datetime(2020, 1, 1, 0, 0, 0) if old else None
                ),
            )
        )
        db.commit()
    finally:
        db.close()
    return lead_id


def test_ceo_chat_auto_executes_within_autonomy(client, auth_headers) -> None:
    lead_ids = [_seed_cold_lead(), _seed_cold_lead()]
    approvals: list[str] = []
    decisions: list[str] = []
    activities: list[str] = []
    try:
        _set_autonomy("ceo_agent", mode="autonomous", allow_follow_ups=True)
        token = auth_headers["Authorization"].split()[-1]
        response = client.post(
            "/ceo/chat",
            json={
                "message": "haz follow-up a los leads fríos",
                "conversation_id": _unique("aut-ceo-conv"),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["intent"] == "follow_up_cold_leads"
        assert body["proposals"], "debería haber propuestas creadas"
        executed = [p for p in body["proposals"] if p["status"] == "approved"]
        assert len(executed) >= 1, "la autonomía debería auto-ejecutar"
        assert all(p["decision_id"] for p in executed)
        assert "ejecutadas" in body["answer"] or "autonomía" in body["answer"]
        approvals.extend(p["id"] for p in body["proposals"])
        decisions.extend(p["decision_id"] for p in executed)

        db = SessionLocal()
        try:
            activities.extend(
                row.id
                for row in db.query(Activity)
                .filter(
                    Activity.lead_id.in_(lead_ids),
                    Activity.created_by == "agent:ceo_agent",
                    Activity.status == "pending",
                )
                .all()
            )
            assert len(activities) >= 1
        finally:
            db.close()
    finally:
        _cleanup(
            leads=lead_ids,
            activities=activities,
            approvals=approvals,
            decisions=decisions,
        )
        _reset_autonomy(["ceo_agent"])


def test_agents_round_task_seeded_and_dispatched(client, auth_headers) -> None:
    """La ronda periódica de agentes es una tarea del catálogo que el
    scheduler puede ejecutar: ensure crea la tarea activa (dedupe por tipo)
    y el dispatch ``agents_round`` devuelve el resultado de la ronda."""

    from app.services.automations import (
        ensure_agents_round_task,
        run_scheduled_task,
    )

    db = SessionLocal()
    try:
        info = ensure_agents_round_task(db)
        assert info["status"] == "active"
        task = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.task_type == "agents_round")
            .first()
        )
        assert task is not None
        assert task.interval_seconds == 3_600
        assert task.name == "Ronda de propuestas de agentes"

        result = run_scheduled_task(
            db,
            task_type="agents_round",
            payload={},
            actor="test",
        )
        assert set(result) >= {"proposed", "auto_executed", "deferred"}
    finally:
        db.close()

    # Hermeticidad: no dejamos la tarea sembrada para otros módulos.
    db = SessionLocal()
    try:
        db.query(ScheduledTask).filter(
            ScheduledTask.task_type == "agents_round"
        ).delete()
        db.commit()
    finally:
        db.close()
