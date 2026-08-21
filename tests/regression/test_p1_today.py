"""Evals de la pantalla «Hoy» (tarjetas accionables del portal).

``GET /today`` agrega en una sola llamada (solo lectura) los conteos de las
cuatro tarjetas accionables:

- ``pending_approvals``: propuestas pendientes (solo roles operadores; el
  viewer recibe ``count=None`` por RBAC, igual que ``/dashboard``).
- ``campaigns_pending_retry``: campañas en estado ``pending_retry``.
- ``low_stock``: productos con stock disponible <= umbral del CEO agent
  (``_STOCK_ALERT_THRESHOLD``, fuente única de verdad).
- ``urgent_messages``: mensajes sociales no descartados con intención
  queja/lead y urgencia >= 40 (misma política que ``_gather_social``).

Cada tarjeta lleva ``count`` y una muestra corta de ``items`` para el portal.
El endpoint nunca ejecuta nada: solo cuenta y devuelve etiquetas.

Hermeticidad D-032: sin red (spool local), SQLite de test y datos con ids
únicos; las aserciones son relativas (>= 1) porque la BD es compartida con
el resto de la suite.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.models import (
    ApprovalRequest,
    Campaign,
    OutboxMessage,
    Product,
    SocialMessage,
    SocialTriage,
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


def _seed_today_data() -> dict[str, str]:
    """Siembra un elemento de cada tarjeta y devuelve sus ids únicos."""
    db = SessionLocal()
    try:
        proposal = ApprovalRequest(
            id=_unique("today-appr"),
            action_type="issue_invoice",
            target_key=_unique("inv"),
            payload={"rationale": "Propuesta para la pantalla Hoy"},
            requested_by="finance_agent",
            status="pending",
        )
        campaign = Campaign(
            id=_unique("today-cmp"),
            name=f"Campaña reintento {uuid.uuid4().hex[:6]}",
            template_name="Seguimiento de presupuesto",
            segment={},
            status="pending_retry",
        )
        product = Product(
            id=_unique("today-prod"),
            external_id=_unique("today-prod"),
            sku=_unique("TODAY"),
            name="Producto a punto de agotarse",
            description="Fixture del endpoint /today",
            category="Industrial",
            attributes={"fixture": True},
            source="local",
            base_price=10,
            tax_rate=0.21,
            stock_quantity=3,
            reserved_stock=0,
        )
        # Agotado a 0: la tarjeta «Stock bajo» no lo cuenta (no es «reponer
        # ya», es otra decisión) ni lo muestra en la muestra.
        sold_out = Product(
            id=_unique("today-soldout"),
            external_id=_unique("today-soldout"),
            sku=_unique("SOLD"),
            name="Producto agotado a cero",
            description="Fixture del endpoint /today",
            category="Industrial",
            attributes={"fixture": True},
            source="local",
            base_price=10,
            tax_rate=0.21,
            stock_quantity=0,
            reserved_stock=0,
        )
        message = SocialMessage(
            id=_unique("today-msg"),
            channel_id=_unique("today-ch"),
            source_message_id=_unique("today-src"),
            sender_name="Cliente urgente",
            body="Necesito una respuesta ya, por favor",
            status="triaged",
        )
        triage = SocialTriage(
            id=_unique("today-trg"),
            message_id=message.id,
            intent="queja",
            language="es",
            register="formal",
            sentiment=-0.5,
            urgency=80,
            entities={},
            score_social=72,
            decided_by="deterministic",
        )
        dead = OutboxMessage(
            id=_unique("today-dead"),
            topic="campaign.deliver",
            idempotency_key=_unique("today-idem"),
            payload={"campaign_id": "c-1", "lead_id": "l-1"},
            state="dead",
            attempt_count=3,
            max_attempts=3,
            last_error={
                "type": "RuntimeError",
                "message": "GHL caído a mitad del envío",
                "permanent": False,
            },
        )
        db.add_all([proposal, campaign, product, sold_out, message, triage, dead])
        db.commit()
        return {
            "proposal_id": proposal.id,
            "campaign_name": campaign.name,
            "product_name": product.name,
            "message_id": message.id,
        }
    finally:
        db.close()


def test_today_operator_ve_las_cuatro_tarjetas_con_datos(client, auth_headers):
    seeded = _seed_today_data()
    response = client.get("/today", headers=auth_headers)
    assert response.status_code == 200, response.text
    cards = response.json()["cards"]

    assert cards["pending_approvals"]["count"] is not None
    assert cards["pending_approvals"]["count"] >= 1
    assert cards["campaigns_pending_retry"]["count"] >= 1
    assert any(
        item["label"] == seeded["campaign_name"]
        for item in cards["campaigns_pending_retry"]["items"]
    )
    assert cards["low_stock"]["count"] >= 1
    assert any(
        seeded["product_name"] in item["label"]
        for item in cards["low_stock"]["items"]
    )
    # Un producto agotado a 0 no cuenta como «a punto de agotarse».
    assert not any(
        "Producto agotado a cero" in item["label"]
        for item in cards["low_stock"]["items"]
    )
    assert cards["urgent_messages"]["count"] >= 1
    assert any(
        "Cliente urgente" in item["label"]
        for item in cards["urgent_messages"]["items"]
    )
    # Fallos del motor: la DLQ cuenta el mensaje muerto sembrado y lo
    # describe en lenguaje llano (topic_label) para el enlace al panel.
    assert cards["engine_failures"]["count"] >= 1
    assert any(
        item["label"] == "Envío de una campaña a un destinatario"
        for item in cards["engine_failures"]["items"]
    )


def test_today_viewer_recibe_conteo_de_aprobaciones_nulo(client, auth_headers):
    username = _unique("viewer")
    _create_user(client, auth_headers, username, "viewer")
    token = _login(client, username)["access_token"]
    _seed_today_data()

    response = client.get("/today", headers=_auth(token))
    assert response.status_code == 200, response.text
    cards = response.json()["cards"]

    # RBAC: el viewer no ve el conteo de aprobaciones (ni puede decidir),
    # pero sí las tarjetas operativas de solo lectura.
    assert cards["pending_approvals"]["count"] is None
    assert cards["campaigns_pending_retry"]["count"] is not None
    assert cards["low_stock"]["count"] is not None
    assert cards["urgent_messages"]["count"] is not None
    # El conteo de fallos del motor no es sensible (igual que la cola de
    # /automations/status): el viewer también lo ve, sin los motivos.
    assert cards["engine_failures"]["count"] is not None
    assert isinstance(cards["engine_failures"]["items"], list)


def test_today_sin_datos_devuelve_ceros(client, auth_headers):
    response = client.get("/today", headers=auth_headers)
    assert response.status_code == 200, response.text
    cards = response.json()["cards"]

    assert cards["pending_approvals"]["count"] is not None
    assert cards["campaigns_pending_retry"]["count"] >= 0
    assert cards["low_stock"]["count"] >= 0
    assert cards["urgent_messages"]["count"] >= 0
    assert cards["engine_failures"]["count"] >= 0
    assert isinstance(cards["low_stock"]["items"], list)
    assert isinstance(cards["engine_failures"]["items"], list)
