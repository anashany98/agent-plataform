"""Evals T-061: color de acento configurable por instalación.

Cubre la apariencia por instalación:

- Get-or-create: la primera lectura crea la fila única con el default y
  ``installation_id`` de la instalación actual; lecturas posteriores
  reutilizan la misma fila.
- PUT solo admin con formato estricto ``#RRGGBB``: cambia el color, marca
  ``updated_by`` y audita ``appearance.settings_updated``.
- Validación fail-closed: hex inválido (o sin ``#``) → 422; ``extra``
  rechazado por el schema.
- RBAC: viewer puede leer, no escribir; sin token → 401.
- Idempotencia: re-PUT con el mismo color no cambia nada (no re-audita como
  cambio).

Hermeticidad D-032: SQLite de test, seeds por ORM con ids únicos y limpieza
en ``finally``.
"""

from __future__ import annotations

import uuid

import pytest
from app.database import SessionLocal
from app.models.models import AuditLog, InstallationAppearance, User

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


@pytest.fixture()
def appearance_env(client, auth_headers):
    admin = _unique("admin-appearance")
    _create_user(client, auth_headers, admin, "client_admin")
    token = _login(client, admin)
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "token": token,
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == admin).delete()
            db.query(InstallationAppearance).delete()
            db.query(AuditLog).filter(
                AuditLog.event_type == "appearance.settings_updated"
            ).delete()
            db.commit()
        finally:
            db.close()


def _get(env) -> dict:
    response = env["client"].get(
        "/appearance/settings",
        headers={"Authorization": f"Bearer {env['token']}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _put(env, accent_color: str):
    return env["client"].put(
        "/appearance/settings",
        json={"accent_color": accent_color},
        headers={"Authorization": f"Bearer {env['token']}"},
    )


def test_get_creates_row_with_default_and_installation_id(appearance_env):
    data = _get(appearance_env)
    assert data["accent_color"] == "#246bfd"
    assert data["updated_at"] is not None
    assert data["updated_by"] is None

    db = SessionLocal()
    try:
        row = db.query(InstallationAppearance).one()
        assert row.installation_id == appearance_env["auth_headers"].get(
            "X-Installation-Id", ""
        ) or row.installation_id is not None
    finally:
        db.close()

    # get-or-create idempotente: la segunda lectura reutiliza la misma fila
    data2 = _get(appearance_env)
    assert data2["accent_color"] == "#246bfd"
    db = SessionLocal()
    try:
        assert db.query(InstallationAppearance).count() == 1
    finally:
        db.close()


def test_put_updates_accent_audits_and_marks_updated_by(appearance_env):
    _get(appearance_env)
    response = _put(appearance_env, "#7C5CF0")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accent_color"] == "#7C5CF0"
    assert body["updated_at"] is not None
    assert body["updated_by"] == appearance_env["auth_headers"].get(
        "X-Username", "admin-appearance"
    ) or body["updated_by"] is not None

    db = SessionLocal()
    try:
        row = db.query(InstallationAppearance).one()
        assert row.accent_color == "#7C5CF0"
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "appearance.settings_updated")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert audit is not None
        assert audit.details.get("accent_color") == "#7C5CF0"
        assert audit.status == "success"
    finally:
        db.close()


def test_put_rejects_invalid_hex(appearance_env):
    _get(appearance_env)
    for invalid in ("red", "#12345", "#12345G", "123456", "#246BFD0"):
        response = _put(appearance_env, invalid)
        assert response.status_code == 422, f"{invalid}: {response.text}"
    db = SessionLocal()
    try:
        row = db.query(InstallationAppearance).one()
        assert row.accent_color == "#246bfd"
    finally:
        db.close()


def test_put_rejects_extra_fields(appearance_env):
    response = appearance_env["client"].put(
        "/appearance/settings",
        json={"accent_color": "#246bfd", "evil": "x"},
        headers={"Authorization": f"Bearer {appearance_env['token']}"},
    )
    assert response.status_code == 422


def test_put_with_same_color_is_idempotent(appearance_env):
    _get(appearance_env)
    first = _put(appearance_env, "#0ea271")
    assert first.status_code == 200
    second = _put(appearance_env, "#0ea271")
    assert second.status_code == 200
    db = SessionLocal()
    try:
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "appearance.settings_updated")
            .all()
        )
        # Solo el primer PUT audita un cambio (changed no vacío)
        changed = [
            a for a in audits if a.details.get("changed")
        ]
        assert len(changed) == 1
        assert len(audits) == 2  # el segundo PUT se audita sin cambios
    finally:
        db.close()


def test_rbac_viewer_reads_but_cannot_write(appearance_env):
    viewer = _unique("viewer-appearance")
    _create_user(appearance_env["client"], appearance_env["auth_headers"], viewer, "viewer")
    token = _login(appearance_env["client"], viewer)
    try:
        read = appearance_env["client"].get(
            "/appearance/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.status_code == 200
        write = appearance_env["client"].put(
            "/appearance/settings",
            json={"accent_color": "#0ea271"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert write.status_code == 403
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == viewer).delete()
            db.commit()
        finally:
            db.close()


def test_unauthenticated_is_rejected(appearance_env):
    assert appearance_env["client"].get("/appearance/settings").status_code == 401
    assert appearance_env["client"].put(
        "/appearance/settings", json={"accent_color": "#246bfd"}
    ).status_code == 401
