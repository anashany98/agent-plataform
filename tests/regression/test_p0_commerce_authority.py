import uuid
from decimal import Decimal

from app import main as bridge_main
from app.database import SessionLocal
from app.models.models import Product, StockReservation
from app.services.deterministic_tools import DeterministicToolsService


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


def test_p0_pricing_applies_selected_combination_and_its_specific_price():
    combination_id = "combination-authoritative"
    product = _new_product(
        source="prestashop",
        attributes={
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
    order_id = f"p0-order-{uuid.uuid4().hex}"
    db = SessionLocal()
    try:
        db.add(product)
        db.commit()
        tools = DeterministicToolsService(db)
        assert tools.reserve_stock(product.id, 3, order_id=order_id) is True
        reservation = (
            db.query(StockReservation)
            .filter(StockReservation.product_id == product.id, StockReservation.order_id == order_id)
            .one()
        )

        assert tools.release_stock(reservation.id) is True

        db.expire_all()
        persisted_product = db.query(Product).filter(Product.id == product.id).one()
        persisted_reservation = db.query(StockReservation).filter(StockReservation.id == reservation.id).one()
        assert persisted_product.reserved_stock == 0
        assert persisted_reservation.status == "released"
    finally:
        db.close()
        _delete_product(product_id, external_id)
