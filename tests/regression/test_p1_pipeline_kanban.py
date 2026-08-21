"""Evals P1-a: kanban de pipeline comercial.

Cubre T-042 (plan de producto CRM) — módulo P1-a:

- ``GET /pipeline/stages`` siembra las etapas por defecto (keys estables y
  orden) y ``PUT /pipeline/stages`` las reconfigura (solo admin, auditado);
  las oportunidades de etapas eliminadas se reasignan a la primera etapa.
- ``GET /pipeline/board`` agrupa las oportunidades por etapa y expone la
  cola de leads sin asignar (``assigned_to`` vacío) con los usuarios
  disponibles para asignar.
- ``PATCH /opportunities/{id}`` mueve de etapa (drag&drop) con auditoría
  ``pipeline.stage_changed`` y valida la etapa contra el pipeline.
- ``PATCH /leads/{id}/assign`` asigna/desasigna un comercial con auditoría
  ``lead.assigned``.
- RBAC: viewer 403 en board/asignación; solo admin reconfigura etapas.

Hermeticidad D-032: la app es single-tenant por instancia (el ORM inyecta
``installation_id`` por contexto, deny-by-default), así que los tests corren
bajo la instalación de prueba por defecto; los usuarios y filas de cada test
se crean y limpian con ids únicos.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.models.models import Activity, AuditLog, Lead, Opportunity, User

PORTAL_TEST_PASSWORD = "Portal-Test-123!"
DEFAULT_KEYS = ["new", "qualified", "quote", "negotiation", "won", "lost"]
DEFAULT_NAMES = ["Nuevo", "Calificado", "Presupuesto", "Negociación", "Ganado", "Perdido"]


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


def _login(client, username: str) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_lead_opportunity(
    *,
    stage: str = "new",
    assigned_to: str | None = None,
    name: str = "Presupuesto Kanban",
) -> tuple[str, str]:
    """Siembra un lead (opcionalmente sin asignar) con una oportunidad."""
    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Kanban",
            company_name="Kanban Corp",
            source="local",
            status="new",
            assigned_to=assigned_to,
        )
        db.add(lead)
        db.flush()
        opportunity = Opportunity(
            id=f"opp-{uuid.uuid4().hex[:8]}",
            lead_id=lead.id,
            external_reference=f"quote-{uuid.uuid4().hex[:6]}",
            name=name,
            monetary_value=Decimal("250.00"),
            currency="EUR",
            pipeline="default",
            stage=stage,
            status="open",
        )
        db.add(opportunity)
        db.commit()
        return lead.id, opportunity.id
    finally:
        db.close()


def _cleanup_lead_opportunity(lead_id: str, opportunity_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Opportunity).filter(Opportunity.id == opportunity_id).delete()
        db.query(Lead).filter(Lead.id == lead_id).delete()
        db.commit()
    finally:
        db.close()


def _audit_events(event_type: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == event_type)
            .order_by(AuditLog.timestamp.desc())
            .all()
        )
        return [row.details or {} for row in rows]
    finally:
        db.close()


@pytest.fixture()
def pipeline_env(client, auth_headers):
    """Crea un comercial y un viewer de prueba y los limpia al terminar."""
    commercial = _unique("comercial")
    viewer = _unique("viewer")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "commercial_token": _login(client, commercial)["access_token"],
        "viewer_token": _login(client, viewer)["access_token"],
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username.in_([commercial, viewer])).delete()
            db.commit()
        finally:
            db.close()


def _commercial_id() -> str:
    db = SessionLocal()
    try:
        row = (
            db.query(User)
            .filter(User.role == "commercial")
            .order_by(User.username.asc())
            .first()
        )
        assert row is not None
        return row.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Etapas: siembra por defecto y configuración (admin, auditada)
# ---------------------------------------------------------------------------


def test_pipeline_stages_seed_defaults(pipeline_env) -> None:
    """GET /pipeline/stages siembra las 6 etapas por defecto en orden."""
    client = pipeline_env["client"]
    response = client.get("/pipeline/stages", headers=_auth(pipeline_env["commercial_token"]))
    assert response.status_code == 200, response.text
    stages = response.json()
    assert [stage["key"] for stage in stages] == DEFAULT_KEYS
    assert [stage["position"] for stage in stages] == list(range(len(stages)))
    # La siembra es idempotente: una segunda llamada no duplica.
    second = client.get("/pipeline/stages", headers=_auth(pipeline_env["commercial_token"]))
    assert len(second.json()) == len(stages)


def test_pipeline_stages_reconfigure_admin_audited(pipeline_env) -> None:
    """PUT reconfigura el pipeline (admin), conserva keys por nombre y
    reasigna las oportunidades de etapas eliminadas a la primera etapa."""
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(stage="negotiation")
    try:
        # Un comercial NO puede reconfigurar etapas.
        denied = client.put(
            "/pipeline/stages",
            json={"names": ["Nuevo", "Cerrado"]},
            headers=_auth(env["commercial_token"]),
        )
        assert denied.status_code == 403, denied.text

        # Admin: elimina "Negociación" (tiene la oportunidad) y añade "Cerrado".
        custom = ["Nuevo", "Calificado", "Presupuesto", "Ganado", "Perdido", "Cerrado"]
        response = client.put(
            "/pipeline/stages",
            json={"names": custom},
            headers=env["auth_headers"],
        )
        assert response.status_code == 200, response.text
        stages = response.json()
        assert [stage["key"] for stage in stages] == [
            "new",
            "qualified",
            "quote",
            "won",
            "lost",
            "cerrado",
        ]
        # La oportunidad huérfana se reasigna a la primera etapa.
        board = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        assert board.status_code == 200, board.text
        first_column = next(s for s in board.json()["stages"] if s["key"] == "new")
        assert any(card["id"] == opp_id for card in first_column["opportunities"])
        # Auditoría: reconfiguración + reasignación.
        updated = _audit_events("pipeline.stages_updated")
        assert updated and updated[0]["after"] == custom
        reassigned = _audit_events("pipeline.stage_reassigned")
        assert reassigned and reassigned[0]["opportunities"] >= 1
        assert reassigned[0]["to"] == "new"
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)
        # Restaura las etapas por defecto para no contaminar otros tests.
        restore = client.put(
            "/pipeline/stages",
            json={"names": DEFAULT_NAMES},
            headers=env["auth_headers"],
        )
        assert restore.status_code == 200, restore.text


# ---------------------------------------------------------------------------
# Tablero: agrupación por etapa + cola de leads sin asignar
# ---------------------------------------------------------------------------


def test_pipeline_board_groups_stages_and_unassigned_queue(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(stage="quote")
    try:
        board = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        assert board.status_code == 200, board.text
        body = board.json()
        assert [stage["key"] for stage in body["stages"]] == DEFAULT_KEYS
        quote_column = next(s for s in body["stages"] if s["key"] == "quote")
        assert any(card["id"] == opp_id for card in quote_column["opportunities"])
        # La cola incluye el lead sin asignar, con su oportunidad embebida.
        assert any(row["id"] == lead_id for row in body["unassigned_leads"])
        queued = next(row for row in body["unassigned_leads"] if row["id"] == lead_id)
        assert any(card["id"] == opp_id for card in queued["opportunities"])
        assert queued["email"].endswith("@example.invalid")
        # El desplegable de asignación trae usuarios activos (sin hashes).
        assert body["users"] and all("username" in u and "id" in u for u in body["users"])
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_pipeline_board_excludes_assigned_leads_from_queue(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    commercial_id = _commercial_id()
    lead_id, opp_id = _seed_lead_opportunity(stage="new", assigned_to=commercial_id)
    try:
        board = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        body = board.json()
        assert not any(row["id"] == lead_id for row in body["unassigned_leads"])
        # El card de la oportunidad muestra el comercial asignado.
        new_column = next(s for s in body["stages"] if s["key"] == "new")
        card = next(c for c in new_column["opportunities"] if c["id"] == opp_id)
        assert card["assigned_to"]
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


# ---------------------------------------------------------------------------
# Cambio de etapa (drag&drop) auditado
# ---------------------------------------------------------------------------


def test_move_opportunity_stage_is_audited(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(stage="new")
    try:
        response = client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "negotiation"},
            headers=_auth(env["commercial_token"]),
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"id": opp_id, "stage": "negotiation", "changed": True}
        board = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        negotiation = next(s for s in board.json()["stages"] if s["key"] == "negotiation")
        assert any(card["id"] == opp_id for card in negotiation["opportunities"])
        events = _audit_events("pipeline.stage_changed")
        assert events and events[0]["opportunity_id"] == opp_id
        assert events[0]["from"] == "new"
        assert events[0]["to"] == "negotiation"
        # Mover a la misma etapa no cambia nada y no repite el efecto.
        same = client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "negotiation"},
            headers=_auth(env["commercial_token"]),
        )
        assert same.json()["changed"] is False
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_move_opportunity_invalid_stage_rejected(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(stage="new")
    try:
        response = client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "no-existe"},
            headers=_auth(env["commercial_token"]),
        )
        assert response.status_code == 422, response.text
        missing = client.patch(
            "/opportunities/opp-inexistente",
            json={"stage": "new"},
            headers=_auth(env["commercial_token"]),
        )
        assert missing.status_code == 404, missing.text
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


# ---------------------------------------------------------------------------
# Asignación de leads (cola sin asignar → comercial)
# ---------------------------------------------------------------------------


def test_assign_and_unassign_lead_is_audited(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(stage="new")
    commercial_id = _commercial_id()
    try:
        assigned = client.patch(
            f"/leads/{lead_id}/assign",
            json={"user_id": commercial_id},
            headers=_auth(env["commercial_token"]),
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assigned_to"] == commercial_id
        # Ya no aparece en la cola.
        board = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        assert not any(row["id"] == lead_id for row in board.json()["unassigned_leads"])
        events = _audit_events("lead.assigned")
        assert events and events[0]["lead_id"] == lead_id
        assert events[0]["to"] == commercial_id
        assert events[0]["from"] is None
        # Desasignación (user_id null) → vuelve a la cola.
        unassigned = client.patch(
            f"/leads/{lead_id}/assign",
            json={"user_id": None},
            headers=_auth(env["commercial_token"]),
        )
        assert unassigned.status_code == 200, unassigned.text
        assert unassigned.json()["assigned_to"] is None
        board2 = client.get("/pipeline/board", headers=_auth(env["commercial_token"]))
        assert any(row["id"] == lead_id for row in board2.json()["unassigned_leads"])
        # Asignar a un usuario inexistente → 422.
        bad = client.patch(
            f"/leads/{lead_id}/assign",
            json={"user_id": "usuario-inexistente"},
            headers=_auth(env["commercial_token"]),
        )
        assert bad.status_code == 422, bad.text
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_pipeline_rbac_viewer_blocked(pipeline_env) -> None:
    env = pipeline_env
    client = env["client"]
    assert (
        client.get("/pipeline/board", headers=_auth(env["viewer_token"])).status_code
        == 403
    )
    assert (
        client.get("/pipeline/stages", headers=_auth(env["viewer_token"])).status_code
        == 403
    )
    lead_id, opp_id = _seed_lead_opportunity(stage="new")
    try:
        assert (
            client.patch(
                f"/leads/{lead_id}/assign",
                json={"user_id": None},
                headers=_auth(env["viewer_token"]),
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/opportunities/{opp_id}",
                json={"stage": "won"},
                headers=_auth(env["viewer_token"]),
            ).status_code
            == 403
        )
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_pipeline_model_has_assignment_and_stage_table() -> None:
    """El modelo expone assigned_to y la tabla de etapas existe (migración 0015)."""
    from sqlalchemy import inspect

    db = SessionLocal()
    try:
        columns = {column["name"] for column in inspect(db.bind).get_columns("leads")}
        assert "assigned_to" in columns
        tables = set(inspect(db.bind).get_table_names())
        assert "pipeline_stages" in tables
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reporting P1-b: funnel, ticket medio, win-rate y aging (T-044)
# ---------------------------------------------------------------------------


def _seed_report_opportunity(
    *,
    stage: str,
    value: str,
    status: str = "open",
    age_days: float = 0.0,
) -> tuple[str, str]:
    """Siembra un lead + oportunidad con antigüedad controlada en la etapa."""
    import datetime as _dt

    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Report",
            company_name="Report Corp",
            source="local",
            status="new",
        )
        db.add(lead)
        db.flush()
        changed = _dt.datetime.now(_dt.UTC).replace(tzinfo=None) - _dt.timedelta(
            days=age_days
        )
        opportunity = Opportunity(
            id=f"opp-{uuid.uuid4().hex[:8]}",
            lead_id=lead.id,
            external_reference=f"quote-{uuid.uuid4().hex[:6]}",
            name=f"Presupuesto {stage} {value}",
            monetary_value=Decimal(value),
            currency="EUR",
            pipeline="default",
            stage=stage,
            status=status,
            stage_changed_at=changed,
        )
        db.add(opportunity)
        db.commit()
        return lead.id, opportunity.id
    finally:
        db.close()


def test_pipeline_report_funnel_ticket_winrate_aging(pipeline_env) -> None:
    """El report calcula funnel por etapa, ticket medio/mediana, win-rate y
    aging (días en la etapa actual vía stage_changed_at)."""
    client = pipeline_env["client"]
    seeded: list[tuple[str, str]] = []
    try:
        # Funnel: new ×2 (100, 300), won ×1 (400), lost ×1 (50).
        seeded.append(_seed_report_opportunity(stage="new", value="100", age_days=3))
        seeded.append(_seed_report_opportunity(stage="new", value="300", age_days=10))
        seeded.append(_seed_report_opportunity(stage="won", value="400"))
        seeded.append(_seed_report_opportunity(stage="lost", value="50"))

        response = client.get(
            "/pipeline/report", headers=_auth(pipeline_env["commercial_token"])
        )
        assert response.status_code == 200, response.text
        report = response.json()

        by_key = {stage["key"]: stage for stage in report["stages"]}
        assert by_key["new"]["count"] == 2
        assert float(by_key["new"]["total_value"]) == 400.0
        assert by_key["new"]["aging_avg_days"] >= 3.0
        assert by_key["new"]["aging_max_days"] >= 10.0

        summary = report["summary"]
        assert summary["total_opportunities"] == 4
        assert summary["avg_ticket"] == 212.5  # (100+300+400+50)/4
        assert summary["median_ticket"] == 200.0  # (100+300)/2
        assert summary["won_count"] == 1
        assert summary["lost_count"] == 1
        assert summary["win_rate_pct"] == 50.0
        assert summary["open_count"] == 2
        assert summary["open_value"] == 400.0
        assert summary["aging_avg_days"] >= (3 + 10) / 4
    finally:
        for lead_id, opp_id in seeded:
            _cleanup_lead_opportunity(lead_id, opp_id)


def test_pipeline_report_moving_stage_resets_aging(pipeline_env) -> None:
    """El PATCH de etapa actualiza stage_changed_at: el aging se resetea al
    mover la oportunidad a otra etapa."""
    client = pipeline_env["client"]
    lead_id, opp_id = _seed_report_opportunity(stage="new", value="250", age_days=9)
    try:
        moved = client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "qualified"},
            headers=_auth(pipeline_env["commercial_token"]),
        )
        assert moved.status_code == 200 and moved.json()["changed"] is True

        report = client.get(
            "/pipeline/report", headers=_auth(pipeline_env["commercial_token"])
        ).json()
        qualified = next(
            stage for stage in report["stages"] if stage["key"] == "qualified"
        )
        # Recién movida: aging ≈ 0 días (no 9).
        assert qualified["aging_avg_days"] < 0.1
        new_column = next(stage for stage in report["stages"] if stage["key"] == "new")
        assert new_column["count"] == 0
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_pipeline_report_rbac_viewer_forbidden(pipeline_env) -> None:
    """Un viewer no puede leer el report (RBAC: operadores+)."""
    client = pipeline_env["client"]
    response = client.get(
        "/pipeline/report", headers=_auth(pipeline_env["viewer_token"])
    )
    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Timeline de interacción (T-044): historial cronológico por lead
# ---------------------------------------------------------------------------


def _seed_timeline_audit(
    *,
    event_type: str,
    details: dict,
    days_ago: float = 0.0,
) -> None:
    """Inserta una fila de auditoría con timestamp controlado."""
    import datetime as _dt

    db = SessionLocal()
    try:
        timestamp = _dt.datetime.now(_dt.UTC).replace(tzinfo=None) - _dt.timedelta(
            days=days_ago
        )
        db.add(
            AuditLog(
                id=f"audit-{uuid.uuid4().hex[:8]}",
                timestamp=timestamp,
                event_type=event_type,
                provider="internal",
                model_name="deterministic",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=0,
                estimated_cost_usd=0,
                status="success",
                details=details,
            )
        )
        db.commit()
    finally:
        db.close()


def test_lead_timeline_merges_lifecycle_stage_note_and_email(pipeline_env) -> None:
    """La timeline fusiona creación, asignación, etapa, nota y email del lead,
    ordenada cronológicamente descendente."""
    import datetime as _dt

    env = pipeline_env
    client = env["client"]
    commercial_id = _commercial_id()
    lead_id, opp_id = _seed_lead_opportunity(name="Presupuesto Timeline")
    try:
        # Asignación (auditada) + cambio de etapa (auditado).
        client.patch(
            f"/leads/{lead_id}/assign",
            json={"user_id": commercial_id},
            headers=_auth(env["commercial_token"]),
        )
        client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "qualified"},
            headers=_auth(env["commercial_token"]),
        )

        # Nota en la oportunidad.
        db = SessionLocal()
        try:
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            opp.notes = [
                {
                    "body": "Cliente pide entrega la próxima semana",
                    "created_at": _dt.datetime.now(_dt.UTC)
                    .replace(tzinfo=None)
                    .isoformat(),
                }
            ]
            db.commit()
        finally:
            db.close()

        # Email enviado correlacionado por hash del email del lead.
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        recipient_hash = hashlib.sha256(
            lead.email.lower().encode("utf-8")
        ).hexdigest()
        _seed_timeline_audit(
            event_type="automation.email_sent",
            details={
                "recipient_sha256": recipient_hash,
                "subject_sha256": hashlib.sha256(
                    b"ASUNTO_PRIVADO_123"
                ).hexdigest(),
                "provider": "smtp",
                "reference": "ref-1",
                "delivery_status": "delivered",
            },
        )

        response = client.get(
            f"/leads/{lead_id}/timeline",
            headers=_auth(env["commercial_token"]),
        )
        assert response.status_code == 200, response.text
        data = response.json()
        kinds = [entry["kind"] for entry in data["timeline"]]
        assert "lead_created" in kinds
        assert "lead_assigned" in kinds
        assert "opportunity_created" in kinds
        assert "stage_changed" in kinds
        assert "note" in kinds
        assert "email_sent" in kinds

        # El asunto NO aparece (privacidad: queda hasheado en auditoría).
        assert "ASUNTO_PRIVADO_123" not in json.dumps(data["timeline"])

        # Orden estrictamente cronológico descendente.
        stamps = [entry["created_at"] for entry in data["timeline"]]
        assert stamps == sorted(stamps, reverse=True)

        stage_entry = next(e for e in data["timeline"] if e["kind"] == "stage_changed")
        assert "Calificado" in stage_entry["detail"]
        assert stage_entry["opportunity_name"] == "Presupuesto Timeline"
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_lead_timeline_quote_and_order_events(pipeline_env) -> None:
    """Presupuesto creado y pedido confirmado aparecen correlacionados por el
    external_reference de la oportunidad (= id del presupuesto)."""
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(name="Presupuesto Venta")
    try:
        db = SessionLocal()
        try:
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            quote_id = opp.external_reference
        finally:
            db.close()
        _seed_timeline_audit(
            event_type="quote_created_api",
            details={"quote_id": quote_id, "created": True},
            days_ago=2,
        )
        _seed_timeline_audit(
            event_type="quote_confirmed",
            details={"quote_id": quote_id, "order_id": "order-123"},
            days_ago=1,
        )

        data = client.get(
            f"/leads/{lead_id}/timeline", headers=_auth(env["commercial_token"])
        ).json()
        kinds = [entry["kind"] for entry in data["timeline"]]
        assert "quote_created" in kinds
        assert "order_created" in kinds
        order_entry = next(
            e for e in data["timeline"] if e["kind"] == "order_created"
        )
        assert "order-123" in order_entry["detail"]
    finally:
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_lead_timeline_email_hash_isolation_and_rbac(pipeline_env) -> None:
    """Emails de OTRO destinatario no se cuelan (aislamiento por hash) y el
    viewer no puede leer la timeline."""
    env = pipeline_env
    client = env["client"]
    lead_id, _opp_id = _seed_lead_opportunity()
    try:
        _seed_timeline_audit(
            event_type="automation.email_sent",
            details={
                "recipient_sha256": hashlib.sha256(
                    b"otro@example.invalid"
                ).hexdigest(),
                "subject_sha256": "x",
                "provider": "smtp",
            },
        )
        data = client.get(
            f"/leads/{lead_id}/timeline", headers=_auth(env["commercial_token"])
        ).json()
        assert all(entry["kind"] != "email_sent" for entry in data["timeline"])

        denied = client.get(
            f"/leads/{lead_id}/timeline", headers=_auth(env["viewer_token"])
        )
        assert denied.status_code == 403, denied.text

        missing = client.get(
            "/leads/lead-no-existe/timeline", headers=_auth(env["commercial_token"])
        )
        assert missing.status_code == 404, missing.text
    finally:
        _cleanup_lead_opportunity(lead_id, _opp_id)


# ---------------------------------------------------------------------------
# Actividades de comercial (T-044): tareas + recordatorios por email
# ---------------------------------------------------------------------------


def _seed_activity(
    *,
    lead_id: str,
    title: str = "Llamada de seguimiento",
    remind_at: str | None = None,
    remind_email: str | None = None,
) -> str:
    """Siembra una actividad directamente (vía ORM) y devuelve su id."""
    db = SessionLocal()
    try:
        activity = Activity(
            lead_id=lead_id,
            title=title,
            kind="call",
            status="pending",
            created_by="test-seed",
            remind_at=(
                datetime.datetime.fromisoformat(remind_at).replace(tzinfo=None)
                if remind_at
                else None
            ),
            remind_email=remind_email,
        )
        db.add(activity)
        db.commit()
        return activity.id
    finally:
        db.close()


def _delete_activity(activity_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Activity).filter(Activity.id == activity_id).delete()
        db.commit()
    finally:
        db.close()


def test_activities_crud_audited(pipeline_env) -> None:
    """Crear, listar, filtrar y completar una actividad queda auditado."""
    env = pipeline_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity(name="Presupuesto Tarea")
    activity_id: str | None = None
    try:
        # Un viewer no puede crear ni listar.
        assert (
            client.get("/activities", headers=_auth(env["viewer_token"])).status_code
            == 403
        )
        assert (
            client.post(
                "/activities",
                json={"title": "x"},
                headers=_auth(env["viewer_token"]),
            ).status_code
            == 403
        )

        created = client.post(
            "/activities",
            json={
                "lead_id": lead_id,
                "opportunity_id": opp_id,
                "title": "Llamada de seguimiento",
                "kind": "call",
                "description": "Recordar oferta del cubo",
                "due_at": "2026-08-20T10:00:00",
                "remind_at": "2026-08-19T09:00:00",
            },
            headers=_auth(env["commercial_token"]),
        )
        assert created.status_code == 200, created.text
        activity_id = created.json()["id"]
        assert created.json()["lead_email"] is not None
        assert created.json()["status"] == "pending"
        assert created.json()["opportunity_name"] == "Presupuesto Tarea"

        # La oportunidad de otro lead → 422.
        other_lead, other_opp = _seed_lead_opportunity()
        try:
            mismatch = client.post(
                "/activities",
                json={"lead_id": lead_id, "opportunity_id": other_opp, "title": "x"},
                headers=_auth(env["commercial_token"]),
            )
            assert mismatch.status_code == 422, mismatch.text
        finally:
            _cleanup_lead_opportunity(other_lead, other_opp)

        # Lead inexistente → 404.
        missing = client.post(
            "/activities",
            json={"lead_id": "lead-no-existe", "title": "x"},
            headers=_auth(env["commercial_token"]),
        )
        assert missing.status_code == 404, missing.text

        # Lista con filtro por lead.
        listing = client.get(
            f"/activities?lead_id={lead_id}",
            headers=_auth(env["commercial_token"]),
        ).json()
        assert any(item["id"] == activity_id for item in listing)

        # Completar → done con completed_at/by, auditado.
        completed = client.patch(
            f"/activities/{activity_id}",
            json={"status": "done"},
            headers=_auth(env["commercial_token"]),
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "done"
        assert completed.json()["completed_at"] is not None

        events = _audit_events("activity.created")
        assert any(d.get("activity_id") == activity_id for d in events)
        updates = _audit_events("activity.updated")
        assert any(d.get("activity_id") == activity_id for d in updates)
    finally:
        if activity_id:
            _delete_activity(activity_id)
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_activity_create_without_lead_returns_none_names(pipeline_env) -> None:
    """Una tarea sin lead vinculado no debe romper la respuesta (regresión None+str)."""
    env = pipeline_env
    client = env["client"]
    activity_id: str | None = None
    try:
        created = client.post(
            "/activities",
            json={"title": "Tarea global", "kind": "other"},
            headers=_auth(env["commercial_token"]),
        )
        assert created.status_code == 200, created.text
        body = created.json()
        activity_id = body["id"]
        assert body["lead_id"] is None
        assert body["lead_name"] is None
        assert body["lead_email"] is None
        assert body["opportunity_id"] is None
        assert body["opportunity_name"] is None

        listing = client.get(
            "/activities",
            headers=_auth(env["commercial_token"]),
        ).json()
        assert any(item["id"] == activity_id for item in listing)
    finally:
        if activity_id:
            _delete_activity(activity_id)


def test_activity_reminder_manual_uses_spool_and_audits(pipeline_env) -> None:
    """POST /activities/{id}/remind envía por el spool (local) y queda auditado."""
    env = pipeline_env
    client = env["client"]
    lead_id, _opp_id = _seed_lead_opportunity()
    activity_id: str | None = None
    try:
        activity_id = _seed_activity(lead_id=lead_id, title="Seguimiento urgente")
        response = client.post(
            f"/activities/{activity_id}/remind",
            headers=_auth(env["commercial_token"]),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["provider"] == "local_spool"
        assert payload["delivery_status"] == "queued_for_manual_delivery"
        assert payload["reminded_at"] is not None

        sent = _audit_events("activity.reminder_sent")
        assert any(d.get("activity_id") == activity_id for d in sent)

        # Recordar de nuevo tras estar pendiente y ya recordada: el endpoint
        # lo permite (reprogramación explícita), y la timeline lo muestra.
        second = client.post(
            f"/activities/{activity_id}/remind",
            headers=_auth(env["commercial_token"]),
        )
        assert second.status_code == 200, second.text

        # Una actividad hecha no se recuerda.
        client.patch(
            f"/activities/{activity_id}",
            json={"status": "done"},
            headers=_auth(env["commercial_token"]),
        )
        refused = client.post(
            f"/activities/{activity_id}/remind",
            headers=_auth(env["commercial_token"]),
        )
        assert refused.status_code == 422, refused.text
    finally:
        if activity_id:
            _delete_activity(activity_id)
        _cleanup_lead_opportunity(lead_id, _opp_id)


def test_activity_reminder_worker_due_and_idempotent(pipeline_env) -> None:
    """El worker procesa solo las vencidas, marca reminded_at (idempotente) y
    audita; sin destinatario resoluble se salta con auditoría."""
    import datetime as _dt

    from app.services.activity_reminder_worker import run_due_activity_reminders

    lead_id, _opp_id = _seed_lead_opportunity()
    now = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    due_id = _seed_activity(
        lead_id=lead_id,
        title="Vencida",
        remind_at=(now - _dt.timedelta(hours=1)).isoformat(),
    )
    future_id = _seed_activity(
        lead_id=lead_id,
        title="Futura",
        remind_at=(now + _dt.timedelta(hours=24)).isoformat(),
    )
    try:
        db = SessionLocal()
        try:
            result = run_due_activity_reminders(
                principal=None, db=db, now=now
            )
        finally:
            db.close()
        assert result["evaluated"] == 1
        assert result["processed"] == 1
        assert result["delivered"] == 1

        db = SessionLocal()
        try:
            due = db.query(Activity).filter(Activity.id == due_id).first()
            future = db.query(Activity).filter(Activity.id == future_id).first()
            assert due.reminded_at is not None
            assert future.reminded_at is None
        finally:
            db.close()

        # Segunda pasada: nada que procesar (idempotente).
        db = SessionLocal()
        try:
            second = run_due_activity_reminders(principal=None, db=db, now=now)
        finally:
            db.close()
        assert second["processed"] == 0

        sent = _audit_events("activity.reminder_sent")
        assert any(d.get("activity_id") == due_id for d in sent)
    finally:
        _delete_activity(due_id)
        _delete_activity(future_id)
        _cleanup_lead_opportunity(lead_id, _opp_id)


def test_activity_reminder_worker_skips_without_recipient(pipeline_env) -> None:
    """Actividad sin lead ni remind_email → skip auditado, no reintento."""
    import datetime as _dt

    from app.services.activity_reminder_worker import run_due_activity_reminders

    db = SessionLocal()
    now = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    orphan_id = _seed_activity(
        lead_id="lead-inexistente",
        title="Sin destinatario",
        remind_at=(now - _dt.timedelta(minutes=5)).isoformat(),
    )
    try:
        result = run_due_activity_reminders(principal=None, db=db, now=now)
        assert result["processed"] == 1
        assert result["skipped"] == 1
        assert result["delivered"] == 0

        skipped = _audit_events("activity.reminder_skipped")
        assert any(d.get("activity_id") == orphan_id for d in skipped)
    finally:
        db.close()
        _delete_activity(orphan_id)


# ---------------------------------------------------------------------------
# Calendario de comercial (P2, T-053): agenda diaria/semanal/mensual sobre
# las actividades existentes (Activity.due_at).
# ---------------------------------------------------------------------------


def _seed_calendar_activity(
    *,
    title: str,
    due_at: str,
    kind: str = "call",
    status: str = "pending",
    assigned_to: str | None = None,
    lead_id: str | None = None,
) -> str:
    """Siembra una actividad con vencimiento controlado (vía ORM)."""
    db = SessionLocal()
    try:
        activity = Activity(
            lead_id=lead_id,
            title=title,
            kind=kind,
            status=status,
            created_by="test-calendar-seed",
            due_at=datetime.datetime.fromisoformat(due_at).replace(tzinfo=None),
            assigned_to=assigned_to,
        )
        db.add(activity)
        db.commit()
        return activity.id
    finally:
        db.close()


def _calendar(client, token: str, start: str, end: str, **params) -> dict:
    resp = client.get(
        "/calendar/agenda",
        params={"start": start, "end": end, **params},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fmt_day(day: datetime.date) -> str:
    return day.isoformat()


def test_calendar_agenda_groups_by_day_with_counts(pipeline_env) -> None:
    """Agrupa por día local con counts y devuelve todos los días del rango."""
    env = pipeline_env
    client = env["client"]
    ids: list[str] = []
    try:
        today = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).date()
        day_a = today + datetime.timedelta(days=5)
        day_b = today + datetime.timedelta(days=6)
        day_before = today + datetime.timedelta(days=4)

        ids.append(
            _seed_calendar_activity(
                title="Llamada mañana", due_at=f"{day_a}T09:00:00"
            )
        )
        ids.append(
            _seed_calendar_activity(
                title="Reunión tarde",
                due_at=f"{day_a}T15:30:00",
                kind="meeting",
            )
        )
        ids.append(
            _seed_calendar_activity(
                title="Follow-up hecho",
                due_at=f"{day_b}T10:00:00",
                status="done",
            )
        )

        agenda = _calendar(
            client,
            env["commercial_token"],
            _fmt_day(day_before),
            _fmt_day(day_b),
        )
        assert [d["date"] for d in agenda["days"]] == [
            _fmt_day(day_before),
            _fmt_day(day_a),
            _fmt_day(day_b),
        ]

        day_a_entry = next(d for d in agenda["days"] if d["date"] == _fmt_day(day_a))
        assert day_a_entry["total"] == 2
        assert day_a_entry["pending"] == 2
        assert day_a_entry["completed"] == 0
        assert {a["title"] for a in day_a_entry["activities"]} == {
            "Llamada mañana",
            "Reunión tarde",
        }

        day_b_entry = next(d for d in agenda["days"] if d["date"] == _fmt_day(day_b))
        assert day_b_entry["total"] == 1
        assert day_b_entry["completed"] == 1

        # Día sin actividades → counts 0 y lista vacía.
        empty_day = next(
            d for d in agenda["days"] if d["date"] == _fmt_day(day_before)
        )
        assert empty_day["total"] == 0
        assert empty_day["activities"] == []

        assert agenda["totals"] == {
            "total": 3,
            "pending": 2,
            "completed": 1,
            "cancelled": 0,
            "overdue": 0,
        }
        assert agenda["range"] == {
            "start": _fmt_day(day_before),
            "end": _fmt_day(day_b),
        }
    finally:
        for aid in ids:
            _delete_activity(aid)


def test_calendar_agenda_overdue_and_filters(pipeline_env) -> None:
    """Cuenta vencidas (pendientes con due_at pasado) y aplica filtros."""
    env = pipeline_env
    client = env["client"]
    ids: list[str] = []
    try:
        today = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).date()
        past = today - datetime.timedelta(days=30)
        future = today + datetime.timedelta(days=2)
        span_end = today + datetime.timedelta(days=10)

        ids.append(
            _seed_calendar_activity(
                title="Vencida",
                due_at=f"{past}T10:00:00",
                assigned_to="comercial-filter",
            )
        )
        ids.append(
            _seed_calendar_activity(
                title="Vencida y hecha",
                due_at=f"{past}T11:00:00",
                status="done",
                assigned_to="comercial-filter",
            )
        )
        ids.append(
            _seed_calendar_activity(
                title="Futura de otro",
                due_at=f"{future}T09:00:00",
                assigned_to="otro-comercial",
            )
        )

        agenda = _calendar(
            client, env["commercial_token"], _fmt_day(past), _fmt_day(span_end)
        )
        assert agenda["totals"]["overdue"] == 1
        assert agenda["totals"]["total"] == 3

        # Filtro por comercial.
        filtered = _calendar(
            client,
            env["commercial_token"],
            _fmt_day(past),
            _fmt_day(span_end),
            assigned_to="comercial-filter",
        )
        assert filtered["totals"]["total"] == 2
        assert filtered["totals"]["overdue"] == 1
        assert {"Vencida", "Vencida y hecha"} == {
            a["title"]
            for day in filtered["days"]
            for a in day["activities"]
        }

        # Filtro por estado.
        done = _calendar(
            client,
            env["commercial_token"],
            _fmt_day(past),
            _fmt_day(span_end),
            status="done",
        )
        assert done["totals"]["total"] == 1
        assert done["totals"]["completed"] == 1

        # Filtro por tipo.
        calls = _calendar(
            client,
            env["commercial_token"],
            _fmt_day(past),
            _fmt_day(span_end),
            kind="call",
        )
        assert calls["totals"]["total"] == 3
    finally:
        for aid in ids:
            _delete_activity(aid)


def test_calendar_agenda_tz_offset_shifts_day(pipeline_env) -> None:
    """El día local depende de tz_offset (23:30 UTC puede caer al día siguiente)."""
    env = pipeline_env
    client = env["client"]
    activity_id = _seed_calendar_activity(
        title="Tarde-noche", due_at="2026-08-16T23:30:00"
    )
    try:
        # Con offset 0 cae el 16.
        utc = _calendar(client, env["commercial_token"], "2026-08-16", "2026-08-17")
        day16 = next(d for d in utc["days"] if d["date"] == "2026-08-16")
        assert day16["total"] == 1

        # Con offset +120 (UTC+2) cae el 17 local.
        local = _calendar(
            client,
            env["commercial_token"],
            "2026-08-16",
            "2026-08-17",
            tz_offset=120,
        )
        day16 = next(d for d in local["days"] if d["date"] == "2026-08-16")
        day17 = next(d for d in local["days"] if d["date"] == "2026-08-17")
        assert day16["total"] == 0
        assert day17["total"] == 1
    finally:
        _delete_activity(activity_id)


def test_calendar_agenda_excludes_unscheduled_and_out_of_range(pipeline_env) -> None:
    """Actividades sin due_at o fuera del rango no aparecen en la agenda."""
    env = pipeline_env
    client = env["client"]
    ids: list[str] = []
    try:
        db = SessionLocal()
        try:
            unscheduled = Activity(
                title="Sin fecha",
                kind="note",
                status="pending",
                created_by="test-calendar-seed",
            )
            db.add(unscheduled)
            db.flush()
            ids.append(unscheduled.id)
            db.commit()
        finally:
            db.close()
        today = datetime.datetime.now(datetime.UTC).replace(tzinfo=None).date()
        ids.append(
            _seed_calendar_activity(
                title="Fuera de rango",
                due_at=f"{today + datetime.timedelta(days=40)}T09:00:00",
            )
        )

        agenda = _calendar(
            client, env["commercial_token"], _fmt_day(today), _fmt_day(today)
        )
        assert agenda["totals"]["total"] == 0
        assert all(not d["activities"] for d in agenda["days"])
    finally:
        for aid in ids:
            _delete_activity(aid)


def test_calendar_agenda_validation_and_rbac(pipeline_env) -> None:
    """RBAC (operador+), fechas inválidas, rango invertido y rango máximo."""
    env = pipeline_env
    client = env["client"]

    # Viewer no puede ver la agenda.
    assert (
        client.get(
            "/calendar/agenda",
            params={"start": "2026-08-10", "end": "2026-08-10"},
            headers=_auth(env["viewer_token"]),
        ).status_code
        == 403
    )

    # Fecha mal formada → 422.
    bad = client.get(
        "/calendar/agenda",
        params={"start": "10-08-2026", "end": "2026-08-10"},
        headers=_auth(env["commercial_token"]),
    )
    assert bad.status_code == 422, bad.text

    # end < start → 422.
    inverted = client.get(
        "/calendar/agenda",
        params={"start": "2026-08-11", "end": "2026-08-10"},
        headers=_auth(env["commercial_token"]),
    )
    assert inverted.status_code == 422, inverted.text

    # Rango > 92 días → 422.
    too_long = client.get(
        "/calendar/agenda",
        params={"start": "2026-01-01", "end": "2026-12-31"},
        headers=_auth(env["commercial_token"]),
    )
    assert too_long.status_code == 422, too_long.text
