import hashlib
import hmac
import json
import time
import uuid

from app.database import SessionLocal
from app.models.models import ApprovalRequest, Customer, InvoiceDraft, Order, Product, Quote, StockReservation
from app.services.deterministic_tools import DeterministicToolsService


def signed(client, payload):
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(b'test-chatwoot-secret', timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return client.post('/webhooks/chatwoot', content=raw, headers={'Content-Type': 'application/json', 'X-Chatwoot-Timestamp': timestamp, 'X-Chatwoot-Signature': f'sha256={signature}'})


def quote_message(conversation_id: int, content: str = 'Necesito 2 unidades Industrial Modelo 1'):
    return {
        'event': 'message_created',
        'id': f'quote-{uuid.uuid4().hex}',
        'message_type': 'incoming',
        'content': content,
        'conversation': {'id': conversation_id},
        'account': {'id': 1},
        'sender': {'email': f'cliente{conversation_id}@example.com', 'name': f'Cliente {conversation_id}'},
    }


def confirm_message(conversation_id: int):
    return {
        'event': 'message_created',
        'id': f'confirm-{uuid.uuid4().hex}',
        'message_type': 'incoming',
        'content': 'CONFIRMAR',
        'conversation': {'id': conversation_id},
        'account': {'id': 1},
    }


def test_customer_pricelist_discount_is_applied():
    db = SessionLocal()
    try:
        tools = DeterministicToolsService(db)
        product = tools.search_products('Industrial')[0]
        result = tools.calculate_price(product['id'], 1, 'cust-004')
        assert result['discount_percentage'] == 20.0
        assert result['discounted_unit_price'] < result['base_unit_price']
    finally:
        db.close()


def test_conversation_can_only_confirm_its_own_quote(client):
    a = signed(client, quote_message(1101))
    b = signed(client, quote_message(2202, 'Necesito 3 unidades Industrial Modelo 6'))
    assert a.status_code == b.status_code == 200

    wrong = signed(client, confirm_message(3303))
    assert wrong.status_code == 409

    confirmed_a = signed(client, confirm_message(1101))
    assert confirmed_a.status_code == 200, confirmed_a.text
    result = confirmed_a.json()
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == result['order_id']).one()
        quote_a = db.query(Quote).filter(Quote.id == a.json()['quote_id']).one()
        quote_b = db.query(Quote).filter(Quote.id == b.json()['quote_id']).one()
        assert order.quote_id == quote_a.id
        assert order.quote_id != quote_b.id
    finally:
        db.close()


def test_repeated_confirmation_is_business_idempotent(client):
    conversation = 4404
    quote = signed(client, quote_message(conversation))
    assert quote.status_code == 200
    first = signed(client, confirm_message(conversation))
    second = signed(client, confirm_message(conversation))
    assert first.status_code == second.status_code == 200
    assert first.json()['order_id'] == second.json()['order_id']
    assert second.json()['action'] == 'order_already_exists'
    db = SessionLocal()
    try:
        assert db.query(Order).filter(Order.quote_id == quote.json()['quote_id']).count() == 1
        order_id = first.json()['order_id']
        assert db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).count() == 1
    finally:
        db.close()


def test_insufficient_stock_rolls_back_entire_order(client):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.name.ilike('%Industrial Modelo 1%')).first()
        product.stock_quantity = product.reserved_stock
        db.commit()
        before_orders = db.query(Order).count()
        before_reservations = db.query(StockReservation).count()
    finally:
        db.close()

    conversation = 5505
    quote = signed(client, quote_message(conversation, 'Necesito 1 unidad Industrial Modelo 1'))
    assert quote.status_code == 200
    assert quote.json()['action'] == 'insufficient_stock'

    db = SessionLocal()
    try:
        assert db.query(Order).count() == before_orders
        assert db.query(StockReservation).count() == before_reservations
        product = db.query(Product).filter(Product.name.ilike('%Industrial Modelo 1%')).first()
        product.stock_quantity = max(50, product.reserved_stock + 50)
        db.commit()
    finally:
        db.close()


def test_approval_is_single_use_and_reviewer_comes_from_token(client, auth_headers):
    conversation = 6606
    assert signed(client, quote_message(conversation)).status_code == 200
    confirmed = signed(client, confirm_message(conversation))
    approval_id = confirmed.json()['approval_id']
    first = client.post(f'/approvals/{approval_id}/approve', json={}, headers=auth_headers)
    assert first.status_code == 200
    assert first.json()['reviewed_by'] == 'admin'
    second = client.post(f'/approvals/{approval_id}/approve', json={}, headers=auth_headers)
    assert second.status_code == 409


def test_atomic_stock_reservation_rejects_overbooking():
    db = SessionLocal()
    try:
        tools = DeterministicToolsService(db)
        product = tools.search_products('Industrial')[0]
        available = tools.check_stock(product['id'])['available_stock']
        assert tools.reserve_stock(product['id'], available + 1, order_id=f'order-over-{uuid.uuid4().hex}') is False
    finally:
        db.close()


def test_generic_recommendation_uses_only_verified_catalog_data(client, auth_headers):
    sku = f'LUM-{uuid.uuid4().hex[:8]}'
    imported = client.post('/api/bridge/import/products', headers=auth_headers, json={
        'dry_run': False,
        'items': [{
            'sku': sku,
            'name': 'Silla lumbar verificada',
            'description': 'Asiento para jornadas largas',
            'category': 'Sillas',
            'base_price': 300,
            'tax_rate': 0.21,
            'stock_quantity': 5,
            'attributes': {'soporte': 'lumbar regulable'},
        }],
    })
    assert imported.status_code == 200, imported.text
    payload = quote_message(7707, '¿Qué asiento tiene soporte lumbar regulable?')
    response = signed(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['action'] == 'verified_product_recommendations'
    assert 'Silla lumbar verificada' in body['reply']
    assert body.get('llm') is None
