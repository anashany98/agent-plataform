"""Evals T-055: campañas segmentadas del CRM (P2).

Cubre el módulo de campañas segmentadas del plan CRM:

- CRUD con RBAC y auditoría: solo admin crea/edita/elimina; operador+ lee;
  nombre duplicado → 409; plantilla inactiva/inexistente → 422 en alta.
- Segmentación determinista: filtros por score, fuente, comercial asignado,
  cuenta y campos personalizados (eq/gt/contains/is_set…), campo inexistente
  → fail-closed (ningún lead cumple).
- Preview: cuenta y muestra de leads SIN materializar.
- Envío: materializa destinatarios y los manda por ``send_templated_email``
  (spool local sin red, con tracking por destinatario); variables renderizadas
  en el spool; leads ``email_opt_out`` → ``skipped``; plantilla desactivada →
  ``failed`` honesto; reenvío idempotente (``already_sent``, sin duplicados).
- Estadísticas: total/sent/failed/skipped y aperturas/clics derivados de
  ``EmailTrackingEvent`` por token.
- Reglas de ciclo: borrar una enviada → 409; cancelar → borrado lógico.

Hermeticidad D-032: sin red (spool a ``tmp_path``), usuarios y filas únicos
por ejecución con limpieza en ``finally``.
"""

from __future__ import annotations

import json
import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    AuditLog,
    Campaign,
    CampaignRecipient,
    EmailTemplate,
    EmailTrackingEvent,
    Lead,
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


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"camp-{uuid.uuid4().hex}"}


@pytest.fixture()
def campaign_env(client, auth_headers):
    """Crea comercial, viewer y admin de prueba; limpia al terminar."""
    commercial = _unique("comercial-cmp")
    viewer = _unique("viewer-cmp")
    admin = _unique("admin-cmp")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    _create_user(client, auth_headers, admin, "client_admin")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "admin_token": _login(client, admin)["access_token"],
        "commercial_token": _login(client, commercial)["access_token"],
        "viewer_token": _login(client, viewer)["access_token"],
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


def _seed_template(*, name: str | None = None, is_active: bool = True) -> str:
    """Siembra una plantilla activa (vía ORM) y devuelve su nombre."""
    db = SessionLocal()
    try:
        template_name = name or _unique("tpl-cmp")
        existing = (
            db.query(EmailTemplate).filter(EmailTemplate.name == template_name).first()
        )
        if existing is None:
            db.add(
                EmailTemplate(
                    name=template_name,
                    subject="Oferta {{store_name}} para {{lead.first_name}}",
                    body=(
                        "Hola {{lead.first_name}},\n"
                        "Tu enlace: https://example.com/oferta\n"
                        "--\nEquipo"
                    ),
                    is_active=is_active,
                )
            )
            db.commit()
        return template_name
    finally:
        db.close()


def _cleanup_template(name: str) -> None:
    db = SessionLocal()
    try:
        db.query(EmailTemplate).filter(EmailTemplate.name == name).delete()
        db.commit()
    finally:
        db.close()


def _seed_lead(
    *,
    source: str = "web",
    first_name: str = "Cliente Campaña",
    email_opt_out: bool = False,
    assigned_to: str | None = None,
    account_id: str | None = None,
    created_days_ago: int | None = None,
) -> str:
    import datetime

    db = SessionLocal()
    try:
        created_at = None
        if created_days_ago is not None:
            created_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
                days=created_days_ago
            )
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name=first_name,
            company_name="Campaña Corp",
            source=source,
            status="new",
            assigned_to=assigned_to,
            account_id=account_id,
            email_opt_out=email_opt_out,
            created_at=created_at,
        )
        db.add(lead)
        db.commit()
        return lead.id
    finally:
        db.close()


def _cleanup_lead(lead_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Lead).filter(Lead.id == lead_id).delete()
        db.commit()
    finally:
        db.close()


