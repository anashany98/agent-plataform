"""Evals T-074: digest diario por email con opción de revertir desde el correo.

El dueño recibe cada día un resumen de decisiones de agentes (T-068),
propuestas pendientes y métricas clave, y puede anular una decisión
respondiendo «REVERTIR <id>» al propio correo (mando del dueño, T-069).

- ``POST /digest/send`` (dry_run) construye el digest sin enviar.
- Con dueño configurado envía por el spool/SMTP con degradación auditada.
- El correo incluye la instrucción REVERTIR <id> por decisión no revertida.
- El webhook de email revierte la decisión con trazabilidad (nunca borra
  evidencia) y responde la confirmación por el spool.
- Sin dueño configurado → skipped auditado. RBAC: viewer → 403.

Hermeticidad D-032: SQLite de test, sin red (spool local), HMAC local y
limpieza en ``finally``; la configuración del dueño se inyecta con
``monkeypatch`` sobre ``settings`` (se restaura sola).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.models import (
    Activity,
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    Lead,
    ScheduledTask,
)

OWNER_EMAIL = "dueno@miempresa.com"
PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _seed_decision(
    db,
    *,
    action_type: str = "agent_proposal:create_follow_up",
    target_key: str | None = None,
    activity_id: str | None = None,
    executed_at: datetime.datetime | None = None,
    deviation: bool = False,
) -> AgentDecision:
    decision = AgentDecision(
        id=_unique("digest-dec"),
        agent_id="crm_agent",
        action_type=action_type,
        target_key=target_key or _unique("lead"),
        executed_at=executed_at or (_now() - datetime.timedelta(hours=3)),
        executed_by="crm_agent",
        payload={
            "summary": "Follow-up automático sobre un lead frío",
            "applied": {"activity_id": activity_id} if activity_id else {},
        },
        deviation=deviation,
    )
    db.add(decision)
    db.flush()
    return decision


def _seed_activity(db) -> Activity:
    activity = Activity(
        id=_unique("act"),
        lead_id=None,
        title="Follow-up del agente CRM",
        kind="follow_up",
        description="Generada por el agente de forma autónoma",
        due_at=_now() + datetime.timedelta(hours=24),
        status="pending",
        created_by="crm_agent",
    )
    db.add(activity)
    db.flush()
    return activity


def _seed_lead(db) -> Lead:
    lead = Lead(
        id=_unique("digest-lead"),
        email=f"{_unique('digest-lead')}@example.invalid",
        first_name="María Digest",
        status="new",
    )
    db.add(lead)
    db.flush()
    return lead


def _seed_pending_proposal(db) -> ApprovalRequest:
    proposal = ApprovalRequest(
        id=_unique("appr"),
        action_type="issue_invoice",
        target_key=_unique("inv"),
        payload={
            "rationale": "Factura pendiente de aprobación",
            "invoice_number": "INV-2026-0042",
        },
        requested_by="finance_agent",
        status="pending",
        # La más antigua: el digest muestra las 8 primeras por antigüedad y
        # el corpus deja propuestas pendientes de otros tests.
        created_at=_now() - datetime.timedelta(days=30),
    )
    db.add(proposal)
    db.flush()
    return proposal


def _email_signature(raw: bytes, secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed = f"{timestamp}.{raw.decode('utf-8')}"
    return {
        "X-Command-Timestamp": timestamp,
        "X-Command-Signature": (
            f"sha256={hmac.new(secret.encode('utf-8'), signed.encode('utf-8'), hashlib.sha256).hexdigest()}"
        ),
    }


def _email_webhook(client, *, sender: str, subject: str, text: str, secret: str):
    payload = {"from": sender, "subject": subject, "text": text}
    raw = json.dumps(payload).encode("utf-8")
    return client.post(
        "/commands/email/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            **_email_signature(raw, secret),
        },
    )


def _cleanup(
    decision_ids: list[str],
    activity_ids: list[str],
    proposal_ids: list[str],
    lead_ids: list[str] | None = None,
) -> None:
    db = SessionLocal()
    try:
        if decision_ids:
            db.query(AgentDecision).filter(AgentDecision.id.in_(decision_ids)).delete()
        if activity_ids:
            db.query(Activity).filter(Activity.id.in_(activity_ids)).delete()
        if proposal_ids:
            db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(proposal_ids)).delete()
        if lead_ids:
            db.query(Lead).filter(Lead.id.in_(lead_ids)).delete()
        db.query(ScheduledTask).filter(ScheduledTask.task_type == "daily_digest").delete()
        db.commit()
    finally:
        db.close()


def test_digest_dry_run_builds_real_content(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    lead_ids: list[str] = []
    try:
        activity = _seed_activity(db)
        activity_ids.append(activity.id)
        lead = _seed_lead(db)
        lead_ids.append(lead.id)
        decision = _seed_decision(db, activity_id=activity.id, target_key=str(lead.id))
        decision_ids.append(decision.id)
        proposal = _seed_pending_proposal(db)
        proposal_ids.append(proposal.id)
        decision_id = str(decision.id)
        lead_id = str(lead.id)
        proposal_id = str(proposal.id)
        proposal_key = str(proposal.target_key)
        db.commit()
    finally:
        db.close()
    try:
        response = client.post(
            "/digest/send?dry_run=true",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "dry_run"
        assert data["to"] == OWNER_EMAIL
        assert "Resumen diario" in data["subject"]
        body = data["body"]
        # Secciones completas con datos reales sembrados.
        assert "DECISIONES DE LOS AGENTES" in body
        assert "PROPUESTAS PENDIENTES" in body
        assert "MÉTRICAS CLAVE" in body
        assert decision_id in body
        assert "REVERTIR " + decision_id in body
        # Lenguaje llano (igual que el chat del CEO): el lead por su nombre,
        # la factura por su número — nunca el id técnico.
        assert "María Digest" in body
        assert lead_id not in body
        assert "INV-2026-0042" in body
        assert proposal_key not in body
        # El email indica en qué módulo vive cada objetivo (sin URL base no
        # puede haber enlace real, pero la pista guía al dueño).
        assert " (en Clientes)" in body
        assert " (en Ventas)" in body
        digest = data["digest"]
        assert digest["decisions_total"] >= 1
        assert digest["pending_total"] >= 1
        assert "open_count" in digest["metrics"]["sales"]
        # El contrato del digest incluye el tipo y el id enfocable para que
        # el portal enlace el objetivo a su ficha en el módulo.
        seeded_decision = next(
            d for d in digest["decisions"] if d["id"] == decision_id
        )
        assert seeded_decision["target_kind"] == "lead"
        assert seeded_decision["target_focus_id"] == lead_id
        seeded_proposal = next(
            p for p in digest["pending"] if p["id"] == proposal_id
        )
        assert seeded_proposal["target_kind"] == "invoice"
    finally:
        _cleanup(decision_ids, activity_ids, proposal_ids, lead_ids)


def test_digest_sends_to_owner_via_spool_and_audits(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    try:
        activity = _seed_activity(db)
        activity_ids.append(activity.id)
        decision = _seed_decision(db, activity_id=activity.id)
        decision_ids.append(decision.id)
        proposal = _seed_pending_proposal(db)
        proposal_ids.append(proposal.id)
        db.commit()
    finally:
        db.close()
    try:
        response = client.post("/digest/send", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] in ("sent", "degraded_to_spool")
        assert data["to"] == OWNER_EMAIL
        # Spool local: entregado a la cola de entrega manual (nunca afirma
        # entrega real) con su referencia y degradación auditada.
        assert data["reference"]

        db = SessionLocal()
        try:
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "daily_digest.sent")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert (audit.details or {})["to"] == OWNER_EMAIL
            assert (audit.details or {})["reference"] == data["reference"]
        finally:
            db.close()
    finally:
        _cleanup(decision_ids, activity_ids, proposal_ids)


def test_revert_decision_from_email_webhook(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", "cmd-secret-digest")
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    try:
        activity = _seed_activity(db)
        activity_ids.append(activity.id)
        decision = _seed_decision(db, activity_id=activity.id)
        decision_ids.append(decision.id)
        db.commit()
        decision_id = decision.id
    finally:
        db.close()
    try:
        response = _email_webhook(
            client,
            sender=OWNER_EMAIL,
            subject=f"REVERTIR {decision_id}",
            text="",
            secret="cmd-secret-digest",
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["handled"] is True
        assert data["intent"] == "revert_decision"
        assert data["revert_status"] == "reverted"
        assert data["reply_ref"]

        db = SessionLocal()
        try:
            decision = db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
            assert decision is not None
            assert decision.reverted_at is not None
            assert decision.reverted_by == OWNER_EMAIL
            # La evidencia no se borra: la actividad quedó cancelada.
            activity = db.query(Activity).filter(Activity.id == activity_ids[0]).first()
            assert activity is not None
            assert activity.status == "cancelled"
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "ceo_command.email.revert")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert (audit.details or {}).get("decision_id") == decision_id
        finally:
            db.close()
    finally:
        _cleanup(decision_ids, activity_ids, proposal_ids)


def test_revert_unknown_or_already_reverted_explains(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", "cmd-secret-digest-2")
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    try:
        activity = _seed_activity(db)
        activity_ids.append(activity.id)
        decision = _seed_decision(db, activity_id=activity.id)
        decision_ids.append(decision.id)
        db.commit()
        decision_id = decision.id
    finally:
        db.close()
    try:
        # Id inexistente → explicación en la respuesta, sin error.
        response = _email_webhook(
            client,
            sender=OWNER_EMAIL,
            subject="REVERTIR no-existe-12345",
            text="",
            secret="cmd-secret-digest-2",
        )
        assert response.status_code == 200, response.text
        assert response.json()["revert_status"] == "not_found"
        assert "No encontré" in response.json()["reply_ref"] or response.json()["handled"]

        # Revertir dos veces: la segunda responde que ya estaba revertida.
        _email_webhook(
            client,
            sender=OWNER_EMAIL,
            subject=f"REVERTIR {decision_id}",
            text="",
            secret="cmd-secret-digest-2",
        )
        second = _email_webhook(
            client,
            sender=OWNER_EMAIL,
            subject=f"REVERTIR {decision_id}",
            text="",
            secret="cmd-secret-digest-2",
        )
        assert second.status_code == 200, second.text
        assert second.json()["revert_status"] == "already_reverted"
    finally:
        _cleanup(decision_ids, activity_ids, proposal_ids)


def test_digest_skipped_without_owner(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", "")
    response = client.post("/digest/send", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "skipped"
    assert data["reason"] == "no_owner_email"
    db = SessionLocal()
    try:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "daily_digest.skipped")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert audit is not None
        assert (audit.details or {}).get("reason") == "no_owner_email"
    finally:
        db.close()


def test_daily_digest_task_seeded_and_dispatched(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    db = SessionLocal()
    decision_ids: list[str] = []
    activity_ids: list[str] = []
    proposal_ids: list[str] = []
    try:
        activity = _seed_activity(db)
        activity_ids.append(activity.id)
        decision = _seed_decision(db, activity_id=activity.id)
        decision_ids.append(decision.id)
        db.commit()
    finally:
        db.close()
    try:
        response = client.post("/digest/send?dry_run=true", headers=auth_headers)
        assert response.status_code == 200, response.text

        db = SessionLocal()
        try:
            task = (
                db.query(ScheduledTask)
                .filter(ScheduledTask.task_type == "daily_digest")
                .first()
            )
            assert task is not None
            assert task.status == "active"
            assert task.interval_seconds == 86_400
            assert task.name == "Digest diario al dueño"

            # Dispatch real del catálogo de tareas (el scheduler lo ejecuta).
            from app.services.automations import run_scheduled_task

            result = run_scheduled_task(db, task_type="daily_digest", payload={}, actor="test")
            assert result["status"] in ("sent", "degraded_to_spool")
            assert result["to"] == OWNER_EMAIL
        finally:
            db.close()
    finally:
        _cleanup(decision_ids, activity_ids, proposal_ids)


def test_digest_rbac_viewer_forbidden(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    username = _unique("viewer-digest")
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
    try:
        login = client.post(
            "/auth/login",
            json={"username": username, "password": PORTAL_TEST_PASSWORD},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        response = client.post(
            "/digest/send",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text
    finally:
        db = SessionLocal()
        try:
            from app.models.models import User

            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()
