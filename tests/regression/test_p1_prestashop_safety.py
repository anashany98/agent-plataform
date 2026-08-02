from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import Product
from app.services.deterministic_tools import (
    BusinessRuleError,
    DeterministicToolsService,
)
from app.services.prestashop_adapter import (
    PrestaShopAdapter,
    PrestaShopIntegrationError,
)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _parse_limit(params: dict[str, Any]) -> tuple[int, int]:
    offset, size = str(params["limit"]).split(",", maxsplit=1)
    return int(offset), int(size)


def _specific_price(identifier: int) -> dict[str, str]:
    return {
        "id": str(identifier),
        "id_shop_group": "0",
        "id_shop": "1",
        "id_cart": "0",
        "id_currency": "1",
        "id_country": "6",
        "id_group": "0",
        "id_customer": "0",
        "id_product_attribute": "0",
        "id_specific_price_rule": "0",
        "price": "-1.000000",
        "from_quantity": "1",
        "reduction": "0.100000",
        "reduction_tax": "0",
        "reduction_type": "percentage",
        "from": "0000-00-00 00:00:00",
        "to": "0000-00-00 00:00:00",
    }


def _combination(identifier: int) -> dict[str, Any]:
    return {
        "id": str(identifier),
        "id_product": "42",
        "reference": f"PS-42-{identifier}",
        "price": "0.000000",
        "default_on": "0",
        "minimal_quantity": "1",
        "associations": {"product_option_values": []},
    }


def _adapter() -> PrestaShopAdapter:
    adapter = PrestaShopAdapter()
    adapter.shop_id = "1"
    adapter.country_id = "6"
    adapter.fiscal_country_id = "6"
    adapter.currency_id = "1"
    return adapter


def test_specific_prices_fetches_rows_after_the_first_500() -> None:
    source_rows = [_specific_price(identifier) for identifier in range(1, 503)]
    calls: list[dict[str, Any]] = []

    async def fake_get(resource: str, params: dict[str, Any]) -> dict[str, Any]:
        assert resource == "specific_prices"
        calls.append(deepcopy(params))
        offset, size = _parse_limit(params)
        return {"specific_prices": deepcopy(source_rows[offset : offset + size])}

    adapter = _adapter()
    adapter._get = fake_get  # type: ignore[method-assign]

    result = asyncio.run(adapter.get_specific_prices("42"))

    assert len(result) == 502
    assert result[-1]["id"] == "502"
    assert [params["limit"] for params in calls] == ["0,500", "500,500"]


def test_combinations_fetches_all_association_ids_after_the_first_500() -> None:
    source_rows = [_combination(identifier) for identifier in range(1, 503)]
    calls: list[dict[str, Any]] = []

    async def fake_get(resource: str, params: dict[str, Any]) -> dict[str, Any]:
        assert resource == "combinations"
        calls.append(deepcopy(params))
        requested = {
            value
            for value in str(params["filter[id]"]).removeprefix("[").removesuffix("]").split("|")
            if value
        }
        offset, size = _parse_limit(params)
        matching = [row for row in source_rows if row["id"] in requested]
        return {"combinations": deepcopy(matching[offset : offset + size])}

    async def fake_stock(_product_id: str, _combination_id: str | None = None) -> int:
        return 7

    adapter = _adapter()
    adapter._get = fake_get  # type: ignore[method-assign]
    adapter.get_stock = fake_stock  # type: ignore[method-assign]
    product = {
        "associations": {
            "combinations": [{"id": str(identifier)} for identifier in range(1, 503)]
        }
    }

    result = asyncio.run(adapter.get_combinations("42", product))

    assert len(result) == 502
    assert result[-1]["id"] == "502"
    assert len(calls) == 2
    assert [len(str(params["filter[id]"]).split("|")) for params in calls] == [500, 2]


def test_combinations_paginate_when_product_associations_are_not_available() -> None:
    source_rows = [_combination(identifier) for identifier in range(1, 503)]
    calls: list[dict[str, Any]] = []

    async def fake_get(resource: str, params: dict[str, Any]) -> dict[str, Any]:
        assert resource == "combinations"
        assert params["filter[id_product]"] == "[42]"
        calls.append(deepcopy(params))
        offset, size = _parse_limit(params)
        return {"combinations": deepcopy(source_rows[offset : offset + size])}

    async def fake_stock(_product_id: str, _combination_id: str | None = None) -> int:
        return 7

    adapter = _adapter()
    adapter._get = fake_get  # type: ignore[method-assign]
    adapter.get_stock = fake_stock  # type: ignore[method-assign]

    result = asyncio.run(adapter.get_combinations("42"))

    assert len(result) == 502
    assert result[-1]["id"] == "502"
    assert [params["limit"] for params in calls] == ["0,500", "500,500"]


