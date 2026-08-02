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
)


def _new_product(*, source: str, attributes: dict | None = None) -> Product:
    suffix = uuid.uuid4().hex[:12]
    return Product(
        id=f"p0-product-{suffix}",
        external_id=f"p0-external-{suffix}",
        sku=f"P0-{suffix}",
        name=f"Producto P0 {suffix}",
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
    product.tax_rate = Decimal("0")
    product_id, external_id = product.id, product.external_id
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()

        result = DeterministicToolsService(db).calculate_price(product.id, 1)

        assert Decimal(str(result["vat_rate"])) == Decimal("0")
        assert Decimal(str(result["vat_amount"])) == Decimal("0")
    finally:
        db.close()
        _delete_product(product_id, external_id)


def test_p0_prestashop_sync_preserves_authoritative_tax_rate(client, auth_headers, monkeypatch):
    product = _new_product(source="prestashop")
    product_id, external_id = product.id, product.external_id

    async def authoritative_product(*, limit: int, include_details: bool):
        assert limit == 1
        assert include_details is True
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

    async def product_without_tax(*, limit: int, include_details: bool):
        assert limit == 1
        assert include_details is True
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
        finally:
            db.close()
    finally:
        _delete_product(product_id, external_id)


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
