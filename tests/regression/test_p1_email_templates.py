"""Evals P2: email integrado — plantillas, firma y tracking (T-044).

Cubre el módulo de email integrado:

- ``GET/POST/PATCH/DELETE /email/templates``: CRUD auditado (solo admin para
  mutar; alta idempotente con ``Idempotency-Key``; nombre único).
- ``GET/PUT /email/settings``: firma por instalación y tracking (admin).
- ``POST /email/templates/{id}/send-test``: envía por el pipeline existente
  (spool local sin red) renderizando variables y firma; con tracking genera
  el token, inserta el pixel de apertura en el HTML y reescribe los clics.
- ``GET /email-tracking/{token}/open.png`` y ``/click`` (públicos): registran
  ``open``/``click`` idempotentes (PNG 1x1 válido; 302 al destino).
- Honestidad: sin ``EMAIL_TRACKING_BASE_URL`` no se emiten URLs rotas
  (``email.tracking_skipped``); plantilla inexistente → fallo cerrado
  ``email_template_not_found`` sin fingir éxito.

Hermeticidad D-032: sin red (spool a tmp_path), usuarios/filas únicos por
ejecución y limpieza en ``finally``.
"""

from __future__ import annotations

import json
import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    AuditLog,
    EmailTemplate,
    EmailTrackingEvent,
    User,
)
from app.services.automations import settings as automations_settings

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


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