def test_specific_price_pagination_fails_closed_when_offset_is_ignored() -> None:
    first_page = [_specific_price(identifier) for identifier in range(1, 501)]

    async def fake_get(resource: str, params: dict[str, Any]) -> dict[str, Any]:
        assert resource == "specific_prices"
        assert "limit" in params
        return {"specific_prices": deepcopy(first_page)}

    adapter = _adapter()
    adapter._get = fake_get  # type: ignore[method-assign]

    with pytest.raises(PrestaShopIntegrationError, match="paginación"):
        asyncio.run(adapter.get_specific_prices("42"))


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with installation_scope("test-installation"):
        session = test_session()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()


def _persist_product(
    db: Session,
    *,
    identifier: str,
    source: str = "prestashop",
    attributes: dict[str, Any] | None = None,
) -> Product:
    product = Product(
        id=identifier,
        external_id=f"external-{identifier}",
        sku=f"SKU-{identifier}",
        name=f"Producto seguro {identifier}",
        description="Fixture sintético de seguridad PrestaShop",
        category="Seguridad",
        attributes=deepcopy(attributes or {}),
        source=source,
        base_price=Decimal("100.0000"),
        tax_rate=Decimal("0.210000"),
        stock_quantity=10,
        reserved_stock=0,
    )
    db.add(product)
    db.commit()
    return product


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active", False),
        ("show_price", False),
        ("available_for_order", False),
        ("active", None),
        ("show_price", "yes"),
    ],
    ids=[
        "inactive",
        "price-hidden",
        "not-orderable",
        "missing-flag",
        "malformed-flag",
    ],
)
def test_prestashop_products_fail_closed_for_search_exposure_and_pricing(
    db: Session,
    field: str,
    value: Any,
) -> None:
    attributes: dict[str, Any] = {
        "active": True,
        "show_price": True,
        "available_for_order": True,
    }
    if value is None:
        attributes.pop(field)
    else:
        attributes[field] = value
    product = _persist_product(
        db,
        identifier=f"blocked-{field}-{str(value).lower()}",
        attributes=attributes,
    )
    service = DeterministicToolsService(db)

    assert product.id not in {
        row["id"] for row in service.search_products("Producto seguro", limit=200)
    }
    assert product.id not in {row["id"] for row in service.search_products("", limit=200)}
    with pytest.raises(BusinessRuleError):
        service.get_product(product.id)
    with pytest.raises(BusinessRuleError):
        service.calculate_price(product.id, 1)


def test_explicitly_sellable_prestashop_product_remains_available(db: Session) -> None:
    product = _persist_product(
        db,
        identifier="sellable-prestashop",
        attributes={
            "active": True,
            "show_price": True,
            "available_for_order": True,
        },
    )
    service = DeterministicToolsService(db)

    assert service.get_product(product.id)["id"] == product.id
    assert service.calculate_price(product.id, 1)["base_unit_price"] == 100.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active", "0"),
        ("show_price", "0"),
        ("available_for_order", "0"),
        ("show_price", None),
    ],
    ids=["inactive", "price-hidden", "not-orderable", "missing-flag"],
)
def test_adapter_search_does_not_expose_non_sellable_products(
    field: str,
    value: str | None,
) -> None:
    raw_product: dict[str, Any] = {
        "id": "42",
        "reference": "PS-42",
        "name": "Producto oculto",
        "description_short": "No debe exponerse",
        "price": "999.000000",
        "id_tax_rules_group": "0",
        "active": "1",
        "show_price": "1",
        "available_for_order": "1",
    }
    if value is None:
        raw_product.pop(field)
    else:
        raw_product[field] = value

    async def fake_get(resource: str, _params: dict[str, Any]) -> dict[str, Any]:
        assert resource == "products"
        return {"products": [deepcopy(raw_product)]}

    adapter = _adapter()
    adapter._get = fake_get  # type: ignore[method-assign]

    assert asyncio.run(adapter.search_products("oculto", include_details=False)) == []