def _seed_custom_field(key: str, field_type: str = "text") -> str:
    """Siembra una definición de campo personalizado y devuelve su id."""
    db = SessionLocal()
    try:
        from app.models.models import CustomFieldDefinition

        definition = CustomFieldDefinition(
            id=f"field-{uuid.uuid4().hex[:8]}",
            key=key,
            label=key,
            entity_type="lead",
            field_type=field_type,
            visibility="all",
            position=0,
            is_active=True,
        )
        db.add(definition)
        db.commit()
        return definition.id
    finally:
        db.close()


def _set_custom_value(field_id: str, entity_id: str, value) -> None:
    """Upsert del valor de un campo personalizado sobre un lead."""
    db = SessionLocal()
    try:
        from app.models.models import CustomFieldValue

        row = (
            db.query(CustomFieldValue)
            .filter(
                CustomFieldValue.field_id == field_id,
                CustomFieldValue.entity_type == "lead",
                CustomFieldValue.entity_id == entity_id,
            )
            .first()
        )
        if row is None:
            row = CustomFieldValue(
                id=f"value-{uuid.uuid4().hex[:8]}",
                field_id=field_id,
                entity_type="lead",
                entity_id=entity_id,
                value_json=value,
            )
            db.add(row)
        else:
            row.value_json = value
        db.commit()
    finally:
        db.close()


def _cleanup_custom(field_id: str) -> None:
    db = SessionLocal()
    try:
        from app.models.models import (
            CustomFieldDefinition,
            CustomFieldValue,
        )

        db.query(CustomFieldValue).filter(CustomFieldValue.field_id == field_id).delete()
        db.query(CustomFieldDefinition).filter(
            CustomFieldDefinition.id == field_id
        ).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_campaign(campaign_id: str | None) -> None:
    if not campaign_id:
        return
    db = SessionLocal()
    try:
        db.query(CampaignRecipient).filter(
            CampaignRecipient.campaign_id == campaign_id
        ).delete()
        db.query(Campaign).filter(Campaign.id == campaign_id).delete()
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


def _create_campaign(
    client,
    token: str,
    template_name: str,
    *,
    segment: dict | None = None,
    name: str | None = None,
) -> dict:
    response = client.post(
        "/campaigns",
        json={
            "name": name or _unique("campaña"),
            "description": "Campaña de prueba E2E",
            "template_name": template_name,
            "segment": segment,
        },
        headers={**_auth(token), **_idem()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_campaign_admin_only_and_audit(campaign_env) -> None:
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    try:
        campaign = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={"score_min": 20, "sources": ["web"]},
        )
        campaign_id = campaign["id"]
        assert campaign["status"] == "draft"
        assert campaign["segment"]["score_min"] == 20
        assert campaign["template_name"] == template_name
        assert campaign["stats"] == {
            "total": 0,
            "sent": 0,
            "failed": 0,
            "queued": 0,
            "skipped": 0,
            "pending": 0,
            "opened": 0,
            "clicked": 0,
            "bounced": 0,
            "opened_rate": 0.0,
            "clicked_rate": 0.0,
            "bounce_rate": 0.0,
        }
        # Auditoría
        assert any(
            row.get("campaign_id") == campaign_id for row in _audit_events("campaign.created")
        )
        # RBAC: comercial y viewer no crean
        for role_token in (
            campaign_env["commercial_token"],
            campaign_env["viewer_token"],
        ):
            response = client.post(
                "/campaigns",
                json={
                    "name": _unique("campaña"),
                    "template_name": template_name,
                },
                headers={**_auth(role_token), **_idem()},
            )
            assert response.status_code == 403, response.text
        # Nombre duplicado → 409
        duplicate = client.post(
            "/campaigns",
            json={
                "name": campaign["name"],
                "template_name": template_name,
            },
            headers={**_auth(admin_token), **_idem()},
        )
        assert duplicate.status_code == 409, duplicate.text
        # Plantilla inexistente → 422
        missing = client.post(
            "/campaigns",
            json={
                "name": _unique("campaña"),
                "template_name": "plantilla-inexistente-xyz",
            },
            headers={**_auth(admin_token), **_idem()},
        )
        assert missing.status_code == 422, missing.text
    finally:
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)


