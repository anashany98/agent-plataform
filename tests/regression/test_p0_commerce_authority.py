import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app import main as bridge_main
from app.database import SessionLocal
from app.models.models import Customer, Product, StockReservation
from app.services.deterministic_tools import (
    BusinessRuleError,
    DeterministicToolsService,
    InsufficientStockError,
)

CHATWOOT_WEBHOOK_SECRET = "test-chatwoot-secret"


def _sign_webhook(raw_body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(
        CHATWOOT_WEBHOOK_SECRET.encode("utf-8"),
        f"{ts}.".encode() + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Chatwoot-Signature": sig,
        "X-Chatwoot-Timestamp": ts,
        "Content-Type": "application/json",
    }


def _new_product(
    *,
    source: str,
    attributes: dict | None = None,
    name_suffix: str | None = None,
) -> Product:
    suffix = uuid.uuid4().hex[:12]
    return Product(
        id=f"p0-product-{suffix}",
        external_id=f"p0-external-{suffix}",
        sku=f"P0-{suffix}",
        name=f"Producto P0 {name_suffix or suffix}",
        description="Fixture sintético de regresión",
        category="Pruebas",
        attributes=attributes or {},
        source=source,
        base_price=Decimal("100.00"),
        tax_rate=Decimal("0.21"),
        stock_quantity=10,
        reserved_stock=0,
    )


def _delete_product(product_id: str, external_id: str) -> None:
    db = SessionLocal()
    try:
        product_ids = [
            row[0]
            for row in db.query(Product.id)
            .filter((Product.id == product_id) | (Product.external_id == external_id))
            .all()
        ]
        if product_ids:
            db.query(StockReservation).filter(StockReservation.product_id.in_(product_ids)).delete(
                synchronize_session=False
            )
            db.query(Product).filter(Product.id.in_(product_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _confirmed_reservation(db, product: Product, qty: int) -> StockReservation:
    customer_id = f"p0-customer-{uuid.uuid4().hex[:12]}"
    db.add(
        Customer(
            id=customer_id,
            name="Cliente P0 sintético",
            email=f"{customer_id}@example.invalid",
        )
    )
    db.commit()
    tools = DeterministicToolsService(db)
    quote = tools.create_quote(customer_id, [{"product_id": product.id, "qty": qty}])
    order = tools.confirm_quote_transactional(
        quote["quote_id"],
        f"p0-confirm-{quote['quote_id']}",
        quote["confirmation_token"],
        confirmed_by=customer_id,
    )
    return db.query(StockReservation).filter(StockReservation.order_id == order["order_id"]).one()


def test_p0_pricing_applies_selected_combination_and_its_specific_price():
    combination_id = "combination-authoritative"
    product = _new_product(
        source="prestashop",
        attributes={
            "active": True,
            "show_price": True,
            "available_for_order": True,
            "combinations": [
                {
                    "id": combination_id,
                    "reference": "P0-VARIANT",
                    "price_impact": 20.0,
                    "stock_quantity": 4,
                    "default": False,
                }
            ],
            "specific_prices": [
                {
                    "combination_id": combination_id,
                    "price": -1.0,
                    "from_quantity": 1,
                    "reduction": 0.10,
                    "reduction_type": "percentage",
                    "reduction_tax": True,
                }
            ],
        },
    )
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)

        result = tools.calculate_price(product.id, 1, combination_id=combination_id)

        assert Decimal(str(result["base_unit_price"])) == Decimal("120.00")
        assert Decimal(str(result["discounted_unit_price"])) == Decimal("108.00")
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_pricing_rejects_unknown_combination_instead_of_using_base_product():
    product = _new_product(source="local", attributes={"combinations": []})
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)

        with pytest.raises(BusinessRuleError, match="Combinación"):
            tools.calculate_price(product.id, 1, combination_id="missing")
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_zero_tax_rate_is_preserved_instead_of_falling_back_to_default_vat():
    product = _new_product(source="local")
    product.tax_rate = Decimal(0)
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()

        result = DeterministicToolsService(db).calculate_price(product.id, 1)

        assert Decimal(str(result["vat_rate"])) == Decimal(0)
        assert Decimal(str(result["vat_amount"])) == Decimal(0)
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_prestashop_sync_preserves_authoritative_tax_rate(client, auth_headers, monkeypatch):
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id

    async def authoritative_product(
        *,
        limit: int,
        offset: int,
        include_details: bool,
        category_names=None,
        stock_map=None,
        batch_stock: bool,
    ):
        assert limit == 1
        assert offset == 0
        assert include_details is True
        assert category_names is None and stock_map is None and not batch_stock
        return [
            {
                "external_id": product.external_id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "category": product.category,
                "attributes": {},
                "source": "prestashop",
                "source_url": "https://shop.invalid/product/fixture",
                "base_price": 100.0,
                "tax_rate": 0.10,
                "stock_quantity": 10,
            }
        ]

    monkeypatch.setattr(bridge_main.prestashop_adapter, "list_products", authoritative_product)
    try:
        response = client.post(
            "/integrations/prestashop/sync?limit=1&dry_run=false&include_details=true",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        db = SessionLocal()
        try:
            persisted = db.query(Product).filter(Product.external_id == product.external_id).one()
            assert Decimal(str(persisted.tax_rate)) == Decimal("0.10")
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def test_p0_prestashop_sync_fails_closed_when_tax_authority_is_missing(
    client,
    auth_headers,
    monkeypatch,
):
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id

    async def product_without_tax(
        *,
        limit: int,
        offset: int,
        include_details: bool,
        category_names=None,
        stock_map=None,
        batch_stock: bool,
    ):
        assert limit == 1
        assert offset == 0
        assert include_details is True
        assert category_names is None and stock_map is None and not batch_stock
        return [
            {
                "external_id": external_id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "category": product.category,
                "attributes": {},
                "source": "prestashop",
                "source_url": "https://shop.invalid/product/fixture",
                "base_price": 100.0,
                "stock_quantity": 10,
            }
        ]

    monkeypatch.setattr(bridge_main.prestashop_adapter, "list_products", product_without_tax)
    try:
        response = client.post(
            "/integrations/prestashop/sync?limit=1&dry_run=false&include_details=true",
            headers=auth_headers,
        )
        assert response.status_code == 503, response.text

        db = SessionLocal()
        try:
            assert db.query(Product).filter(Product.external_id == external_id).count() == 0
            failed = (
                db.query(bridge_main.PrestashopSyncHistory)
                .filter(bridge_main.PrestashopSyncHistory.status == "failed")
                .order_by(bridge_main.PrestashopSyncHistory.started_at.desc())
                .first()
            )
            assert failed is not None, "el fallo del sync debe quedar registrado en el historial"
            assert failed.error is not None
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def test_p0_prestashop_sync_forwards_incremental_since(client, auth_headers, monkeypatch):
    """El endpoint usa el escaneo incremental cuando ``since`` se pasa."""
    seen: dict = {}

    async def changed_since(since, *, include_details):
        seen["since"] = since
        seen["include_details"] = include_details
        return [], {}

    monkeypatch.setattr(
        bridge_main.prestashop_adapter, "list_products_changed_since", changed_since
    )
    response = client.post(
        "/integrations/prestashop/sync?limit=500&dry_run=false"
        "&include_details=false&since=2026-08-13+00%3A00%3A00",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert seen == {"since": "2026-08-13 00:00:00", "include_details": False}
    assert response.json()["incremental"] is True


def test_p0_prestashop_sync_applies_stock_only_delta(client, auth_headers, monkeypatch):
    """El delta de stock actualiza solo las filas con stock distinto."""
    product = _new_product(source="prestashop")
    product.stock_quantity = 3
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
    finally:
        db.close()

    async def changed_since(since, *, include_details):
        return [], {external_id: 5}  # solo cambia el stock

    monkeypatch.setattr(
        bridge_main.prestashop_adapter, "list_products_changed_since", changed_since
    )
    try:
        response = client.post(
            "/integrations/prestashop/sync?limit=500&dry_run=false"
            "&include_details=false&since=2026-08-13+00%3A00%3A00",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["updated"] == 1

        db = SessionLocal()
        try:
            persisted = db.query(Product).filter(Product.id == product_id).one()
            assert persisted.stock_quantity == 5
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


class _InMemoryLockRedis:
    """Falso mínimo de Redis para el lock del sync (set NX + script de release)."""

    def __init__(self) -> None:
        self._locks: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self._locks:
            return None
        self._locks[key] = value
        return True

    def register_script(self, _script: str):
        async def _eval(*, keys, args):
            if self._locks.get(keys[0]) == args[0]:
                del self._locks[keys[0]]
                return 1
            return 0

        return _eval


def _patch_sync_redis(monkeypatch, redis: _InMemoryLockRedis) -> None:
    from app.services.redis_backend import RedisBackend

    monkeypatch.setattr(
        "app.services.redis_backend.RedisBackend",
        lambda: RedisBackend(client=redis),
    )


def test_p0_prestashop_sync_conflicts_when_lock_held(client, auth_headers, monkeypatch):
    """Dos syncs concurrentes: el segundo recibe 409 y queda registrado como skipped."""
    redis = _InMemoryLockRedis()
    redis._locks["bridge:prestashop:sync"] = "otro-run"
    _patch_sync_redis(monkeypatch, redis)

    response = client.post(
        "/integrations/prestashop/sync?limit=1&dry_run=false&include_details=true",
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    assert "en curso" in response.json()["detail"]

    db = SessionLocal()
    try:
        skipped = (
            db.query(bridge_main.PrestashopSyncHistory)
            .filter(bridge_main.PrestashopSyncHistory.status == "skipped")
            .order_by(bridge_main.PrestashopSyncHistory.started_at.desc())
            .first()
        )
        assert skipped is not None, "el sync rechazado debe registrarse como skipped"
    finally:
        db.close()


def test_p0_prestashop_sync_releases_lock_after_run(client, auth_headers, monkeypatch):
    """El lock se libera al terminar el sync (incluso con ejecución exitosa)."""
    redis = _InMemoryLockRedis()
    _patch_sync_redis(monkeypatch, redis)

    async def authoritative_product(
        *,
        limit: int,
        offset: int,
        include_details: bool,
        category_names=None,
        stock_map=None,
        batch_stock: bool,
    ):
        return []

    monkeypatch.setattr(bridge_main.prestashop_adapter, "list_products", authoritative_product)
    response = client.post(
        "/integrations/prestashop/sync?limit=1&dry_run=false&include_details=true",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert "bridge:prestashop:sync" not in redis._locks, "el lock debe liberarse en finally"


def test_p0_prestashop_sync_records_history(client, auth_headers, monkeypatch):
    """Cada ejecución queda registrada en prestashop_sync_history (auditoría del cron)."""

    async def changed_since(since, *, include_details):
        return [], {}

    monkeypatch.setattr(
        bridge_main.prestashop_adapter, "list_products_changed_since", changed_since
    )
    response = client.post(
        "/integrations/prestashop/sync?limit=500&dry_run=false&include_details=false"
        "&since=2026-08-13+00%3A00%3A00",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        rows = (
            db.query(bridge_main.PrestashopSyncHistory)
            .order_by(bridge_main.PrestashopSyncHistory.started_at.desc())
            .all()
        )
        assert rows, "no se registró ninguna fila en prestashop_sync_history"
        latest = rows[0]
        assert latest.incremental is True
        assert latest.status == "success"
        assert latest.since == "2026-08-13 00:00:00"
        assert latest.total_remote == 0
        assert latest.finished_at is not None
        assert latest.duration_seconds >= 0
    finally:
        db.close()

    response = client.get(
        "/integrations/prestashop/sync/history?limit=1", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["history"][0]["status"] == "success"


def test_p0_external_stock_projection_fails_closed_without_authority_confirmation():
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)

        reserved = tools.reserve_stock(product.id, 1, order_id=f"p0-order-{uuid.uuid4().hex}")

        assert reserved is False, "El stock PrestaShop no puede reservarse solo en la proyección local"
        db.expire_all()
        persisted = db.query(Product).filter(Product.id == product.id).one()
        assert persisted.reserved_stock == 0
        assert db.query(StockReservation).filter(StockReservation.product_id == product.id).count() == 0
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_prestashop_buy_creates_quote_without_false_stockout(client):
    # P0-003 (opción C): un producto sincronizado de PrestaShop con stock
    # proyectado crea el presupuesto (la verificación en vivo queda para
    # CONFIRMAR) y NO responde "no hay N unidades disponibles" (falso).
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        product.attributes = {"active": True, "show_price": True, "available_for_order": True}
        db.add(product)
        db.commit()
        product_name = product.name
    finally:
        db.close()

    conversation = 7703
    content = f"Necesito 2 unidades {product_name}"
    body = {
        "event": "message_created",
        "id": f"msg-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation},
        "account": {"id": 1},
        "sender": {"email": f"cliente{conversation}@example.com", "name": f"Cliente {conversation}"},
    }
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        response = client.post("/webhooks/chatwoot", content=raw, headers=_sign_webhook(raw))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["action"] == "quote_created", result
        assert "no hay 2 unidades" not in result["reply"].lower(), result["reply"]
        assert "CONFIRMAR" in result["reply"], result["reply"]
        assert "verificará en vivo" in result["reply"].lower(), result["reply"]
        # El stock no debe reservarse en la compra: la autoridad externa se
        # verifica en vivo al confirmar.
        db = SessionLocal()
        try:
            persisted = db.query(Product).filter(Product.id == product_id).one()
            assert persisted.reserved_stock == 0
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def test_p0_quote_closing_includes_store_name(monkeypatch, client):
    # Persona por cliente: el cierre de compra (creación determinista del
    # presupuesto) menciona el nombre de la tienda configurado.
    monkeypatch.setattr(bridge_main.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        product.attributes = {"active": True, "show_price": True, "available_for_order": True}
        db.add(product)
        db.commit()
        product_name = product.name
    finally:
        db.close()

    conversation = 7704
    raw = _buy_message(product_name, conversation)
    try:
        response = client.post("/webhooks/chatwoot", content=raw, headers=_sign_webhook(raw))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["action"] == "quote_created", result
        assert "Presupuesto" in result["reply"] and "BTOP Digital" in result["reply"], result["reply"]
        assert "CONFIRMAR" in result["reply"], result["reply"]
    finally:
        _delete_product(product_id, external_id)


def test_p0_confirm_sends_invoice_email_with_pdf(client, monkeypatch):
    # Cierre de venta real: al confirmar el presupuesto se crea el pedido y
    # se envía la factura (PDF adjunto) por email al cliente del chat.
    product, product_id, external_id, product_name = _seed_prestashop_product()

    async def fake_get_stocks_batch(product_ids):
        return {str(product.external_id): 5000}

    monkeypatch.setattr(bridge_main.prestashop_adapter, "get_stocks_batch", fake_get_stocks_batch)

    from app.services.automations import EmailResult

    class FakeProvider:
        name = "fake-invoice"

        def __init__(self):
            self.sent: list[dict] = []

        def send(
            self,
            to,
            subject,
            body,
            attachments=None,
            html=None,
            tracking_token=None,
        ):
            self.sent.append(
                {"to": to, "subject": subject, "attachments": attachments or []}
            )
            return EmailResult(self.name, to, subject, True, "fake-ref", status="sent")

    fake = FakeProvider()
    monkeypatch.setattr(bridge_main.settings, "EMAIL_PROVIDER", fake.name)
    monkeypatch.setattr(
        bridge_main.automations,
        "_EMAIL_PROVIDERS",
        dict(bridge_main.automations._EMAIL_PROVIDERS, **{fake.name: fake}),
    )

    conversation = 7709
    try:
        raw_buy = _buy_message(product_name, conversation)
        buy = client.post("/webhooks/chatwoot", content=raw_buy, headers=_sign_webhook(raw_buy))
        assert buy.status_code == 200, buy.text
        token = re.search(r"CONFIRMAR ([A-F0-9]{32})", buy.json()["reply"]).group(1)

        raw_confirm = _confirm_message(conversation, token)
        confirm = client.post("/webhooks/chatwoot", content=raw_confirm, headers=_sign_webhook(raw_confirm))
        assert confirm.status_code == 200, confirm.text
        confirm_result = confirm.json()
        assert confirm_result["action"] == "order_created", confirm_result
        assert "factura" in confirm_result["reply"].lower(), confirm_result["reply"]
        assert "enviado por email" in confirm_result["reply"].lower(), confirm_result["reply"]
        assert confirm_result["invoice_email"] == "La factura se ha enviado por email."

        assert len(fake.sent) == 1
        sent = fake.sent[0]
        assert sent["to"] == f"cliente{conversation}@example.com"
        assert "factura" in sent["subject"].lower()
        assert sent["attachments"][0]["filename"].endswith(".pdf")
        assert sent["attachments"][0]["content"].startswith(b"%PDF")
    finally:
        _delete_product(product_id, external_id)


def test_p0_confirm_with_placeholder_email_skips_invoice_email(client, monkeypatch):
    # Sin email real del cliente, la factura NO se envía (no hay éxito
    # fingido): se audita el salto y el chat pide el dato para enviarla.
    product, product_id, external_id, product_name = _seed_prestashop_product()

    async def fake_get_stocks_batch(product_ids):
        return {str(product.external_id): 5000}

    monkeypatch.setattr(bridge_main.prestashop_adapter, "get_stocks_batch", fake_get_stocks_batch)
    monkeypatch.setattr(bridge_main.settings, "EMAIL_PROVIDER", "local")

    conversation = 7710

    def _no_email_message(content: str) -> bytes:
        body = {
            "event": "message_created",
            "id": f"msg-{uuid.uuid4().hex}",
            "message_type": "incoming",
            "content": content,
            "conversation": {"id": conversation},
            "account": {"id": 1},
            "sender": {"id": "cw-7710", "name": "Cliente sin email"},
        }
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    try:
        raw_buy = _no_email_message(f"Necesito 2 unidades {product_name}")
        buy = client.post("/webhooks/chatwoot", content=raw_buy, headers=_sign_webhook(raw_buy))
        assert buy.status_code == 200, buy.text
        token = re.search(r"CONFIRMAR ([A-F0-9]{32})", buy.json()["reply"]).group(1)

        raw_confirm = _no_email_message(f"CONFIRMAR {token}")
        confirm = client.post("/webhooks/chatwoot", content=raw_confirm, headers=_sign_webhook(raw_confirm))
        assert confirm.status_code == 200, confirm.text
        confirm_result = confirm.json()
        assert confirm_result["action"] == "order_created", confirm_result
        assert "necesito tu correo" in confirm_result["reply"].lower(), confirm_result["reply"]

        from app.models.models import AuditLog

        db = SessionLocal()
        try:
            skipped = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "automation.invoice_email_skipped")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert skipped is not None, "El salto del email debe auditarse"
            assert skipped.details.get("order_id") == confirm_result["order_id"]
            assert skipped.details.get("reason") == "customer_email_placeholder_or_missing"
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def _seed_prestashop_product() -> tuple[Product, str, str, str]:
    product = _new_product(source="prestashop")
    product.attributes = {"active": True, "show_price": True, "available_for_order": True}
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        product_name = product.name
    finally:
        db.close()
    return product, product.id, product.external_id, product_name


def _buy_message(product_name: str, conversation: int, qty: int = 2) -> bytes:
    body = {
        "event": "message_created",
        "id": f"msg-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": f"Necesito {qty} unidades {product_name}",
        "conversation": {"id": conversation},
        "account": {"id": 1},
        "sender": {"email": f"cliente{conversation}@example.com", "name": f"Cliente {conversation}"},
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _confirm_message(conversation: int, token: str) -> bytes:
    body = {
        "event": "message_created",
        "id": f"msg-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": f"CONFIRMAR {token}",
        "conversation": {"id": conversation},
        "account": {"id": 1},
        "sender": {"email": f"cliente{conversation}@example.com", "name": f"Cliente {conversation}"},
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_p0_confirm_prestashop_quote_confirms_when_remote_stock_sufficient(client, monkeypatch):
    # P0-003 (opción C): al confirmar un presupuesto con producto PrestaShop,
    # se verifica en vivo el stock remoto; con stock suficiente se crea el
    # pedido sin reserva local (la autoridad es la tienda).
    product, product_id, external_id, product_name = _seed_prestashop_product()

    async def fake_get_stocks_batch(product_ids):
        assert str(product.external_id) in [str(p) for p in product_ids]
        return {str(product.external_id): 5000}

    monkeypatch.setattr(bridge_main.prestashop_adapter, "get_stocks_batch", fake_get_stocks_batch)

    conversation = 7706
    try:
        raw_buy = _buy_message(product_name, conversation)
        buy = client.post("/webhooks/chatwoot", content=raw_buy, headers=_sign_webhook(raw_buy))
        assert buy.status_code == 200, buy.text
        buy_result = buy.json()
        assert buy_result["action"] == "quote_created", buy_result
        token = re.search(r"CONFIRMAR ([A-F0-9]{32})", buy_result["reply"]).group(1)

        raw_confirm = _confirm_message(conversation, token)
        confirm = client.post("/webhooks/chatwoot", content=raw_confirm, headers=_sign_webhook(raw_confirm))
        assert confirm.status_code == 200, confirm.text
        confirm_result = confirm.json()
        assert confirm_result["action"] == "order_created", confirm_result
        assert confirm_result["order_id"].startswith("ord-"), confirm_result

        # La verificación en vivo sustituye a la reserva local para la
        # autoridad externa: no debe haber reserva contra el stock local.
        db = SessionLocal()
        try:
            assert db.query(StockReservation).filter(StockReservation.product_id == product_id).count() == 0
            persisted = db.query(Product).filter(Product.id == product_id).one()
            assert persisted.reserved_stock == 0
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def test_p0_confirm_prestashop_quote_409_and_handoff_when_remote_stock_insufficient(client, monkeypatch):
    # P0-003 (opción C): si el stock remoto verificado en vivo es inferior a
    # lo solicitado, CONFIRMAR responde 409 sin crear pedido, con handoff a
    # humano y mensaje honesto.
    product, product_id, external_id, product_name = _seed_prestashop_product()

    async def fake_get_stocks_batch(product_ids):
        return {str(product.external_id): 1}

    monkeypatch.setattr(bridge_main.prestashop_adapter, "get_stocks_batch", fake_get_stocks_batch)

    conversation = 7707
    try:
        raw_buy = _buy_message(product_name, conversation, qty=2)
        buy = client.post("/webhooks/chatwoot", content=raw_buy, headers=_sign_webhook(raw_buy))
        assert buy.status_code == 200, buy.text
        buy_result = buy.json()
        assert buy_result["action"] == "quote_created", buy_result
        token = re.search(r"CONFIRMAR ([A-F0-9]{32})", buy_result["reply"]).group(1)

        raw_confirm = _confirm_message(conversation, token)
        confirm = client.post("/webhooks/chatwoot", content=raw_confirm, headers=_sign_webhook(raw_confirm))
        assert confirm.status_code == 409, confirm.text
        assert "Stock remoto insuficiente" in confirm.text, confirm.text

        db = SessionLocal()
        try:
            assert db.query(StockReservation).filter(StockReservation.product_id == product_id).count() == 0
            persisted = db.query(Product).filter(Product.id == product_id).one()
            assert persisted.reserved_stock == 0
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


def test_p0_confirm_prestashop_quote_fails_closed_without_live_verification():
    # P0-003 (opción C): sin verificación en vivo del stock remoto, un
    # producto de autoridad externa NO puede confirmarse (fail-closed 409).
    product, product_id, external_id, _ = _seed_prestashop_product()
    db = SessionLocal()
    try:
        customer_id = f"p0-failclosed-{uuid.uuid4().hex[:12]}"
        db.add(
            Customer(
                id=customer_id,
                name="Cliente fail-closed",
                email=f"{customer_id}@example.invalid",
            )
        )
        db.commit()
        tools = DeterministicToolsService(db)
        quote = tools.create_quote(customer_id, [{"product_id": product_id, "qty": 2}])
        with pytest.raises(InsufficientStockError):
            tools.confirm_quote_transactional(
                quote["quote_id"],
                f"p0-failclosed-{quote['quote_id']}",
                quote["confirmation_token"],
                confirmed_by=customer_id,
            )
        # Sin pedido ni reserva tras el rechazo.
        assert db.query(StockReservation).filter(StockReservation.product_id == product_id).count() == 0
        persisted = db.query(Product).filter(Product.id == product_id).one()
        assert persisted.reserved_stock == 0
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_confirm_prestashop_quote_skips_local_reservation_when_verified():
    # P0-003 (opción C): con stock remoto verificado en vivo, la confirmación
    # crea el pedido pero NO reserva stock local (la autoridad es la tienda).
    product, product_id, external_id, _ = _seed_prestashop_product()
    db = SessionLocal()
    try:
        customer_id = f"p0-verified-{uuid.uuid4().hex[:12]}"
        db.add(
            Customer(
                id=customer_id,
                name="Cliente verificado",
                email=f"{customer_id}@example.invalid",
            )
        )
        db.commit()
        tools = DeterministicToolsService(db)
        quote = tools.create_quote(customer_id, [{"product_id": product_id, "qty": 2}])
        order = tools.confirm_quote_transactional(
            quote["quote_id"],
            f"p0-verified-{quote['quote_id']}",
            quote["confirmation_token"],
            confirmed_by=customer_id,
            verified_remote_stock={product_id: 5000},
        )
        assert order["created"] is True
        assert order["order_id"].startswith("ord-")
        assert db.query(StockReservation).filter(StockReservation.product_id == product_id).count() == 0
        persisted = db.query(Product).filter(Product.id == product_id).one()
        assert persisted.reserved_stock == 0
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_local_stockout_keeps_honest_insufficient_stock(client):
    # Regresión: el agotado real del catálogo local conserva el mensaje
    # "no hay N unidades disponibles" y la acción original.
    # Referencia numérica larga: antes se eliminaba como si fuese la
    # cantidad y el flujo caía de forma intermitente en catalog_browse_prompt.
    product = _new_product(source="local", name_suffix="123456789012")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        product.stock_quantity = 0
        product.reserved_stock = 0
        db.add(product)
        db.commit()
        product_name = product.name
    finally:
        db.close()

    conversation = 7704
    content = f"Necesito 2 unidades {product_name}"
    body = {
        "event": "message_created",
        "id": f"msg-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation},
        "account": {"id": 1},
        "sender": {"email": f"cliente{conversation}@example.com", "name": f"Cliente {conversation}"},
    }
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        response = client.post("/webhooks/chatwoot", content=raw, headers=_sign_webhook(raw))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["action"] == "insufficient_stock", result
        assert "no hay 2 unidades disponibles" in result["reply"].lower(), result["reply"]
    finally:
        _delete_product(product_id, external_id)


def test_p0_reservation_can_be_released_and_restores_available_stock():
    product = _new_product(source="local")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)
        reservation = _confirmed_reservation(db, product, 3)

        assert tools.release_stock(reservation.id) is True

        db.expire_all()
        persisted_product = db.query(Product).filter(Product.id == product.id).one()
        persisted_reservation = db.query(StockReservation).filter(StockReservation.id == reservation.id).one()
        assert persisted_product.reserved_stock == 0
        assert persisted_reservation.status == "released"
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_expired_reservation_is_released_once_and_restores_stock():
    product = _new_product(source="local")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)
        reservation = _confirmed_reservation(db, product, 2)
        reservation.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()

        assert tools.expire_stock_reservations() == 1
        assert tools.expire_stock_reservations() == 0

        db.expire_all()
        persisted_product = db.query(Product).filter(Product.id == product.id).one()
        persisted_reservation = db.query(StockReservation).filter(StockReservation.id == reservation.id).one()
        assert persisted_product.reserved_stock == 0
        assert persisted_reservation.status == "expired"
        assert persisted_reservation.released_at is not None
    finally:
        db.close()
        _delete_product(product_id, external_id)
