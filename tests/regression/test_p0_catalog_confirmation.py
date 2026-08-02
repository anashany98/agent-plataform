import hashlib
import hmac
import json
import time
import uuid

from app.database import SessionLocal
from app.models.models import Order, Quote


def _signed_chatwoot_message(client, *, conversation_id: int, content: str):
    payload = {
        "event": "message_created",
        "id": f"regression-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {
            "email": f"cliente-{conversation_id}@example.com",
            "name": f"Cliente sintético {conversation_id}",
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"test-chatwoot-secret",
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/chatwoot",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )


def test_p0_001_demo_products_are_not_visible_through_catalog_tool(client, auth_headers):
    response = client.get("/tools/products?query=Industrial", headers=auth_headers)

    assert response.status_code == 200, response.text
    leaked_demo_products = [product for product in response.json() if product.get("source") == "demo"]
    assert leaked_demo_products == [], (
        "P0-001 reproducido: /tools/products devuelve productos demo como resultados de catálogo; "
        f"ejemplos={[(product['sku'], product['name']) for product in leaked_demo_products[:3]]}"
    )


def test_p0_002_negative_confirmation_never_creates_an_order(client, auth_headers):
    unique = uuid.uuid4().hex[:12]
    product_name = f"Silla sintética negación {unique}"
    imported = client.post(
        "/api/bridge/import/products",
        headers=auth_headers,
        json={
            "dry_run": False,
            "items": [
                {
                    "sku": f"NEG-{unique}",
                    "name": product_name,
                    "description": "Fixture sintético para reproducir una confirmación negativa.",
                    "category": "Pruebas",
                    "source": "local",
                    "base_price": 100,
                    "tax_rate": 0.21,
                    "stock_quantity": 5,
                }
            ],
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["status"] == "success", imported.text

    conversation_id = int(unique[:8], 16)
    quote_response = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"Necesito 1 unidad {product_name}",
    )
    assert quote_response.status_code == 200, quote_response.text
    assert quote_response.json()["action"] == "quote_created", quote_response.text
    quote_id = quote_response.json()["quote_id"]

    negative_response = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content="No acepto",
    )
    assert negative_response.status_code < 500, negative_response.text

    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.quote_id == quote_id).first()
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        assert order is None, (
            "P0-002 reproducido: el mensaje 'No acepto' creó un pedido confirmado; "
            f"order_id={order.id}, response_action={negative_response.json().get('action')}"
        )
        assert quote.status != "confirmed", (
            "P0-002 reproducido: el mensaje 'No acepto' cambió el presupuesto a confirmed"
        )
    finally:
        db.close()