def test_segment_preview_filters_by_score_source_and_custom(campaign_env) -> None:
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    lead_ids: list[str] = []
    # Cada test acota su segmento a una cuenta única para no casar leads de
    # otras suites (la BD SQLite es compartida entre todos los tests).
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    field_key = f"sector-{uuid.uuid4().hex[:6]}"
    field_id = _seed_custom_field(field_key, "text")
    try:
        # web con sector=logistica (fuente web, custom eq logistica)
        lead_web = _seed_lead(source="web", first_name="Web Log", account_id=account_id)
        _set_custom_value(field_id, lead_web, "logistica")
        lead_ids.append(lead_web)
        # chat con sector=retail
        lead_chat = _seed_lead(source="chat", first_name="Chat Retail", account_id=account_id)
        _set_custom_value(field_id, lead_chat, "retail")
        lead_ids.append(lead_chat)
        # web con sector=retail (fuente web, custom NO logistica)
        lead_web_retail = _seed_lead(
            source="web", first_name="Web Retail", account_id=account_id
        )
        _set_custom_value(field_id, lead_web_retail, "retail")
        lead_ids.append(lead_web_retail)

        campaign = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={
                "account_ids": [account_id],
                "sources": ["web"],
                "custom_fields": [
                    {"key": field_key, "op": "eq", "value": "logistica"}
                ],
            },
        )
        campaign_id = campaign["id"]
        preview = client.post(
            f"/campaigns/{campaign_id}/preview",
            headers=_auth(campaign_env["commercial_token"]),  # operador+ puede leer
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["count"] == 1
        assert body["sample"][0]["id"] == lead_web

        # Segmento por score: un lead antiguo (sin puntos por antigüedad,
        # web=30) queda fuera de score_min=40; los recientes (web=50, chat=60)
        # cumplen. Acotado a la cuenta única.
        lead_old = _seed_lead(
            source="web",
            first_name="Web Vieja",
            account_id=account_id,
            created_days_ago=200,
        )
        lead_ids.append(lead_old)
        high_score = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={"account_ids": [account_id], "score_min": 40},
        )
        try:
            preview2 = client.post(
                f"/campaigns/{high_score['id']}/preview",
                headers=_auth(admin_token),
            )
            assert preview2.status_code == 200
            body2 = preview2.json()
            assert body2["count"] == 3
            ids = {row["id"] for row in body2["sample"]}
            assert lead_web in ids
            assert lead_chat in ids
            assert lead_old not in ids
        finally:
            _cleanup_campaign(high_score["id"])

        # Campo inexistente → fail-closed: nadie cumple (aunque la cuenta
        # coincida, el criterio de campo falla cerrado).
        unknown_field = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={
                "account_ids": [account_id],
                "custom_fields": [{"key": "no-existe", "op": "eq", "value": "x"}],
            },
        )
        try:
            preview3 = client.post(
                f"/campaigns/{unknown_field['id']}/preview",
                headers=_auth(admin_token),
            )
            assert preview3.status_code == 200
            assert preview3.json()["count"] == 0
        finally:
            _cleanup_campaign(unknown_field["id"])
    finally:
        for lead_id in lead_ids:
            _cleanup_lead(lead_id)
        _cleanup_custom(field_id)
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)