def _cleanup_template(template_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(EmailTemplate).filter(EmailTemplate.id == template_id).delete()
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


def _tracking_events(token: str | None = None) -> list[EmailTrackingEvent]:
    db = SessionLocal()
    try:
        query = db.query(EmailTrackingEvent)
        if token:
            query = query.filter(EmailTrackingEvent.token == token)
        return query.order_by(EmailTrackingEvent.created_at.asc()).all()
    finally:
        db.close()


def _seed_sent(token: str, *, to: str = "destino@example.invalid") -> None:
    db = SessionLocal()
    try:
        db.add(
            EmailTrackingEvent(
                token=token,
                event_type="sent",
                to=to,
                template_name="Plantilla Demo",
            )
        )
        db.commit()
    finally:
        db.close()


def _cleanup_tracking(token: str) -> None:
    db = SessionLocal()
    try:
        db.query(EmailTrackingEvent).filter(EmailTrackingEvent.token == token).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def email_env(client, auth_headers):
    """Crea comercial y viewer de prueba (el admin es el fixture)."""

    commercial = _unique("comercial")
    viewer = _unique("viewer")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "admin_token": auth_headers["Authorization"].split()[1],
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


def _create_template(client, token, **overrides) -> dict:
    payload = {
        "name": _unique("plantilla"),
        "subject": "Oferta para {{lead.first_name}}",
        "body": (
            "Hola {{lead.first_name}},\n"
            "Tu presupuesto {{quote.id}} de {{store_name}}:\n"
            "https://example.com/presupuesto/{{quote.id}}"
        ),
        "is_active": True,
    }
    payload.update(overrides)
    response = client.post(
        "/email/templates",
        json=payload,
        headers={**_auth(token), **_idem()},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# CRUD de plantillas y settings
# ---------------------------------------------------------------------------


def test_email_template_crud_admin_audited(email_env) -> None:
    client = email_env["client"]
    token = email_env["admin_token"]
    template = _create_template(client, token)
    try:
        assert template["subject"].startswith("Oferta para")
        assert template["is_active"] is True
        assert any(
            event.get("template_id") == template["id"]
            for event in _audit_events("email.template_created")
        )

        listed = client.get("/email/templates", headers=_auth(token)).json()
        assert any(item["id"] == template["id"] for item in listed["items"])
        variable_keys = {variable["key"] for variable in listed["variables"]}
        assert {"store_name", "lead.first_name", "quote.id", "order.id"} <= variable_keys

        updated = client.patch(
            f"/email/templates/{template['id']}",
            json={"subject": "Nuevo asunto", "is_active": False},
            headers=_auth(token),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["subject"] == "Nuevo asunto"
        assert updated.json()["is_active"] is False
        assert any(
            event.get("template_id") == template["id"]
            and "subject" in event.get("changed", [])
            for event in _audit_events("email.template_updated")
        )

        deleted = client.delete(
            f"/email/templates/{template['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 200
        remaining = client.get("/email/templates", headers=_auth(token)).json()
        assert all(item["id"] != template["id"] for item in remaining["items"])
        assert any(
            event.get("template_id") == template["id"]
            for event in _audit_events("email.template_deleted")
        )
    finally:
        _cleanup_template(template["id"])


def test_email_template_rbac_and_validation(email_env) -> None:
    client = email_env["client"]
    token = email_env["admin_token"]
    payload = {
        "name": _unique("solo_admin"),
        "subject": "Asunto",
        "body": "Cuerpo",
    }
    forbidden = client.post(
        "/email/templates",
        json=payload,
        headers=_auth(email_env["commercial_token"]),
    )
    assert forbidden.status_code == 403
    missing_key = client.post(
        "/email/templates",
        json=payload,
        headers=_auth(token),
    )
    assert missing_key.status_code == 428
    first = _create_template(client, token, name=_unique("dup"))
    try:
        duplicate = client.post(
            "/email/templates",
            json={
                "name": first["name"],
                "subject": "Otro",
                "body": "Cuerpo",
            },
            headers={**_auth(token), **_idem()},
        )
        assert duplicate.status_code == 409
    finally:
        _cleanup_template(first["id"])
    # Un viewer puede leer.
    assert client.get("/email/templates", headers=_auth(email_env["viewer_token"])).status_code == 200


def test_email_settings_get_and_put(email_env) -> None:
    client = email_env["client"]
    token = email_env["admin_token"]
    current = client.get("/email/settings", headers=_auth(token)).json()
    assert current["tracking_enabled"] is True

    updated = client.put(
        "/email/settings",
        json={"signature": "Un saludo,\nEquipo BTOP", "tracking_enabled": False},
        headers=_auth(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["signature"] == "Un saludo,\nEquipo BTOP"
    assert updated.json()["tracking_enabled"] is False
    assert any(
        "signature" in event.get("changed", [])
        for event in _audit_events("email.settings_updated")
    )

    forbidden = client.put(
        "/email/settings",
        json={"signature": "no"},
        headers=_auth(email_env["commercial_token"]),
    )
    assert forbidden.status_code == 403
    # Restaurar el default para no contaminar el resto del corpus.
    client.put(
        "/email/settings",
        json={"signature": "", "tracking_enabled": True},
        headers=_auth(token),
    )
    restored = client.get("/email/settings", headers=_auth(token)).json()
    assert restored["tracking_enabled"] is True


# ---------------------------------------------------------------------------
# Envío con plantilla + tracking (spool local, sin red)
# ---------------------------------------------------------------------------


def _send_test(client, token, template_id: str, to: str) -> dict:
    response = client.post(
        f"/email/templates/{template_id}/send-test",
        json={"to": to},
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_send_templated_email_spool_with_tracking(
    email_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(
        automations_settings, "EMAIL_TRACKING_BASE_URL", "https://bridge.example", raising=False
    )
    client = email_env["client"]
    token = email_env["admin_token"]
    template = _create_template(
        client,
        token,
        body=(
            "<html><body><p>Hola {{lead.first_name}}, tu presupuesto "
            "{{quote.id}} de {{store_name}}:</p>\n"
            '<a href="https://example.com/presupuesto/{{quote.id}}">Ver</a>'
            "</body></html>"
        ),
    )
    try:
        result = _send_test(client, token, template["id"], "cliente@example.invalid")
        assert result["provider"] == "local_spool"
        assert result["accepted"] is False  # el spool nunca afirma entrega
        assert result["delivery_status"] == "queued_for_manual_delivery"
        assert result["tracking_token"] and result["tracking_token"].startswith("tk-")

        # El spool contiene el cuerpo renderizado con clics reescritos y el
        # HTML con el pixel de apertura.
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert "Cliente de prueba" in payload["body"]
        assert "QT-DEMO" in payload["body"]
        assert payload["tracking_token"] == result["tracking_token"]
        assert payload["html"] is not None
        assert f"/email-tracking/{result['tracking_token']}/open.png" in payload["html"]
        from urllib.parse import quote

        click_url = f"https://bridge.example/email-tracking/{result['tracking_token']}/click"
        assert click_url in payload["html"]
        # El destino original queda codificado en el parámetro ``u``.
        assert quote("https://example.com/presupuesto", safe="") in payload["html"]

        # El evento 'sent' quedó registrado con el mapa token → destinatario.
        sent = [
            event
            for event in _tracking_events(result["tracking_token"])
            if event.event_type == "sent"
        ]
        assert len(sent) == 1
        assert sent[0].to == "cliente@example.invalid"
        assert sent[0].template_name == template["name"]
        assert any(
            event.get("tracking_token") == result["tracking_token"]
            for event in _audit_events("email.template_test_sent")
        )
    finally:
        _cleanup_template(template["id"])
        for event in _tracking_events():
            _cleanup_tracking(event.token)


def test_send_templated_email_skips_tracking_without_base_url(
    email_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(automations_settings, "AUTOMATION_EMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(automations_settings, "EMAIL_TRACKING_BASE_URL", "", raising=False)
    client = email_env["client"]
    token = email_env["admin_token"]
    template = _create_template(
        client, token, body="Mira esto: https://example.com/oferta"
    )
    try:
        result = _send_test(client, token, template["id"], "cliente@example.invalid")
        assert result["tracking_token"] is None
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        # Sin base URL no se emiten URLs rotas: el enlace queda intacto.
        assert "https://example.com/oferta" in payload["body"]
        assert "/email-tracking/" not in payload["body"]
        assert any(
            event.get("reason") == "sin_base_url"
            for event in _audit_events("email.tracking_skipped")
        )
    finally:
        _cleanup_template(template["id"])


def test_send_templated_email_unknown_template_is_honest(email_env) -> None:
    from app.services.email_service import send_templated_email

    db = SessionLocal()
    try:
        result, token = send_templated_email(
            db,
            template_name="no-existe",
            to="x@example.invalid",
            variables={"lead.first_name": "X"},
        )
        assert result.accepted is False
        assert "email_template_not_found:no-existe" in (result.error or "")
        assert token is None
        assert any(
            event.get("template_name") == "no-existe"
            for event in _audit_events("email.template_not_found")
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tracking público (pixel y redirect)
# ---------------------------------------------------------------------------


def test_tracking_open_png_registers_idempotently(email_env) -> None:
    client = email_env["client"]
    token = "tk-open-test"
    _seed_sent(token)
    try:
        first = client.get(f"/email-tracking/{token}/open.png")
        assert first.status_code == 200, first.text
        assert first.headers["content-type"].startswith("image/png")
        body = first.content
        assert body.startswith(b"\x89PNG\r\n\x1a\n")  # magic bytes
        assert b"IEND" in body  # chunk de cierre válido

        second = client.get(f"/email-tracking/{token}/open.png")
        assert second.status_code == 200
        opens = [
            event
            for event in _tracking_events(token)
            if event.event_type == "open"
        ]
        assert len(opens) == 1  # la recarga no duplica
        assert opens[0].to == "destino@example.invalid"
    finally:
        _cleanup_tracking(token)


def test_tracking_click_redirects_and_registers(email_env) -> None:
    from urllib.parse import quote

    client = email_env["client"]
    token = "tk-click-test"
    _seed_sent(token)
    destination = "https://example.com/oferta?utm=a&b=c"
    try:
        response = client.get(
            f"/email-tracking/{token}/click?u={quote(destination, safe='')}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == destination
        clicks = [
            event
            for event in _tracking_events(token)
            if event.event_type == "click"
        ]
        assert len(clicks) == 1
        assert clicks[0].url == destination

        # Idempotente: un segundo clic no duplica.
        client.get(
            f"/email-tracking/{token}/click?u={quote(destination, safe='')}",
            follow_redirects=False,
        )
        assert len(
            [e for e in _tracking_events(token) if e.event_type == "click"]
        ) == 1

        # URL no http → 422; token desconocido → 404.
        assert client.get(f"/email-tracking/{token}/click?u=javascript:alert(1)").status_code == 422
        assert (
            client.get(
                "/email-tracking/tk-desconocido/click?u=https%3A%2F%2Fexample.com"
            ).status_code
            == 404
        )
    finally:
        _cleanup_tracking(token)


def test_tracking_endpoints_public_and_rbac_on_events(email_env) -> None:
    """El pixel/redirect son públicos; el listado de eventos es solo admin."""

    client = email_env["client"]
    token = "tk-public-test"
    _seed_sent(token)
    try:
        assert client.get(f"/email-tracking/{token}/open.png").status_code == 200
        assert (
            client.get("/email/tracking/events", headers=_auth(email_env["viewer_token"])).status_code
            == 403
        )
        events = client.get(
            "/email/tracking/events", headers=_auth(email_env["admin_token"])
        ).json()
        assert any(item["token"] == token for item in events["items"])
    finally:
        _cleanup_tracking(token)
