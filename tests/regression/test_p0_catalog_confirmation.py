import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.database import SessionLocal
from app.models.models import ConversationState, Order, Product, Quote
from app.services.deterministic_tools import (
    BusinessRuleError,
    DeterministicToolsService,
)


def _signed_chatwoot_message(
    client,
    *,
    conversation_id: int,
    content: str,
    sender_email: str | None = None,
    message_id: str | None = None,
    delivery_id: str | None = None,
):
    payload = {
        "event": "message_created",
        "id": message_id or f"regression-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {
            "email": sender_email or f"cliente-{conversation_id}@example.com",
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
    headers = {
        "Content-Type": "application/json",
        "X-Chatwoot-Timestamp": timestamp,
        "X-Chatwoot-Signature": f"sha256={signature}",
    }
    if delivery_id:
        headers["X-Chatwoot-Delivery"] = delivery_id
    return client.post(
        "/webhooks/chatwoot",
        content=raw,
        headers=headers,
    )


def _create_pending_quote(client, auth_headers, *, label: str):
    unique = uuid.uuid4().hex[:12]
    product_name = f"Silla sintética {label} {unique}"
    imported = client.post(
        "/api/bridge/import/products",
        headers=auth_headers,
        json={
            "dry_run": False,
            "items": [
                {
                    "sku": f"CONF-{unique}",
                    "name": product_name,
                    "description": "Fixture sintético para confirmar de forma segura.",
                    "category": "Pruebas",
                    "source": "local",
                    "base_price": 100,
                    "tax_rate": 0.21,
                    "stock_quantity": 20,
                }
            ],
        },
    )
    assert imported.status_code == 200, imported.text
    conversation_id = int(unique[:8], 16)
    response = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"Necesito 1 unidad {product_name}",
    )
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "quote_created", response.text
    token_match = re.search(r"CONFIRMAR ([A-F0-9]{32})", response.json()["reply"])
    assert token_match, response.text
    return conversation_id, response.json()["quote_id"], token_match.group(1)


def test_p0_001_demo_products_are_not_visible_through_catalog_tool(client, auth_headers):
    response = client.get("/tools/products?query=Industrial", headers=auth_headers)

    assert response.status_code == 200, response.text
    leaked_demo_products = [product for product in response.json() if product.get("source") == "demo"]
    assert leaked_demo_products == [], (
        "P0-001 reproducido: /tools/products devuelve productos demo como resultados de catálogo; "
        f"ejemplos={[(product['sku'], product['name']) for product in leaked_demo_products[:3]]}"
    )


def test_p0_001_demo_source_aliases_are_fail_closed_across_catalog_operations(client, auth_headers):
    unique = uuid.uuid4().hex[:12]
    aliases = ("Demo", " demo ", "fixture", "SAMPLE", "customer-demo-data")
    response = client.post(
        "/api/bridge/import/products",
        headers=auth_headers,
        json={
            "dry_run": False,
            "items": [
                {
                    "sku": f"DEMO-ALIAS-{index}-{unique}",
                    "name": f"Producto oculto alias {index} {unique}",
                    "source": source,
                    "base_price": 10,
                    "tax_rate": 0.21,
                    "stock_quantity": 5,
                }
                for index, source in enumerate(aliases)
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "validation_error"
    assert response.json()["invalid_rows"] == len(aliases)

    db = SessionLocal()
    try:
        db.execute(
            Product.__table__.insert(),
            [
                {
                    "id": f"historical-demo-{index}-{unique}",
                    "installation_id": settings.INSTALLATION_ID,
                    "external_id": f"historical-demo-external-{index}-{unique}",
                    "sku": f"DEMO-ALIAS-{index}-{unique}",
                    "name": f"Producto histórico oculto alias {index} {unique}",
                    "source": source,
                    "base_price": 10,
                    "tax_rate": 0.21,
                    "stock_quantity": 5,
                    "reserved_stock": 0,
                }
                for index, source in enumerate(aliases)
            ],
        )
        db.commit()
        products = db.query(Product).filter(Product.sku.like(f"DEMO-ALIAS-%-{unique}")).all()
        assert len(products) == len(aliases)
        tools = DeterministicToolsService(db)
        visible_ids = {row["id"] for row in tools.search_products(unique, limit=20)}
        for product in products:
            assert product.id not in visible_ids
            with pytest.raises(BusinessRuleError, match="no encontrado"):
                tools.get_product(product.id)
            with pytest.raises(BusinessRuleError, match="no encontrado"):
                tools.calculate_price(product.id, 1)
            assert tools.check_stock(product.id)["available"] is False
    finally:
        db.close()


def test_p0_002_negative_confirmation_never_creates_an_order(client, auth_headers):
    conversation_id, quote_id, _ = _create_pending_quote(client, auth_headers, label="negación")

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


def test_p0_002_only_exact_structured_token_confirms_and_replay_is_idempotent(client, auth_headers):
    conversation_id, quote_id, token = _create_pending_quote(client, auth_headers, label="confirmación")

    db = SessionLocal()
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        assert quote.confirmation_token != token
        assert quote.confirmation_token == hashlib.sha256(token.encode()).hexdigest()
    finally:
        db.close()

    intruder = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"CONFIRMAR {token}",
        sender_email="otro-cliente@example.com",
    )
    assert intruder.status_code == 403

    first = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"CONFIRMAR {token}",
    )
    assert first.status_code == 200
    db = SessionLocal()
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        quote.confirmation_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    second = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"confirmar {token.lower()}",
    )

    assert second.status_code == 200
    assert first.json()["action"] == "order_created"
    assert second.json()["action"] == "order_already_exists"
    assert first.json()["order_id"] == second.json()["order_id"]
    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.quote_id == quote_id).count() == 1
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        assert quote.confirmation_consumed_at is not None
        assert quote.confirmed_by
    finally:
        db.close()