def test_send_materializes_recipients_with_tracking(
    campaign_env, tmp_path, monkeypatch
) -> None:
    from app.services.automations import settings as automations_settings

    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(
        automations_settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    lead_ids: list[str] = []
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    try:
        lead_a = _seed_lead(source="web", first_name="Ana Campaña", account_id=account_id)
        lead_b = _seed_lead(
            source="chat", first_name="Bruno Campaña", account_id=account_id
        )
        lead_ids.extend([lead_a, lead_b])

        campaign = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={"account_ids": [account_id]},
        )
        campaign_id = campaign["id"]
        sent = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["recipients"] == 2
        assert body["sent"] == 2
        assert body["failed"] == 0
        assert body["skipped"] == 0

        # Destinatarios materializados con token de tracking propio
        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        assert detail.status_code == 200, detail.text
        recipients = detail.json()["recipients"]
        assert len(recipients) == 2
        assert all(recipient["status"] == "sent" for recipient in recipients)
        tokens = [recipient["tracking_token"] for recipient in recipients]
        assert all(token and token.startswith("tk-") for token in tokens)
        assert len(set(tokens)) == 2  # token único por destinatario

        # Eventos sent registrados por token
        db = SessionLocal()
        try:
            sent_events = (
                db.query(EmailTrackingEvent)
                .filter(EmailTrackingEvent.event_type == "sent")
                .all()
            )
            sent_tokens = {event.token for event in sent_events}
            assert set(tokens) <= sent_tokens
        finally:
            db.close()

        # Spool local con variables renderizadas (nombre + tienda)
        files = list(tmp_path.glob("*.json"))
        assert len(files) >= 2
        rendered_names = []
        for file in files:
            payload = json.loads(file.read_text(encoding="utf-8"))
            rendered_names.append(payload.get("subject", ""))
        assert any("Ana Campaña" in subject for subject in rendered_names)
        assert any("Bruno Campaña" in subject for subject in rendered_names)

        # Auditoría del envío
        assert any(
            row.get("campaign_id") == campaign_id and row.get("sent") == 2
            for row in _audit_events("campaign.send_finished")
        )
    finally:
        for lead_id in lead_ids:
            _cleanup_lead(lead_id)
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)


def test_send_skips_opted_out_and_is_idempotent(campaign_env, tmp_path, monkeypatch) -> None:
    from app.services.automations import settings as automations_settings

    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(
        automations_settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    lead_ids: list[str] = []
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    try:
        opted_out = _seed_lead(
            source="web", first_name="Opt Out", email_opt_out=True, account_id=account_id
        )
        normal = _seed_lead(source="web", first_name="Normal", account_id=account_id)
        lead_ids.extend([opted_out, normal])

        campaign = _create_campaign(
            client, admin_token, template_name, segment={"account_ids": [account_id]}
        )
        campaign_id = campaign["id"]
        sent = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["recipients"] == 2
        assert body["sent"] == 1
        assert body["skipped"] == 1

        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        by_lead = {recipient["lead_id"]: recipient for recipient in detail.json()["recipients"]}
        assert by_lead[opted_out]["status"] == "skipped"
        assert by_lead[opted_out]["error"] == "email_opt_out"
        assert by_lead[normal]["status"] == "sent"

        # Reenvío idempotente: no duplica destinatarios
        resend = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert resend.status_code == 200, resend.text
        assert resend.json()["already_sent"] is True
        detail2 = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        assert len(detail2.json()["recipients"]) == 2
        assert detail2.json()["stats"]["total"] == 2
    finally:
        for lead_id in lead_ids:
            _cleanup_lead(lead_id)
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)


def test_send_fails_honestly_when_template_inactive(
    campaign_env, tmp_path, monkeypatch
) -> None:
    from app.services.automations import settings as automations_settings

    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template(is_active=False)
    campaign_id = None
    lead_id = None
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    try:
        lead_id = _seed_lead(source="web", account_id=account_id)
        # La plantilla inactiva no es válida ni siquiera al crear la campaña
        response = client.post(
            "/campaigns",
            json={
                "name": _unique("campaña"),
                "template_name": template_name,
            },
            headers={**_auth(admin_token), **_idem()},
        )
        assert response.status_code == 422, response.text

        # Activar la plantilla, crear la campaña y desactivarla antes del envío
        db = SessionLocal()
        try:
            template = (
                db.query(EmailTemplate)
                .filter(EmailTemplate.name == template_name)
                .first()
            )
            template.is_active = True
            db.commit()
        finally:
            db.close()
        campaign = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={"account_ids": [account_id]},
        )
        campaign_id = campaign["id"]
        db = SessionLocal()
        try:
            template = (
                db.query(EmailTemplate)
                .filter(EmailTemplate.name == template_name)
                .first()
            )
            template.is_active = False
            db.commit()
        finally:
            db.close()

        sent = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["recipients"] == 1
        assert body["failed"] == 1
        assert body["sent"] == 0
        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        assert detail.json()["recipients"][0]["status"] == "failed"
        assert "template_not_found" in detail.json()["recipients"][0]["error"]
    finally:
        if lead_id:
            _cleanup_lead(lead_id)
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)


