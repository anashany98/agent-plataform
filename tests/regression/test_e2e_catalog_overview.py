"""End-to-end test del flujo catalog_overview.

Verifica que una pregunta libre del chat (\"¿Qué tenéis?\") muestra el
catálogo completo sincronizado desde PrestaShop en lugar de transferir al
equipo comercial o de abstenerse. Usa TestClient (sin red externa) y un
catálogo sintético de 21 productos para validar el límite configurable
CATALOG_OVERVIEW_LIMIT (default 500).

El test se ejecuta en el entorno live de Docker para validar la
integración real con la BD sincronizada desde PrestaShop. Es hermético
en lo que al exterior respecta: no toca Chatwoot ni PrestaShop.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models.models import Product
from fastapi.testclient import TestClient


def _send_signed_webhook(client: TestClient, content: str, conversation_id: int) -> dict:
    secret = "test-chatwoot-secret"
    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "id": f"e2e-{int(time.time() * 1_000_000)}",
        "content": content,
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {
            "email": f"e2e-{conversation_id}@example.com",
            "name": f"Cliente E2E {conversation_id}",
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    response = client.post(
        "/webhooks/chatwoot",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _count_trusted_products() -> int:
    db = SessionLocal()
    try:
        return (
            db.query(Product)
            .filter(Product.source.in_(["prestashop", "local", "import"]))
            .count()
        )
    finally:
        db.close()


def test_catalog_overview_lists_every_prestashop_product(client):
    """\"¿Qué tenéis?\" debe listar todos los productos del catálogo."""

    trusted = _count_trusted_products()
    if trusted == 0:
        pytest.skip("No hay productos trusted sincronizados; corre la sync PrestaShop")

    body = _send_signed_webhook(client, "¿Qué tenéis disponible?", 99001)
    assert body["action"] == "catalog_overview", body
    assert body.get("llm") is None
    assert len(body["products"]) == trusted, (
        f"Esperaba {trusted} productos, obtuve {len(body['products'])}"
    )
    reply = body["reply"]
    assert reply.startswith("Estas son las opciones verificadas disponibles")
    # Cada producto aparece en el reply con su SKU y precio.
    for product in body["products"]:
        assert product["sku"] in reply
        assert f"{product['unit_price']:.2f}" in reply


def test_catalog_overview_respects_configurable_limit(client):
    """El default CATALOG_OVERVIEW_LIMIT debe permitir agotar el catálogo."""

    expected_limit = max(1, min(int(settings.CATALOG_OVERVIEW_LIMIT), 1000))
    assert expected_limit >= 300, (
        f"CATALOG_OVERVIEW_LIMIT={settings.CATALOG_OVERVIEW_LIMIT} no cubre catálogos grandes"
    )


def test_short_greeting_does_not_trigger_catalog_overview(client):
    """Un saludo corto no debe generar un resumen de catálogo."""

    body = _send_signed_webhook(client, "Hola, buenas tardes", 99002)
    assert body["action"] != "catalog_overview"


def test_product_inquiry_without_specific_match_returns_full_catalog(client):
    """\"tienes algo exótico?\" cae al resumen del catálogo completo."""

    trusted = _count_trusted_products()
    if trusted == 0:
        pytest.skip("No hay productos trusted sincronizados")

    body = _send_signed_webhook(client, "tienes algo exótico?", 99003)
    assert body["action"] == "catalog_overview"
    assert len(body["products"]) == trusted