def test_p0_002_quote_retry_recovers_the_original_confirmable_token(client, auth_headers):
    conversation_id, quote_id, token = _create_pending_quote(client, auth_headers, label="retry-token")
    db = SessionLocal()
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        replay = DeterministicToolsService(db).create_quote(
            quote.customer_id,
            [
                {
                    "product_id": item["product_id"],
                    "combination_id": item.get("combination_id"),
                    "qty": item["qty"],
                }
                for item in quote.items
            ],
            account_id=quote.account_id,
            conversation_id=quote.conversation_id,
            source_message_id=quote.source_message_id,
        )
    finally:
        db.close()

    assert replay["created"] is False
    assert replay["confirmation_token"] == token
    confirmed = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"CONFIRMAR {replay['confirmation_token']}",
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["action"] == "order_created"


def test_p0_002_unsigned_delivery_header_cannot_bypass_webhook_replay_protection(client):
    unique = uuid.uuid4().hex[:12]
    message_id = f"signed-message-{unique}"
    conversation_id = int(unique[:8], 16)
    content = "Consulta sin efectos comerciales"

    first = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=content,
        message_id=message_id,
        delivery_id=f"delivery-a-{unique}",
    )
    replay = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=content,
        message_id=message_id,
        delivery_id=f"delivery-b-{unique}",
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "duplicate_ignored"


def test_p0_002_wrong_or_expired_token_never_confirms(client, auth_headers):
    conversation_id, quote_id, token = _create_pending_quote(client, auth_headers, label="caducidad")

    wrong = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content="CONFIRMAR 00000000000000000000000000000000",
    )
    assert wrong.status_code == 422

    db = SessionLocal()
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        quote.confirmation_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    expired = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"CONFIRMAR {token}",
    )
    assert expired.status_code == 422
    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.quote_id == quote_id).count() == 0
        assert db.query(Quote).filter(Quote.id == quote_id).one().status == "expired"
    finally:
        db.close()


def test_p0_002_payload_hash_blocks_confirmation_after_quote_mutation(client, auth_headers):
    conversation_id, quote_id, token = _create_pending_quote(client, auth_headers, label="integridad")
    db = SessionLocal()
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).one()
        quote.grand_total += 1
        db.commit()
    finally:
        db.close()

    response = _signed_chatwoot_message(
        client,
        conversation_id=conversation_id,
        content=f"CONFIRMAR {token}",
    )
    assert response.status_code == 422
    assert "cambió" in response.json()["detail"]
    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.quote_id == quote_id).count() == 0
    finally:
        db.close()


def test_p0_002_conversation_state_cannot_confirm_another_customers_quote(
    client,
    auth_headers,
):
    conversation_a, _, _ = _create_pending_quote(client, auth_headers, label="state-a")
    _, quote_b, token_b = _create_pending_quote(client, auth_headers, label="state-b")

    db = SessionLocal()
    try:
        state_a = db.query(ConversationState).filter(
            ConversationState.account_id == "1",
            ConversationState.conversation_id == str(conversation_a),
        ).one()
        state_a.active_quote_id = quote_b
        db.commit()
    finally:
        db.close()

    response = _signed_chatwoot_message(
        client,
        conversation_id=conversation_a,
        content=f"CONFIRMAR {token_b}",
    )
    assert response.status_code == 409, response.text
    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.quote_id == quote_b).count() == 0
    finally:
        db.close()
