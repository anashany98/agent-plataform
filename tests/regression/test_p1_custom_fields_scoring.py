"""Evals P1-c / P1-d: campos personalizados y lead scoring.

Cubre T-044 (plan CRM B2B) — módulos P1-c y P1-d:

- ``POST /custom-fields`` crea definiciones tipadas por instalación (solo
  admin, auditado); clave duplicada → 409. Un comercial no puede crearlas.
- ``GET /custom-fields`` lista las definiciones activas aplicando la
  visibilidad por rol (viewer solo ``all``, operadores también ``operators``,
  admins todo).
- ``PATCH /custom-fields/{id}`` edita etiqueta/obligatoriedad/visibilidad/
  activo (solo admin, auditado); desactivar sustituye a borrar.
- ``PUT /custom-values`` hace upsert idempotente del valor de un campo sobre
  un lead u oportunidad: valida el tipo contra la definición, rechaza valores
  fuera de las opciones de un ``select``, exige ``Idempotency-Key`` y devuelve
  403 si el campo no es visible para el rol.
- ``GET /custom-values`` devuelve definición+valor por entidad, filtrado por
  visibilidad.
- ``GET /leads/{id}/score`` puntúa el lead de forma determinista y explica las
  señales (origen, antigüedad, oportunidades abiertas, valor, histórico won).
- ``GET /pipeline/board`` ordena la cola de leads sin asignar por puntuación
  descendente.

Hermeticidad D-032: usuarios y filas se crean/limpian con ids únicos y la
instalación de prueba es la del contexto ORM (single-tenant por instancia).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.models.models import AuditLog, Lead, Opportunity, User

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


def _login(client, username: str) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def _seed_lead(*, source: str = "local", age_days: float = 0) -> str:
    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Scoring",
            source=source,
            status="new",
        )
        db.add(lead)
        db.flush()
        if age_days:
            lead.created_at = datetime.datetime.now(datetime.UTC).replace(
                tzinfo=None
            ) - datetime.timedelta(days=age_days)
        db.commit()
        return lead.id
    finally:
        db.close()


def _seed_opportunity(
    lead_id: str,
    *,
    stage: str = "new",
    status: str = "open",
    value: Decimal = Decimal("100.00"),
) -> str:
    db = SessionLocal()
    try:
        opportunity = Opportunity(
            id=f"opp-{uuid.uuid4().hex[:8]}",
            lead_id=lead_id,
            external_reference=f"quote-{uuid.uuid4().hex[:6]}",
            name="Oportunidad Scoring",
            monetary_value=value,
            currency="EUR",
            pipeline="default",
            stage=stage,
            status=status,
        )
        db.add(opportunity)
        db.commit()
        return opportunity.id
    finally:
        db.close()


def _cleanup(*, lead_ids=(), opp_ids=(), field_ids=()) -> None:
    db = SessionLocal()
    try:
        from app.models.models import CustomFieldDefinition, CustomFieldValue

        for opp_id in opp_ids:
            db.query(Opportunity).filter(Opportunity.id == opp_id).delete()
        if field_ids:
            db.query(CustomFieldValue).filter(
                CustomFieldValue.field_id.in_(field_ids)
            ).delete(synchronize_session=False)
            db.query(CustomFieldDefinition).filter(
                CustomFieldDefinition.id.in_(field_ids)
            ).delete(synchronize_session=False)
        for lead_id in lead_ids:
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
def scoring_env(client, auth_headers):
    """Crea admin (fixture), comercial y viewer de prueba y los limpia."""
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


def _create_field(client, token, **overrides) -> dict:
    payload = {
        "key": _unique("campo").lower().replace("-", "_"),
        "label": "Sector",
        "entity_type": "lead",
        "field_type": "text",
    }
    payload.update(overrides)
    response = client.post("/custom-fields", json=payload, headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# P1-c: definiciones de campos personalizados
# ---------------------------------------------------------------------------


def test_custom_field_create_admin_audited(scoring_env) -> None:
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    field = _create_field(client, admin_token, key=_unique("sector").lower())
    _cleanup(field_ids=[field["id"]])
    assert field["key"].startswith("sector")
    assert field["entity_type"] == "lead"
    assert field["field_type"] == "text"
    assert field["is_active"] is True
    created = _audit_events("custom_field.created")
    assert any(event.get("field_id") == field["id"] for event in created)


def test_custom_field_create_requires_admin(scoring_env) -> None:
    """Un comercial no puede crear definiciones (403)."""
    client = scoring_env["client"]
    response = client.post(
        "/custom-fields",
        json={"key": _unique("solo_admin").lower(), "label": "Solo admin"},
        headers=_auth(scoring_env["commercial_token"]),
    )
    assert response.status_code == 403


def test_custom_field_duplicate_key_conflict(scoring_env) -> None:
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    key = _unique("duplicado").lower()
    first = _create_field(client, admin_token, key=key)
    response = client.post(
        "/custom-fields",
        json={"key": key, "label": "Otro"},
        headers=_auth(admin_token),
    )
    _cleanup(field_ids=[first["id"]])
    assert response.status_code == 409


def test_custom_field_visibility_filtering(scoring_env) -> None:
    """GET filtra definiciones por visibilidad y rol del principal."""
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    f_all = _create_field(client, admin_token, key=_unique("all").lower(), visibility="all")
    f_ops = _create_field(
        client, admin_token, key=_unique("ops").lower(), visibility="operators"
    )
    f_adm = _create_field(
        client, admin_token, key=_unique("adm").lower(), visibility="admins"
    )
    try:
        viewer_ids = {
            f["id"]
            for f in client.get(
                "/custom-fields", headers=_auth(scoring_env["viewer_token"])
            ).json()
        }
        commercial_ids = {
            f["id"]
            for f in client.get(
                "/custom-fields", headers=_auth(scoring_env["commercial_token"])
            ).json()
        }
        admin_ids = {
            f["id"] for f in client.get("/custom-fields", headers=_auth(admin_token)).json()
        }
        assert f_all["id"] in viewer_ids
        assert f_ops["id"] not in viewer_ids
        assert f_adm["id"] not in viewer_ids
        assert f_ops["id"] in commercial_ids
        assert f_adm["id"] not in commercial_ids
        assert {f_all["id"], f_ops["id"], f_adm["id"]} <= admin_ids
    finally:
        _cleanup(field_ids=[f_all["id"], f_ops["id"], f_adm["id"]])


def test_custom_field_update_and_deactivate(scoring_env) -> None:
    """PATCH edita y desactiva (solo admin, auditado); desactivado no se lista."""
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    field = _create_field(client, admin_token, key=_unique("editable").lower())
    try:
        response = client.patch(
            f"/custom-fields/{field['id']}",
            json={"label": "Sector económico", "required": True},
            headers=_auth(admin_token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["label"] == "Sector económico"
        assert response.json()["required"] is True

        # Un comercial no puede editar.
        forbidden = client.patch(
            f"/custom-fields/{field['id']}",
            json={"label": "No debería"},
            headers=_auth(scoring_env["commercial_token"]),
        )
        assert forbidden.status_code == 403

        deactivate = client.patch(
            f"/custom-fields/{field['id']}",
            json={"is_active": False},
            headers=_auth(admin_token),
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["is_active"] is False
        listed_ids = {
            f["id"] for f in client.get("/custom-fields", headers=_auth(admin_token)).json()
        }
        assert field["id"] not in listed_ids
        updated = _audit_events("custom_field.updated")
        assert any(event.get("field_id") == field["id"] for event in updated)
    finally:
        _cleanup(field_ids=[field["id"]])


# ---------------------------------------------------------------------------
# P1-c: valores de campos personalizados
# ---------------------------------------------------------------------------


def test_custom_value_upsert_idempotent_and_typed(scoring_env) -> None:
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    lead_id = _seed_lead()
    field = _create_field(client, admin_token, key=_unique("texto").lower())
    try:
        idem = _idem()
        payload = {
            "entity_type": "lead",
            "entity_id": lead_id,
            "field_id": field["id"],
            "value": "Distribución",
        }
        first = client.put("/custom-values", json=payload, headers={**_auth(admin_token), **idem})
        assert first.status_code == 200, first.text
        assert first.json()["value"] == "Distribución"
        # Replay con la misma key y payload: misma respuesta, sin duplicar.
        replay = client.put("/custom-values", json=payload, headers={**_auth(admin_token), **idem})
        assert replay.status_code == 200
        assert replay.json()["value"] == "Distribución"

        values = client.get(
            "/custom-values",
            params={"entity_type": "lead", "entity_id": lead_id},
            headers=_auth(admin_token),
        )
        assert values.status_code == 200
        matching = [row for row in values.json() if row["field"]["id"] == field["id"]]
        assert len(matching) == 1
        assert matching[0]["value"] == "Distribución"
        assert any(
            event.get("field_id") == field["id"]
            for event in _audit_events("custom_field.value_updated")
        )
    finally:
        _cleanup(lead_ids=[lead_id], field_ids=[field["id"]])


def test_custom_value_type_validation(scoring_env) -> None:
    """Valores fuera de tipo o de opciones → 422; sin Idempotency-Key → 428."""
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    lead_id = _seed_lead()
    select = _create_field(
        client,
        admin_token,
        key=_unique("select").lower(),
        field_type="select",
        options=["A", "B"],
    )
    try:
        base = {"entity_type": "lead", "entity_id": lead_id, "field_id": select["id"]}
        bad_option = client.put(
            "/custom-values",
            json={**base, "value": "Z"},
            headers={**_auth(admin_token), **_idem()},
        )
        assert bad_option.status_code == 422
        bad_number = client.put(
            "/custom-values",
            json={**base, "value": 42},
            headers={**_auth(admin_token), **_idem()},
        )
        assert bad_number.status_code == 422
        missing_key = client.put(
            "/custom-values", json={**base, "value": "A"}, headers=_auth(admin_token)
        )
        assert missing_key.status_code == 428
    finally:
        _cleanup(lead_ids=[lead_id], field_ids=[select["id"]])


def test_custom_value_invisible_field_forbidden(scoring_env) -> None:
    """Un viewer no puede escribir un campo con visibilidad ``operators``."""
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    lead_id = _seed_lead()
    field = _create_field(
        client, admin_token, key=_unique("interno").lower(), visibility="operators"
    )
    try:
        response = client.put(
            "/custom-values",
            json={
                "entity_type": "lead",
                "entity_id": lead_id,
                "field_id": field["id"],
                "value": "x",
            },
            headers={**_auth(scoring_env["viewer_token"]), **_idem()},
        )
        assert response.status_code == 403
        # Y tampoco lo ve en el listado de valores.
        values = client.get(
            "/custom-values",
            params={"entity_type": "lead", "entity_id": lead_id},
            headers=_auth(scoring_env["viewer_token"]),
        )
        assert all(row["field"]["id"] != field["id"] for row in values.json())
    finally:
        _cleanup(lead_ids=[lead_id], field_ids=[field["id"]])


# ---------------------------------------------------------------------------
# P1-d: lead scoring
# ---------------------------------------------------------------------------


def test_lead_score_signals_are_deterministic(scoring_env) -> None:
    """El score refleja origen, antigüedad, oportunidades, valor y won."""
    client = scoring_env["client"]
    token = scoring_env["commercial_token"]

    # Lead reciente de chat con oportunidad abierta de valor → score alto.
    hot = _seed_lead(source="chat")
    _seed_opportunity(hot, stage="new", status="open", value=Decimal("500.00"))
    # Lead antiguo local sin oportunidades → score bajo.
    cold = _seed_lead(source="local", age_days=120)

    try:
        hot_score = client.get(f"/leads/{hot}/score", headers=_auth(token))
        assert hot_score.status_code == 200, hot_score.text
        hot_body = hot_score.json()
        kinds = {signal["kind"] for signal in hot_body["signals"]}
        assert {"source", "age", "opportunities", "value"} <= kinds
        assert hot_body["score"] >= 80

        cold_score = client.get(f"/leads/{cold}/score", headers=_auth(token))
        assert cold_score.status_code == 200
        assert cold_score.json()["score"] < hot_body["score"]
        # Determinismo: la misma consulta repite el resultado.
        repeat = client.get(f"/leads/{hot}/score", headers=_auth(token))
        assert repeat.json()["score"] == hot_body["score"]
    finally:
        _cleanup(lead_ids=[hot, cold])


def test_lead_score_won_history_adds_signal(scoring_env) -> None:
    client = scoring_env["client"]
    token = scoring_env["commercial_token"]
    lead_id = _seed_lead(source="local")
    _seed_opportunity(lead_id, stage="won", status="closed", value=Decimal("50.00"))
    try:
        body = client.get(f"/leads/{lead_id}/score", headers=_auth(token)).json()
        assert any(signal["kind"] == "won_history" for signal in body["signals"])
    finally:
        _cleanup(lead_ids=[lead_id])


def test_lead_score_missing_lead_404(scoring_env) -> None:
    client = scoring_env["client"]
    response = client.get("/leads/no-existe/score", headers=_auth(scoring_env["commercial_token"]))
    assert response.status_code == 404


def test_board_queue_sorted_by_score(scoring_env) -> None:
    """La cola de leads sin asignar se ordena por puntuación descendente."""
    client = scoring_env["client"]
    token = scoring_env["commercial_token"]
    # Ambos sin asignar; el de chat con oportunidad debe puntuar más alto.
    hot = _seed_lead(source="chat")
    _seed_opportunity(hot, status="open", value=Decimal("900.00"))
    cold = _seed_lead(source="local", age_days=200)
    try:
        board = client.get("/pipeline/board", headers=_auth(token)).json()
        queue_ids = [row["id"] for row in board["unassigned_leads"]]
        assert hot in queue_ids and cold in queue_ids
        assert queue_ids.index(hot) < queue_ids.index(cold)
        hot_row = next(row for row in board["unassigned_leads"] if row["id"] == hot)
        assert hot_row["score"] >= 80
        assert isinstance(hot_row["score_signals"], list)
    finally:
        _cleanup(lead_ids=[hot, cold])


# ---------------------------------------------------------------------------
# P2-e: import/export CSV de leads
# ---------------------------------------------------------------------------


def test_export_leads_csv_includes_custom_fields(scoring_env) -> None:
    """El CSV exporta columnas fijas + campos personalizados activos."""
    client = scoring_env["client"]
    admin_token = scoring_env["auth_headers"]["Authorization"].split()[1]
    lead_id = _seed_lead(source="import")
    field = _create_field(client, admin_token, key=_unique("sector_exp").lower())
    try:
        # Fijar un valor de campo personalizado sobre el lead.
        set_value = client.put(
            "/custom-values",
            json={
                "entity_type": "lead",
                "entity_id": lead_id,
                "field_id": field["id"],
                "value": "Retail",
            },
            headers={**_auth(admin_token), **_idem()},
        )
        assert set_value.status_code == 200, set_value.text

        response = client.get("/leads/export.csv", headers=_auth(admin_token))
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        text = response.text
        header_line = text.splitlines()[0]
        for column in ("email", "first_name", "source", "status", "assigned_to"):
            assert column in header_line
        assert field["key"] in header_line
        # La fila del lead incluye su email y el valor del campo.
        matching = [line for line in text.splitlines() if "example.invalid" in line]
        assert any("Retail" in line for line in matching)
    finally:
        _cleanup(lead_ids=[lead_id], field_ids=[field["id"]])


def test_import_leads_creates_and_dedupes(scoring_env) -> None:
    """La importación crea con source=import, deduplica por email y audita."""
    client = scoring_env["client"]
    token = scoring_env["commercial_token"]
    unique = uuid.uuid4().hex[:10]
    rows = [
        {"email": f"a-{unique}@example.invalid", "first_name": "Alfa"},
        {"email": f"b-{unique}@example.invalid", "first_name": "Beta", "company_name": "B Corp"},
        {"email": f"a-{unique}@example.invalid", "first_name": "Alfa otra vez"},
        {"email": "no-es-un-email", "first_name": "Inválido"},
    ]
    response = client.post(
        "/leads/import",
        json={"rows": rows},
        headers={**_auth(token), **_idem()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["received"] == 4
    assert body["created"] == 2  # a- y b- (el a- repetido es duplicado intra-lote)
    assert body["skipped_duplicates"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["reason"] == "email_invalido"
    assert any(
        event.get("created") == 2 for event in _audit_events("lead.import_completed")
    )

    # Limpieza: borrar los dos leads creados.
    from app.database import SessionLocal as _SL

    db = _SL()
    try:
        db.query(Lead).filter(Lead.email.like(f"%-{unique}@example.invalid")).delete()
        db.commit()
    finally:
        db.close()


def test_import_leads_dry_run_creates_nothing(scoring_env) -> None:
    client = scoring_env["client"]
    token = scoring_env["commercial_token"]
    unique = uuid.uuid4().hex[:10]
    response = client.post(
        "/leads/import",
        json={"rows": [{"email": f"dry-{unique}@example.invalid", "first_name": "Dry"}], "dry_run": True},
        headers=_auth(token),  # sin Idempotency-Key: el dry_run no la exige
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["would_create"] == 1
    # Nada persistido.
    db = SessionLocal()
    try:
        assert db.query(Lead).filter(Lead.email == f"dry-{unique}@example.invalid").first() is None
    finally:
        db.close()


def test_import_leads_requires_idempotency_key(scoring_env) -> None:
    client = scoring_env["client"]
    response = client.post(
        "/leads/import",
        json={"rows": [{"email": "x@example.invalid", "first_name": "X"}]},
        headers=_auth(scoring_env["commercial_token"]),
    )
    assert response.status_code == 428


def test_import_export_rbac_viewer_forbidden(scoring_env) -> None:
    client = scoring_env["client"]
    viewer = _auth(scoring_env["viewer_token"])
    assert client.get("/leads/export.csv", headers=viewer).status_code == 403
    assert (
        client.post(
            "/leads/import",
            json={"rows": []},
            headers={**viewer, **_idem()},
        ).status_code
        == 403
    )
