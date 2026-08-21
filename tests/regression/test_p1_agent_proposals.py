"""Evals T-058: propuestas de agentes por módulo con aprobación humana.

Cubre la Fase 2 de los agentes especializados (directriz del cliente): los
agentes **proponen**, nunca ejecutan sin aprobación.

- ``crm_agent`` propone follow-ups para leads sociales urgentes (queja/lead
  con urgencia >= 40) cuya actividad de seguimiento falta o está vencida.
- ``social_agent`` propone descartar mensajes triados como spam.
- Cada propuesta es un ``ApprovalRequest`` pendiente visible en
  ``GET /approvals``; un re-run no duplica (pendiente o aprobada no se
  re-propone); un lead con follow-up pendiente no vencido se omite.
- Aprobar aplica el efecto en la misma transacción (crear la actividad con
  ``created_by=agent:<id>`` / marcar ``dismissed``) y audita
  ``agent_proposal.executed``; aprobar dos veces → 409; rechazar no ejecuta.
- RBAC: la ronda de propuestas y las decisiones son de admin.

Hermeticidad D-032: SQLite de test, seeds por ORM con ids únicos y limpieza
en ``finally``.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    Activity,
    ApprovalRequest,
    AuditLog,
    Lead,
    SocialMessage,
    SocialTriage,
    User,
)

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_user(client, auth_headers, username: str, role: str) -> None:
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": PORTAL_TEST_PASSWORD,
            "role": role,
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text


def _login(client, username: str) -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def proposal_env(client, auth_headers):
    commercial = _unique("comercial-prop")
    viewer = _unique("viewer-prop")
    admin = _unique("admin-prop")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    _create_user(client, auth_headers, admin, "client_admin")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "admin_token": _login(client, admin),
        "commercial_token": _login(client, commercial),
        "viewer_token": _login(client, viewer),
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(
                User.username.in_([commercial, viewer, admin])
            ).delete()
            db.commit()
        finally:
            db.close()


def _seed_urgent_social_lead(*, with_overdue: bool, message_intent: str = "queja"):
    """Lead social con mensaje urgente triado (+ actividad vencida opcional)."""
    db = SessionLocal()
    lead_id = f"lead-{uuid.uuid4().hex[:12]}"
    message_id = f"msg-{uuid.uuid4().hex[:12]}"
    activity_id = None
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    try:
        db.add(
            Lead(
                id=lead_id,
                email=f"{_unique('prop')}@example.com",
                first_name="Lead SLA",
                source="social",
                status="new",
            )
        )
        db.add(
            SocialMessage(
                id=message_id,
                channel_id="ch-prop",
                source_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
                body="Esto es urgente, por favor",
                sender_name="Cliente SLA",
                status="triaged",
                lead_id=lead_id,
            )
        )
        db.flush()
        db.add(
            SocialTriage(
                message_id=message_id,
                intent=message_intent,
                language="es",
                register="formal",
                urgency=70,
                score_social=60,
                summary="Urgente",
                decided_by="deterministic",
            )
        )
        if with_overdue:
            activity_id = f"act-{uuid.uuid4().hex[:12]}"
            db.add(
                Activity(
                    id=activity_id,
                    lead_id=lead_id,
                    title="Follow-up vencido",
                    kind="follow_up",
                    due_at=now - datetime.timedelta(days=2),
                    status="pending",
                    created_by="comercial",
                )
            )
        db.commit()
    finally:
        db.close()
    return lead_id, message_id, activity_id


def _seed_spam_message():
    db = SessionLocal()
    message_id = f"msg-{uuid.uuid4().hex[:12]}"
    try:
        db.add(
            SocialMessage(
                id=message_id,
                channel_id="ch-prop",
                source_message_id=f"spam.{uuid.uuid4().hex[:8]}",
                body="GANA un premio gratis!! pincha aquí",
                sender_handle="spammer",
                status="triaged",
            )
        )
        db.flush()
        db.add(
            SocialTriage(
                message_id=message_id,
                intent="spam",
                language="es",
                register="neutral",
                urgency=0,
                score_social=0,
                summary="Spam",
                decided_by="deterministic",
            )
        )
        db.commit()
    finally:
        db.close()
    return message_id


def _run_proposals(client, token):
    return client.post("/agent-proposals/run", headers=_auth(token))


def _cleanup(lead_ids, message_ids, activity_ids, approval_ids):
    db = SessionLocal()
    try:
        if approval_ids:
            db.query(ApprovalRequest).filter(
                ApprovalRequest.id.in_(approval_ids)
            ).delete()
        if message_ids:
            db.query(SocialTriage).filter(
                SocialTriage.message_id.in_(message_ids)
            ).delete(synchronize_session=False)
            db.query(SocialMessage).filter(
                SocialMessage.id.in_(message_ids)
            ).delete(synchronize_session=False)
        if activity_ids:
            db.query(Activity).filter(
                Activity.id.in_(activity_ids)
            ).delete(synchronize_session=False)
        if lead_ids:
            db.query(Lead).filter(Lead.id.in_(lead_ids)).delete(
                synchronize_session=False
            )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# crm_agent: propuestas de follow-up
# ---------------------------------------------------------------------------


def test_crm_agent_proposes_follow_up_for_overdue_social_lead(proposal_env):
    client = proposal_env["client"]
    lead_id, message_id, activity_id = _seed_urgent_social_lead(with_overdue=True)
    try:
        response = _run_proposals(client, proposal_env["admin_token"])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["by_agent"]["crm_agent"] == 1
        proposal = result["proposals"][0]
        assert proposal["requested_by"] == "crm_agent"
        assert "queja" in proposal["rationale"]
        assert "venció" in proposal["rationale"]

        # Dedupe: un re-run no propone lo ya propuesto.
        second = _run_proposals(client, proposal_env["admin_token"])
        assert second.json()["proposed"] == 0
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "crm_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([lead_id], [message_id], [activity_id or None], proposal_ids)


def test_crm_agent_skips_lead_with_active_follow_up(proposal_env):
    client = proposal_env["client"]
    lead_id, message_id, activity_id = _seed_urgent_social_lead(with_overdue=False)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    # Añadimos un follow-up pendiente con vencimiento futuro: el humano ya
    # está encima, el agente no propone.
    db = SessionLocal()
    future_activity = f"act-{uuid.uuid4().hex[:12]}"
    try:
        db.add(
            Activity(
                id=future_activity,
                lead_id=lead_id,
                title="Follow-up en curso",
                kind="follow_up",
                due_at=now + datetime.timedelta(hours=6),
                status="pending",
                created_by="comercial",
            )
        )
        db.commit()
    finally:
        db.close()
    try:
        response = _run_proposals(client, proposal_env["admin_token"])
        assert response.json()["by_agent"]["crm_agent"] == 0
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "crm_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([lead_id], [message_id], [activity_id or None, future_activity], proposal_ids)


def test_social_agent_proposes_spam_dismissal(proposal_env):
    client = proposal_env["client"]
    message_id = _seed_spam_message()
    try:
        response = _run_proposals(client, proposal_env["admin_token"])
        assert response.status_code == 200
        assert response.json()["by_agent"]["social_agent"] == 1
        second = _run_proposals(client, proposal_env["admin_token"])
        assert second.json()["proposed"] == 0
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "social_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([], [message_id], [], proposal_ids)


def test_proposals_surface_in_approvals_endpoint(proposal_env):
    client = proposal_env["client"]
    message_id = _seed_spam_message()
    try:
        _run_proposals(client, proposal_env["admin_token"])
        listed = client.get(
            "/approvals?status_filter=pending",
            headers=_auth(proposal_env["commercial_token"]),
        )
        assert listed.status_code == 200
        items = listed.json()
        dismiss = next(
            (
                item
                for item in items
                if item["action_type"] == "agent_proposal:dismiss_message"
                and item["requested_by"] == "social_agent"
            ),
            None,
        )
        assert dismiss is not None
        # El panel del portal no debe mostrar identificadores internos: el
        # backend entrega labels en lenguaje llano junto a la clave cruda.
        assert dismiss["action_label"] == "descartar un mensaje social"
        assert dismiss["target_label"] == "spammer"
        assert dismiss["target_key"] == message_id
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "social_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([], [message_id], [], proposal_ids)


# ---------------------------------------------------------------------------
# Decisión humana: aprobar aplica, rechazar no
# ---------------------------------------------------------------------------


def test_approve_follow_up_creates_activity_and_audits(proposal_env):
    client = proposal_env["client"]
    lead_id, message_id, activity_id = _seed_urgent_social_lead(with_overdue=True)
    try:
        run = _run_proposals(client, proposal_env["admin_token"]).json()
        proposal_id = run["proposals"][0]["id"]
        approved = client.post(
            f"/approvals/{proposal_id}/approve",
            json={},
            headers=_auth(proposal_env["admin_token"]),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["applied"]["action"] == "create_follow_up"
        # La actividad se creó con la marca del agente.
        db = SessionLocal()
        try:
            activity = (
                db.query(Activity)
                .filter(
                    Activity.lead_id == lead_id,
                    Activity.created_by == "agent:crm_agent",
                )
                .first()
            )
            assert activity is not None
            assert activity.title == "Follow-up urgente (SLA social)"
            assert activity.status == "pending"
            approval = db.query(ApprovalRequest).filter(
                ApprovalRequest.id == proposal_id
            ).first()
            assert approval.status == "approved"
            assert approval.reviewed_by is not None
            executed = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "agent_proposal.executed")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert executed is not None
            assert executed.agent_id == "crm_agent"
            assert executed.details.get("approval_id") == proposal_id
            activity_id_created = activity.id
        finally:
            db.close()
        # Aprobar dos veces → 409.
        again = client.post(
            f"/approvals/{proposal_id}/approve",
            json={},
            headers=_auth(proposal_env["admin_token"]),
        )
        assert again.status_code == 409
        assert activity_id_created
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "crm_agent")
                .all()
            ]
            created = [
                row.id
                for row in db.query(Activity)
                .filter(Activity.created_by == "agent:crm_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([lead_id], [message_id], [activity_id or None, *created], proposal_ids)


def test_approve_dismiss_marks_message_dismissed(proposal_env):
    client = proposal_env["client"]
    message_id = _seed_spam_message()
    try:
        run = _run_proposals(client, proposal_env["admin_token"]).json()
        proposal_id = run["proposals"][0]["id"]
        approved = client.post(
            f"/approvals/{proposal_id}/approve",
            json={},
            headers=_auth(proposal_env["admin_token"]),
        )
        assert approved.status_code == 200
        assert approved.json()["applied"]["action"] == "dismiss_message"
        db = SessionLocal()
        try:
            message = db.query(SocialMessage).filter(
                SocialMessage.id == message_id
            ).first()
            assert message.status == "dismissed"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "social_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([], [message_id], [], proposal_ids)


def test_reject_proposal_does_not_execute(proposal_env):
    client = proposal_env["client"]
    lead_id, message_id, activity_id = _seed_urgent_social_lead(with_overdue=True)
    try:
        run = _run_proposals(client, proposal_env["admin_token"]).json()
        proposal_id = run["proposals"][0]["id"]
        rejected = client.post(
            f"/approvals/{proposal_id}/reject",
            json={"rejection_reason": "El comercial ya contactó por teléfono"},
            headers=_auth(proposal_env["admin_token"]),
        )
        assert rejected.status_code == 200, rejected.text
        db = SessionLocal()
        try:
            approval = db.query(ApprovalRequest).filter(
                ApprovalRequest.id == proposal_id
            ).first()
            assert approval.status == "rejected"
            assert "teléfono" in (approval.rejection_reason or "")
            # Nada se ejecutó.
            activity = (
                db.query(Activity)
                .filter(Activity.created_by == "agent:crm_agent")
                .first()
            )
            assert activity is None
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            proposal_ids = [
                row.id
                for row in db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "crm_agent")
                .all()
            ]
        finally:
            db.close()
        _cleanup([lead_id], [message_id], [activity_id or None], proposal_ids)


def test_run_requires_admin_role(proposal_env):
    client = proposal_env["client"]
    assert (
        _run_proposals(client, proposal_env["viewer_token"]).status_code == 403
    )
    assert (
        _run_proposals(client, proposal_env["commercial_token"]).status_code == 403
    )
