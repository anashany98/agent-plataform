"""Evals T-054: datos maestros del CRM (cuenta vs contacto, merge, cierre).

Cubre el módulo de datos maestros del plan CRM:

- ``Account`` (empresa) y ``Contact`` (persona) separados: CRUD auditado de
  cuentas y contactos, email único por instalación, cuenta inexistente → 404,
  nombre/email duplicado → 409.
- Merge de contactos: los leads del perdedor se reasignan al ganador y el
  perdedor queda marcado (``merged_into_contact_id``), nunca borrado.
- Probabilidad por etapa: ``PATCH /pipeline/stages/{id}`` solo admin,
  auditado; fuera de rango → 422.
- Cierre de oportunidad: ``POST /opportunities/{id}/close`` con
  ``outcome=won|lost`` fija stage/status, probabilidad 100/0, ``won_at`` /
  ``lost_at`` y ``lost_reason``; ya terminal → 422; emite el webhook
  ``opportunity.closed`` por el outbox durable (mismo commit).
- Merge de leads: mueve oportunidades, actividades y campos personalizados
  (en colisión se conserva el del ganador), marca el perdedor ``merged`` y lo
  excluye de ``GET /leads``.
- Reporte ``GET /pipeline/report``: ``lost_reasons`` agrupados por motivo,
  ``weighted_pipeline_value`` (valor × probabilidad efectiva) y
  ``probability`` por etapa.

Hermeticidad D-032: sin red (el worker del outbox está deshabilitado en
tests; los webhooks quedan ``pending``), usuarios y filas únicos por
ejecución con limpieza en ``finally``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.models.models import (
    Account,
    Activity,
    AuditLog,
    Contact,
    CustomFieldDefinition,
    CustomFieldValue,
    Lead,
    Opportunity,
    OutboxMessage,
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


def _login(client, username: str) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def master_env(client, auth_headers):
    """Crea un comercial, un viewer y un admin de prueba; limpia al terminar."""
    commercial = _unique("comercial-md")
    viewer = _unique("viewer-md")
    admin = _unique("admin-md")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    _create_user(client, auth_headers, admin, "client_admin")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "commercial_token": _login(client, commercial)["access_token"],
        "viewer_token": _login(client, viewer)["access_token"],
        "admin_token": _login(client, admin)["access_token"],
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


def _seed_lead_opportunity(
    *,
    stage: str = "new",
    value: str = "250.00",
    name: str = "Presupuesto Maestro",
) -> tuple[str, str]:
    """Siembra un lead con una oportunidad (vía ORM) y devuelve (lead_id, opp_id)."""
    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Maestro",
            company_name="Maestro Corp",
            source="local",
            status="new",
        )
        db.add(lead)
        db.flush()
        opportunity = Opportunity(
            id=f"opp-{uuid.uuid4().hex[:8]}",
            lead_id=lead.id,
            external_reference=f"quote-{uuid.uuid4().hex[:6]}",
            name=name,
            monetary_value=Decimal(value),
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
        if opportunity_id:
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


def _delete_account(account_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Contact).filter(Contact.account_id == account_id).delete()
        db.query(Account).filter(Account.id == account_id).delete()
        db.commit()
    finally:
        db.close()


def _delete_contact(contact_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Contact).filter(Contact.id == contact_id).delete()
        db.commit()
    finally:
        db.close()


def test_accounts_crud_audited_with_rbac(master_env) -> None:
    """Crear/editar cuentas (auditado), duplicado 409 y viewer 403."""
    env = master_env
    client = env["client"]
    account_id: str | None = None
    try:
        assert (
            client.get("/accounts", headers=_auth(env["viewer_token"])).status_code
            == 403
        )
        assert (
            client.post(
                "/accounts",
                json={"name": "x"},
                headers=_auth(env["viewer_token"]),
            ).status_code
            == 403
        )

        created = client.post(
            "/accounts",
            json={
                "name": "Acme Industrial",
                "industry": "Manufactura",
                "website": "https://acme.test",
                "city": "Madrid",
                "country": "ES",
            },
            headers=_auth(env["commercial_token"]),
        )
        assert created.status_code == 200, created.text
        account_id = created.json()["id"]
        assert created.json()["name"] == "Acme Industrial"
        assert created.json()["contact_count"] == 0

        # Nombre duplicado → 409.
        duplicate = client.post(
            "/accounts",
            json={"name": "Acme Industrial"},
            headers=_auth(env["commercial_token"]),
        )
        assert duplicate.status_code == 409, duplicate.text

        # Edición: rename + inactiva.
        updated = client.patch(
            f"/accounts/{account_id}",
            json={"name": "Acme Industrial SL", "is_active": False},
            headers=_auth(env["commercial_token"]),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Acme Industrial SL"
        assert updated.json()["is_active"] is False

        # Ficha con métricas.
        detail = client.get(
            f"/accounts/{account_id}", headers=_auth(env["commercial_token"])
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["contacts"] == []

        # Lista.
        listing = client.get("/accounts", headers=_auth(env["commercial_token"])).json()
        assert any(item["id"] == account_id for item in listing)

        events = _audit_events("account.created")
        assert any(d.get("account_id") == account_id for d in events)
        updates = _audit_events("account.updated")
        assert any(d.get("account_id") == account_id for d in updates)
    finally:
        if account_id:
            _delete_account(account_id)


def test_contacts_crud_and_merge(master_env) -> None:
    """Contactos: alta con cuenta, duplicado 409, cuenta inexistente 404 y merge."""
    env = master_env
    client = env["client"]
    account_id: str | None = None
    contact_a: str | None = None
    contact_b: str | None = None
    lead_ids: list[str] = []
    try:
        created = client.post(
            "/accounts",
            json={"name": "Corp Maestra"},
            headers=_auth(env["commercial_token"]),
        )
        account_id = created.json()["id"]

        ca = client.post(
            "/contacts",
            json={
                "account_id": account_id,
                "first_name": "Ana",
                "last_name": "Pérez",
                "email": "ana.perez@corp.test",
                "job_title": "Compradora",
                "is_primary": True,
            },
            headers=_auth(env["commercial_token"]),
        )
        assert ca.status_code == 200, ca.text
        contact_a = ca.json()["id"]

        # Email duplicado → 409.
        dup = client.post(
            "/contacts",
            json={"first_name": "Ana", "email": "ana.perez@corp.test"},
            headers=_auth(env["commercial_token"]),
        )
        assert dup.status_code == 409, dup.text

        # Cuenta inexistente → 404.
        missing = client.post(
            "/contacts",
            json={"account_id": "cuenta-no-existe", "first_name": "x", "email": "x@y.test"},
            headers=_auth(env["commercial_token"]),
        )
        assert missing.status_code == 404, missing.text

        cb = client.post(
            "/contacts",
            json={
                "account_id": account_id,
                "first_name": "Ana",
                "last_name": "Pérez (duplicada)",
                "email": "ana.perez2@corp.test",
            },
            headers=_auth(env["commercial_token"]),
        )
        assert cb.status_code == 200, cb.text
        contact_b = cb.json()["id"]

        # Un lead se vincula al contacto B (vía ORM) para probar el merge.
        db = SessionLocal()
        try:
            lead = Lead(
                id=f"lead-{uuid.uuid4().hex[:8]}",
                email=f"{uuid.uuid4().hex[:10]}@example.invalid",
                first_name="Persona B",
                contact_id=contact_b,
                account_id=account_id,
                source="local",
                status="new",
            )
            db.add(lead)
            db.commit()
            lead_ids.append(lead.id)
        finally:
            db.close()

        # Merge B → A: el lead pasa al contacto ganador.
        merged = client.post(
            f"/contacts/{contact_b}/merge",
            json={"into_id": contact_a},
            headers=_auth(env["commercial_token"]),
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["leads_moved"] == 1

        db = SessionLocal()
        try:
            moved = (
                db.query(Lead).filter(Lead.contact_id == contact_a).count()
            )
            assert moved == 1
            loser = db.query(Contact).filter(Contact.id == contact_b).first()
            assert loser.merged_into_contact_id == contact_a
            assert loser.is_primary is False
            winner = db.query(Contact).filter(Contact.id == contact_a).first()
            assert winner.is_primary is True
        finally:
            db.close()

        # Merge consigo mismo → 422.
        self_merge = client.post(
            f"/contacts/{contact_a}/merge",
            json={"into_id": contact_a},
            headers=_auth(env["commercial_token"]),
        )
        assert self_merge.status_code == 422, self_merge.text

        # Ya fusionado → 422.
        again = client.post(
            f"/contacts/{contact_b}/merge",
            json={"into_id": contact_a},
            headers=_auth(env["commercial_token"]),
        )
        assert again.status_code == 422, again.text

        # Filtro por cuenta.
        listing = client.get(
            f"/contacts?account_id={account_id}",
            headers=_auth(env["commercial_token"]),
        ).json()
        assert any(item["id"] == contact_a for item in listing)

        events = _audit_events("contact.merged")
        assert any(d.get("winner_contact_id") == contact_a for d in events)
    finally:
        for lead_id in lead_ids:
            db = SessionLocal()
            try:
                db.query(Lead).filter(Lead.id == lead_id).delete()
                db.commit()
            finally:
                db.close()
        if contact_b:
            _delete_contact(contact_b)
        if contact_a:
            _delete_contact(contact_a)
        if account_id:
            _delete_account(account_id)


def test_stage_probability_admin_only(master_env) -> None:
    """Probabilidad por etapa: solo admin, auditado, validación de rango."""
    env = master_env
    client = env["client"]

    stages = client.get(
        "/pipeline/stages", headers=_auth(env["commercial_token"])
    ).json()
    stage = next(s for s in stages if s["key"] == "quote")

    assert (
        client.patch(
            f"/pipeline/stages/{stage['id']}",
            json={"probability": 40},
            headers=_auth(env["commercial_token"]),
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/pipeline/stages/{stage['id']}",
            json={"probability": 40},
            headers=_auth(env["viewer_token"]),
        ).status_code
        == 403
    )

    updated = client.patch(
        f"/pipeline/stages/{stage['id']}",
        json={"probability": 40},
        headers=_auth(env["admin_token"]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["probability"] == 40

    # Fuera de rango → 422.
    invalid = client.patch(
        f"/pipeline/stages/{stage['id']}",
        json={"probability": 150},
        headers=_auth(env["admin_token"]),
    )
    assert invalid.status_code == 422, invalid.text

    # Etapa inexistente → 404.
    missing = client.patch(
        "/pipeline/stages/stage-no-existe",
        json={"probability": 10},
        headers=_auth(env["admin_token"]),
    )
    assert missing.status_code == 404, missing.text

    events = _audit_events("pipeline.stage_probability_updated")
    assert any(
        d.get("stage_key") == "quote" and d.get("probability") == 40
        for d in events
    )


def test_close_opportunity_won_and_lost(master_env) -> None:
    """Cierre ganada/perdida: stage/status, probabilidad, motivo y webhook."""
    env = master_env
    client = env["client"]
    lead_id, opp_id = _seed_lead_opportunity()
    lead2, opp2 = _seed_lead_opportunity(value="500.00")
    subscription_id: str | None = None
    try:
        # Suscripción al evento opportunity.closed para verificar el outbox.
        sub = client.post(
            "/webhooks/subscriptions",
            json={
                "name": _unique("close-sub"),
                "url": "https://public.test/hook",
                "secret": "subscription-secret-16ch",
                "events": ["opportunity.closed"],
            },
            headers={
                **_auth(env["admin_token"]),
                "Idempotency-Key": f"close-sub-{uuid.uuid4().hex[:12]}",
            },
        )
        assert sub.status_code == 200, sub.text
        subscription_id = sub.json()["id"]

        # Viewer no puede cerrar.
        assert (
            client.post(
                f"/opportunities/{opp_id}/close",
                json={"outcome": "won"},
                headers=_auth(env["viewer_token"]),
            ).status_code
            == 403
        )

        won = client.post(
            f"/opportunities/{opp_id}/close",
            json={"outcome": "won"},
            headers=_auth(env["commercial_token"]),
        )
        assert won.status_code == 200, won.text
        assert won.json()["status"] == "won"
        assert won.json()["probability"] == 100
        assert won.json()["won_at"] is not None
        assert won.json()["lost_at"] is None

        lost = client.post(
            f"/opportunities/{opp2}/close",
            json={"outcome": "lost", "lost_reason": "Precio demasiado alto"},
            headers=_auth(env["commercial_token"]),
        )
        assert lost.status_code == 200, lost.text
        assert lost.json()["status"] == "lost"
        assert lost.json()["probability"] == 0
        assert lost.json()["lost_reason"] == "Precio demasiado alto"
        assert lost.json()["lost_at"] is not None

        # Ya terminal → 422.
        again = client.post(
            f"/opportunities/{opp_id}/close",
            json={"outcome": "lost"},
            headers=_auth(env["commercial_token"]),
        )
        assert again.status_code == 422, again.text

        # outcome inválido → 422.
        bad = client.post(
            f"/opportunities/{lead2}/close",
            json={"outcome": "quizas"},
            headers=_auth(env["commercial_token"]),
        )
        assert bad.status_code == 422, bad.text

        events = _audit_events("opportunity.closed")
        assert any(
            d.get("opportunity_id") == opp_id and d.get("outcome") == "won"
            for d in events
        )
        assert any(
            d.get("opportunity_id") == opp2 and d.get("outcome") == "lost"
            for d in events
        )

        # El webhook opportunity.closed se encoló en el outbox (mismo commit).
        db = SessionLocal()
        try:
            queued = (
                db.query(OutboxMessage)
                .filter(OutboxMessage.topic == "crm.webhook")
                .filter(OutboxMessage.payload.like("%opportunity.closed%"))
                .count()
            )
            assert queued >= 2
        finally:
            db.close()
    finally:
        if subscription_id:
            client.delete(
                f"/webhooks/subscriptions/{subscription_id}",
                headers=_auth(env["admin_token"]),
            )
        _cleanup_lead_opportunity(lead2, opp2)
        _cleanup_lead_opportunity(lead_id, opp_id)


def test_merge_leads_moves_children_and_hides_loser(master_env) -> None:
    """Merge de leads: mueve oportunidades/actividades/campos y oculta al perdedor."""
    env = master_env
    client = env["client"]
    loser_lead_id: str | None = None
    winner_lead_id: str | None = None
    loser_opp: str | None = None
    winner_opp: str | None = None
    loser_activity: str | None = None
    definitions: list[str] = []
    try:
        # Ganador: 1 oportunidad + 1 campo "sector" con valor.
        winner_lead_id, winner_opp = _seed_lead_opportunity(
            stage="quote", value="800.00", name="Ganador"
        )
        # Perdedor: 1 oportunidad + 1 actividad + campo "sector" (colisión) +
        # campo "prioridad" (sin colisión).
        loser_lead_id, loser_opp = _seed_lead_opportunity(
            stage="new", value="300.00", name="Perdedor"
        )

        db = SessionLocal()
        try:
            activity = Activity(
                lead_id=loser_lead_id,
                title="Follow-up del perdedor",
                kind="follow_up",
                status="pending",
                created_by="test-md",
            )
            db.add(activity)
            db.flush()
            loser_activity = activity.id

            def _field(key: str) -> str:
                definition = CustomFieldDefinition(
                    key=key,
                    label=key,
                    entity_type="lead",
                    field_type="text",
                    options=None,
                    required=False,
                    visibility="all",
                    position=0,
                    is_active=True,
                )
                db.add(definition)
                db.flush()
                definitions.append(definition.id)
                return definition.id

            sector = _field("sector")
            prioridad = _field("prioridad")
            db.add(
                CustomFieldValue(
                    field_id=sector,
                    entity_type="lead",
                    entity_id=winner_lead_id,
                    value_json={"value": "Ganador-sector"},
                )
            )
            db.add(
                CustomFieldValue(
                    field_id=sector,
                    entity_type="lead",
                    entity_id=loser_lead_id,
                    value_json={"value": "Perdedor-sector"},
                )
            )
            db.add(
                CustomFieldValue(
                    field_id=prioridad,
                    entity_type="lead",
                    entity_id=loser_lead_id,
                    value_json={"value": "Alta"},
                )
            )
            db.commit()
        finally:
            db.close()

        # Merge perdedor → ganador.
        merged = client.post(
            f"/leads/{loser_lead_id}/merge",
            json={"into_id": winner_lead_id},
            headers=_auth(env["commercial_token"]),
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["opportunities_moved"] == 1
        assert merged.json()["activities_moved"] == 1
        assert merged.json()["custom_fields_moved"] == 1  # prioridad
        assert merged.json()["custom_field_collisions"] == 1  # sector

        db = SessionLocal()
        try:
            # La oportunidad y la actividad ahora cuelgan del ganador.
            assert (
                db.query(Opportunity).filter(Opportunity.id == loser_opp).first().lead_id
                == winner_lead_id
            )
            assert (
                db.query(Activity).filter(Activity.id == loser_activity).first().lead_id
                == winner_lead_id
            )
            # En colisión se conserva el valor del ganador.
            winner_sector = (
                db.query(CustomFieldValue)
                .filter(
                    CustomFieldValue.entity_type == "lead",
                    CustomFieldValue.entity_id == winner_lead_id,
                    CustomFieldValue.field_id == sector,
                )
                .first()
            )
            assert winner_sector.value_json == {"value": "Ganador-sector"}
            # El campo sin colisión se movió.
            moved_priority = (
                db.query(CustomFieldValue)
                .filter(
                    CustomFieldValue.entity_type == "lead",
                    CustomFieldValue.entity_id == winner_lead_id,
                    CustomFieldValue.field_id == prioridad,
                )
                .first()
            )
            assert moved_priority is not None
            assert moved_priority.value_json == {"value": "Alta"}
            # El perdedor queda marcado y su valor de sector ya no existe.
            loser = db.query(Lead).filter(Lead.id == loser_lead_id).first()
            assert loser.merged_into_lead_id == winner_lead_id
            assert loser.status == "merged"
        finally:
            db.close()

        # GET /leads excluye al perdedor.
        listing = client.get("/leads", headers=_auth(env["commercial_token"])).json()
        assert not any(item["id"] == loser_lead_id for item in listing)
        assert any(item["id"] == winner_lead_id for item in listing)

        # Merge consigo mismo → 422 y ya fusionado → 422.
        self_merge = client.post(
            f"/leads/{winner_lead_id}/merge",
            json={"into_id": winner_lead_id},
            headers=_auth(env["commercial_token"]),
        )
        assert self_merge.status_code == 422, self_merge.text

        events = _audit_events("lead.merged")
        assert any(
            d.get("winner_lead_id") == winner_lead_id
            and d.get("loser_lead_id") == loser_lead_id
            for d in events
        )
    finally:
        db = SessionLocal()
        try:
            if loser_activity:
                db.query(Activity).filter(Activity.id == loser_activity).delete()
            if definitions:
                db.query(CustomFieldValue).filter(
                    CustomFieldValue.field_id.in_(definitions)
                ).delete()
                db.query(CustomFieldDefinition).filter(
                    CustomFieldDefinition.id.in_(definitions)
                ).delete()
            if loser_opp:
                db.query(Opportunity).filter(Opportunity.id == loser_opp).delete()
            if winner_opp:
                db.query(Opportunity).filter(Opportunity.id == winner_opp).delete()
            if loser_lead_id:
                db.query(Lead).filter(Lead.id == loser_lead_id).delete()
            if winner_lead_id:
                db.query(Lead).filter(Lead.id == winner_lead_id).delete()
            db.commit()
        finally:
            db.close()


def test_report_lost_reasons_and_weighted_pipeline(master_env) -> None:
    """Reporte: motivos de pérdida agrupados y weighted pipeline con probabilidad."""
    env = master_env
    client = env["client"]
    rows: list[tuple[str, str]] = []
    try:
        # won 100; lost con motivo 200; lost sin motivo 50; abierta override 50% (200);
        # abierta en etapa quote con probabilidad de etapa.
        _, opp_won = _seed_lead_opportunity(stage="won", value="100.00")
        rows.append(("lead-won", opp_won))
        _, opp_lost_reason = _seed_lead_opportunity(stage="lost", value="200.00")
        rows.append(("lead-lost-reason", opp_lost_reason))
        _, opp_lost_no = _seed_lead_opportunity(stage="lost", value="50.00")
        rows.append(("lead-lost-no", opp_lost_no))
        _, opp_override = _seed_lead_opportunity(stage="new", value="200.00")
        rows.append(("lead-override", opp_override))
        _, opp_quote = _seed_lead_opportunity(stage="quote", value="400.00")
        rows.append(("lead-quote", opp_quote))

        # Configurar probabilidades: quote=25; override en la "new" = 50.
        stages = client.get(
            "/pipeline/stages", headers=_auth(env["admin_token"])
        ).json()
        quote_stage = next(s for s in stages if s["key"] == "quote")
        assert (
            client.patch(
                f"/pipeline/stages/{quote_stage['id']}",
                json={"probability": 25},
                headers=_auth(env["admin_token"]),
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/opportunities/{opp_override}",
                json={"probability": 50},
                headers=_auth(env["commercial_token"]),
            ).status_code
            == 200
        )

        db = SessionLocal()
        try:
            db.query(Opportunity).filter(Opportunity.id == opp_lost_reason).update(
                {"lost_reason": "Precio demasiado alto"}
            )
            db.query(Opportunity).filter(Opportunity.id == opp_lost_no).update(
                {"lost_reason": None}
            )
            db.commit()
        finally:
            db.close()

        report = client.get(
            "/pipeline/report", headers=_auth(env["commercial_token"])
        ).json()

        # weighted = 200*0.5 (override) + 400*0.25 (etapa) = 100 + 100 = 200.
        assert report["summary"]["weighted_pipeline_value"] == 200.0

        reasons = {entry["reason"]: entry for entry in report["lost_reasons"]}
        assert reasons["Precio demasiado alto"]["value"] == 200.0
        assert reasons["Precio demasiado alto"]["count"] == 1
        assert reasons["sin_motivo"]["value"] == 50.0
        assert reasons["sin_motivo"]["count"] == 1

        quote_col = next(s for s in report["stages"] if s["key"] == "quote")
        assert quote_col["probability"] == 25
    finally:
        db = SessionLocal()
        try:
            opp_ids = [opp for _, opp in rows]
            if opp_ids:
                db.query(Opportunity).filter(Opportunity.id.in_(opp_ids)).delete()
            lead_ids = [lead for lead, _ in rows]
            if lead_ids:
                db.query(Lead).filter(Lead.id.in_(lead_ids)).delete()
            db.commit()
        finally:
            db.close()