def test_campaign_stats_opened_clicked_derived_from_tracking(
    campaign_env, tmp_path, monkeypatch
) -> None:
    from app.services.automations import settings as automations_settings

    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(
        automations_settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    lead_ids: list[str] = []
    tokens: list[str] = []
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    try:
        lead_ids.append(
            _seed_lead(source="web", first_name="Rastreado", account_id=account_id)
        )
        campaign = _create_campaign(
            client,
            admin_token,
            template_name,
            segment={"account_ids": [account_id]},
        )
        campaign_id = campaign["id"]
        sent = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert sent.status_code == 200
        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        tokens = [r["tracking_token"] for r in detail.json()["recipients"]]
        assert tokens and tokens[0]

        # Simula apertura y clic por el pixel/redirect (mismo token, idempotente)
        db = SessionLocal()
        try:
            db.add(
                EmailTrackingEvent(
                    token=tokens[0], event_type="open", to="x@example.invalid"
                )
            )
            db.add(
                EmailTrackingEvent(
                    token=tokens[0], event_type="click", url="https://example.com/oferta"
                )
            )
            db.commit()
        finally:
            db.close()

        detail2 = client.get(f"/campaigns/{campaign_id}", headers=_auth(admin_token))
        assert detail2.json()["stats"]["opened"] == 1
        assert detail2.json()["stats"]["clicked"] == 1
        assert detail2.json()["recipients"][0]["opened"] is True
        assert detail2.json()["recipients"][0]["clicked"] is True

        # El viewer no tiene acceso a campañas (lectura = operador+)
        denied = client.get("/campaigns", headers=_auth(campaign_env["viewer_token"]))
        assert denied.status_code == 403, denied.text
        # Listado también expone las stats
        listing = client.get(
            "/campaigns", headers=_auth(campaign_env["commercial_token"])
        )
        assert listing.status_code == 200
        row = next(c for c in listing.json()["campaigns"] if c["id"] == campaign_id)
        assert row["stats"]["opened"] == 1
    finally:
        db = SessionLocal()
        try:
            if tokens:
                db.query(EmailTrackingEvent).filter(
                    EmailTrackingEvent.token == tokens[0]
                ).delete()
            db.commit()
        finally:
            db.close()
        for lead_id in lead_ids:
            _cleanup_lead(lead_id)
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)


def test_campaign_lifecycle_rules(campaign_env) -> None:
    client = campaign_env["client"]
    admin_token = campaign_env["admin_token"]
    template_name = _seed_template()
    campaign_id = None
    try:
        campaign = _create_campaign(client, admin_token, template_name)
        campaign_id = campaign["id"]

        # Borrar (cancelar) un draft funciona y es un borrado lógico
        deleted = client.delete(
            f"/campaigns/{campaign_id}", headers=_auth(admin_token)
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "cancelled"

        # Una cancelada no se puede enviar
        send = client.post(
            f"/campaigns/{campaign_id}/send", headers=_auth(admin_token)
        )
        assert send.status_code == 409, send.text

        # Una enviada no se puede editar ni borrar
        campaign2 = _create_campaign(client, admin_token, template_name)
        try:
            db = SessionLocal()
            try:
                row = db.query(Campaign).filter(Campaign.id == campaign2["id"]).first()
                row.status = "sent"
                db.commit()
            finally:
                db.close()
            edit = client.patch(
                f"/campaigns/{campaign2['id']}",
                json={"description": "intento de edición"},
                headers=_auth(admin_token),
            )
            assert edit.status_code == 409, edit.text
            delete_sent = client.delete(
                f"/campaigns/{campaign2['id']}", headers=_auth(admin_token)
            )
            assert delete_sent.status_code == 409, delete_sent.text
        finally:
            _cleanup_campaign(campaign2["id"])

        # RBAC de escritura en PATCH/DELETE
        patch = client.patch(
            f"/campaigns/{campaign_id}",
            json={"description": "x"},
            headers=_auth(campaign_env["commercial_token"]),
        )
        assert patch.status_code == 403, patch.text
    finally:
        _cleanup_campaign(campaign_id)
        _cleanup_template(template_name)
