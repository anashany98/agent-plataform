"""Evals Fase B (bloque 4): RBAC del portal — backend como autoridad.

Cubre T-024 / PR-10:

- ``login`` devuelve el rol del usuario para que el portal pueda renderizar
  por rol sin decidir permisos por su cuenta.
- ``GET /dashboard`` es role-aware: ``viewer`` recibe el resumen básico
  (sin aprobaciones pendientes), operadores reciben ``pending_approvals``
  y ``permissions`` declaradas por el backend; nunca filtra datos ajenos.
- ``GET/POST /leads`` y ``GET /opportunities`` (CRM local, Fase B) exigen
  rol operador: ``viewer`` recibe 403, ``commercial``/admin pueden listar
  y crear con validación (email inválido 422, duplicado 409).

Hermeticidad D-032: los usuarios de prueba se crean y se limpian dentro
de la instalación de test; ningún rol hereda credenciales reales.
"""

from __future__ import annotations

import uuid

import pytest

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
def rbac_users(client, auth_headers):
    """Crea un comercial y un viewer de prueba y los limpia al terminar."""
    from app.database import SessionLocal
    from app.models.models import User

    commercial = _unique("comercial")
    viewer = _unique("viewer")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")

    commercial_token = _login(client, commercial)["access_token"]
    viewer_token = _login(client, viewer)["access_token"]
    yield {
        "commercial_token": commercial_token,
        "viewer_token": viewer_token,
        "usernames": (commercial, viewer),
    }

    db = SessionLocal()
    try:
        db.query(User).filter(
            User.username.in_([commercial, viewer])
        ).delete()
        db.commit()
    finally:
        db.close()


def test_login_returns_role(client, auth_headers, rbac_users) -> None:
    """El login devuelve el rol; sin él el portal no puede renderizar por rol."""

    body = _login(client, rbac_users["usernames"][0])
    assert body.get("role") == "commercial"
    assert body.get("username") == rbac_users["usernames"][0]


def test_dashboard_is_role_aware(client, auth_headers, rbac_users) -> None:
    """Viewer ve resumen básico; comercial/admin ven aprobaciones y permisos."""

    viewer = client.get("/dashboard", headers=_auth(rbac_users["viewer_token"]))
    assert viewer.status_code == 200, viewer.text
    viewer_body = viewer.json()
    assert viewer_body["role"] == "viewer"
    assert viewer_body["permissions"]["approve"] is False
    assert viewer_body["permissions"]["manage_users"] is False
    assert "pending_approvals" not in viewer_body["counts"], (
        "Un viewer no debe recibir el conteo de aprobaciones pendientes"
    )
    assert "products" in viewer_body["counts"]
    assert "customers" in viewer_body["counts"]

    commercial = client.get(
        "/dashboard", headers=_auth(rbac_users["commercial_token"])
    )
    assert commercial.status_code == 200, commercial.text
    commercial_body = commercial.json()
    assert commercial_body["role"] == "commercial"
    assert commercial_body["permissions"]["approve"] is True
    assert commercial_body["permissions"]["manage_leads"] is True
    assert commercial_body["permissions"]["manage_users"] is False
    assert "pending_approvals" in commercial_body["counts"]

    admin = client.get("/dashboard", headers=auth_headers)
    assert admin.status_code == 200, admin.text
    admin_body = admin.json()
    assert admin_body["permissions"]["manage_users"] is True
    assert admin_body["permissions"]["view_costs"] is True
    assert admin_body["permissions"]["import_catalog"] is True


def test_dashboard_is_available_to_every_reader(client, rbac_users) -> None:
    """Cualquier rol lector obtiene 200 (la carga parcial del portal lo exige)."""

    response = client.get("/dashboard", headers=_auth(rbac_users["viewer_token"]))
    assert response.status_code == 200, response.text
    assert response.json()["installation_id"]


def test_leads_require_operator_role(client, rbac_users) -> None:
    """Un viewer no puede listar ni crear leads (403)."""

    get = client.get("/leads", headers=_auth(rbac_users["viewer_token"]))
    assert get.status_code == 403, get.text

    post = client.post(
        "/leads",
        json={"email": "viewer@example.invalid", "first_name": "No"},
        headers=_auth(rbac_users["viewer_token"]),
    )
    assert post.status_code == 403, post.text


def test_commercial_can_create_and_list_leads(client, rbac_users) -> None:
    """El comercial crea y lista leads; duplicado 409 y email inválido 422."""

    from app.database import SessionLocal
    from app.models.models import Lead

    email = f"{_unique('lead')}@example.invalid"
    created = client.post(
        "/leads",
        json={
            "email": email,
            "first_name": "Cliente Portal",
            "phone": "+34600111222",
            "company_name": "Portal Corp",
        },
        headers=_auth(rbac_users["commercial_token"]),
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["email"] == email
    assert created_body["status"] == "new"

    listed = client.get("/leads", headers=_auth(rbac_users["commercial_token"]))
    assert listed.status_code == 200, listed.text
    assert any(row["email"] == email for row in listed.json())

    duplicate = client.post(
        "/leads",
        json={"email": email.upper(), "first_name": "Duplicado"},
        headers=_auth(rbac_users["commercial_token"]),
    )
    assert duplicate.status_code == 409, duplicate.text

    invalid = client.post(
        "/leads",
        json={"email": "no-es-un-email", "first_name": "Malo"},
        headers=_auth(rbac_users["commercial_token"]),
    )
    assert invalid.status_code == 422, invalid.text

    db = SessionLocal()
    try:
        db.query(Lead).filter(Lead.email == email).delete()
        db.commit()
    finally:
        db.close()


def test_opportunities_require_operator_role(client, rbac_users) -> None:
    """Viewer 403; comercial puede listar oportunidades."""

    get = client.get("/opportunities", headers=_auth(rbac_users["viewer_token"]))
    assert get.status_code == 403, get.text

    listed = client.get(
        "/opportunities", headers=_auth(rbac_users["commercial_token"])
    )
    assert listed.status_code == 200, listed.text
    assert isinstance(listed.json(), list)


def test_portal_rbac_never_leaks_other_installation_rows(
    client, rbac_users, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los leads listados están aislados por instalación (P0-006)."""

    from app.database import SessionLocal
    from app.installation_context import installation_scope
    from app.models.models import Lead

    email = f"{_unique('otra-inst')}@example.invalid"
    db = SessionLocal()
    try:
        with installation_scope("otra-instalacion"):
            db.add(
                Lead(
                    email=email,
                    first_name="Ajeno",
                    source="local",
                    status="new",
                )
            )
            db.commit()
        listed = client.get(
            "/leads", headers=_auth(rbac_users["commercial_token"])
        )
        assert listed.status_code == 200
        assert email not in {row["email"] for row in listed.json()}, (
            "Un lead de otra instalación no debe aparecer en el listado"
        )
    finally:
        with installation_scope("otra-instalacion"):
            db.query(Lead).filter(Lead.email == email).delete()
            db.commit()
        db.close()
