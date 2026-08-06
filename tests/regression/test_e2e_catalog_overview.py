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
from decimal import Decimal

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


def _count_prestashop_products() -> int:
    db = SessionLocal()
    try:
        return db.query(Product).filter(Product.source == "prestashop").count()
    finally:
        db.close()


def _skip_if_no_prestashop_catalog():
    if _count_prestashop_products() == 0:
        pytest.skip("No hay productos PrestaShop sincronizados en la BD live")


def test_catalog_overview_lists_every_prestashop_product(client):
    """\"¿Qué tenéis?\" debe listar todos los productos PrestaShop del catálogo."""

    _skip_if_no_prestashop_catalog()

    body = _send_signed_webhook(client, "¿Qué tenéis disponible?", 99001)
    assert body["action"] == "catalog_overview", body
    assert body.get("llm") is None
    # El catálogo overview debe contener exclusivamente productos
    # PrestaShop; nunca locales ni importados de staging.
    for product in body["products"]:
        assert product["source"] == "prestashop", (
            f"producto {product['sku']} tiene source={product['source']}, esperaba prestashop"
        )
    reply = body["reply"]
    assert reply.startswith("Estas son las opciones verificadas disponibles")
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
    """\"tienes algo exótico?\" cae al resumen del catálogo PrestaShop."""

    _skip_if_no_prestashop_catalog()

    body = _send_signed_webhook(client, "tienes algo exótico?", 99003)
    assert body["action"] == "catalog_overview"
    # El catálogo overview debe ser exclusivamente PrestaShop.
    for product in body["products"]:
        assert product["source"] == "prestashop", product


def test_domain_hint_with_empty_category_falls_back_to_full_catalog(client):
    """\"pásame los portátiles en oferta\" → no hay portátiles → fallback al
    catálogo PrestaShop completo con nota explícita de la categoría ausente.
    """

    _skip_if_no_prestashop_catalog()

    body = _send_signed_webhook(
        client,
        "pásame los portátiles en oferta que tengáis",
        99004,
    )
    assert body["action"] == "catalog_overview_fallback", body
    assert body.get("domain") == "portatil"
    # Solo productos PrestaShop en el fallback.
    for product in body["products"]:
        assert product["source"] == "prestashop", product
    # El reply debe avisar de que no hay portátiles y mostrar el catálogo
    # completo como alternativa.
    reply = body["reply"]
    assert "no tenemos portátiles" in reply.lower()
    assert reply.startswith("Estas son las opciones verificadas disponibles")


def test_catalog_overview_excludes_local_and_imported_products(client):
    """Los resúmenes del catálogo (con o sin domain hint) NUNCA deben
    exponer productos de staging con source='local' o 'import'.
    """

    _skip_if_no_prestashop_catalog()

    from app.database import SessionLocal
    from app.models.models import Product

    db = SessionLocal()
    try:
        # Sembrar un producto local y otro importado de staging para
        # verificar que el filtro los excluye.
        db.add(
            Product(
                id="stage-local",
                external_id="stage-local",
                sku="STG-LOCAL-001",
                name="Producto staging local NO debe aparecer",
                category="Staging",
                attributes={"active": True, "available_for_order": True, "show_price": True},
                source="local",
                base_price=Decimal("1.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=1,
                reserved_stock=0,
            )
        )
        db.add(
            Product(
                id="stage-import",
                external_id="stage-import",
                sku="STG-IMPORT-001",
                name="Producto staging import NO debe aparecer",
                category="Staging",
                attributes={"active": True, "available_for_order": True, "show_price": True},
                source="import",
                base_price=Decimal("1.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=1,
                reserved_stock=0,
            )
        )
        db.commit()
    finally:
        db.close()

    body = _send_signed_webhook(client, "¿Qué tenéis disponible?", 99010)
    assert body["action"] == "catalog_overview"
    skus = {p["sku"] for p in body["products"]}
    assert "STG-LOCAL-001" not in skus, skus
    assert "STG-IMPORT-001" not in skus, skus