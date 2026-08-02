from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest
from app.config import settings
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import Customer, Order, Pricelist, Product, StockReservation
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

# The fixture shapes below follow the official PrestaShop Webservice resources:
# products, combinations, stock_availables, tax_rules, taxes and
# specific_prices. Values are strings because that is how the JSON Webservice
# commonly serializes database-backed scalar fields.
PRODUCT = {
    "id": "42",
    "reference": "PS-42",
    "name": {"language": [{"id": "1", "value": "Silla contractual"}]},
    "description_short": {"language": [{"id": "1", "value": "Producto de contrato"}]},
    "price": "100.000000",
    "id_category_default": "2",
    "id_tax_rules_group": "53",
    "id_default_combination": "900",
    "id_shop_default": "1",
    "active": "1",
    "available_for_order": "1",
    "show_price": "1",
    "associations": {"combinations": [{"id": "900"}, {"id": "901"}]},
}

COMBINATIONS = [
    {
        "id": "900",
        "id_product": "42",
        "reference": "PS-42-DEFAULT",
        "price": "20.000000",
        "default_on": "1",
        "minimal_quantity": "1",
        "associations": {"product_option_values": []},
    },
    {
        "id": "901",
        "id_product": "42",
        "reference": "PS-42-OTHER",
        "price": "5.000000",
        "default_on": "0",
        "minimal_quantity": "1",
        "associations": {"product_option_values": []},
    },
]

STOCK_ROWS = [
    {
        "id": "3000",
        "id_product": "42",
        "id_product_attribute": "0",
        "id_shop": "1",
        "id_shop_group": "0",
        "quantity": "0",
    },
    {
        "id": "3001",
        "id_product": "42",
        "id_product_attribute": "900",
        "id_shop": "1",
        "id_shop_group": "0",
        "quantity": "3",
    },
    {
        "id": "3002",
        "id_product": "42",
        "id_product_attribute": "901",
        "id_shop": "1",
        "id_shop_group": "0",
        "quantity": "9",
    },
]

TAX_RULE_21_ES = {
    "id": "701",
    "id_tax_rules_group": "53",
    "id_state": "0",
    "id_country": "6",
    "zipcode_from": "0",
    "zipcode_to": "0",
    "id_tax": "21",
    "behavior": "0",
    "description": "IVA general España",
}

TAX_21 = {
    "id": "21",
    "rate": "21.000",
    "active": "1",
    "deleted": "0",
    "name": {"language": [{"id": "1", "value": "IVA ES 21%"}]},
}


def _official_specific_price(
    *,
    identifier: str,
    shop_group_id: str = "0",
    shop_id: str = "1",
    cart_id: str = "0",
    currency_id: str = "1",
    country_id: str = "6",
    customer_id: str = "0",
    group_id: str = "0",
    specific_price_rule_id: str = "0",
    product_attribute_id: str = "900",
    reduction: str = "0.100000",
    reduction_type: str = "percentage",
    reduction_tax: str = "0",
    starts_at: str = "0000-00-00 00:00:00",
    ends_at: str = "0000-00-00 00:00:00",
) -> dict[str, str]:
    return {
        "id": identifier,
        "id_shop_group": shop_group_id,
        "id_shop": shop_id,
        "id_cart": cart_id,
        "id_product": "42",
        "id_product_attribute": product_attribute_id,
        "id_currency": currency_id,
        "id_country": country_id,
        "id_group": group_id,
        "id_customer": customer_id,
        "id_specific_price_rule": specific_price_rule_id,
        "price": "-1.000000",
        "from_quantity": "1",
        "reduction": reduction,
        "reduction_tax": reduction_tax,
        "reduction_type": reduction_type,
        "from": starts_at,
        "to": ends_at,
    }


class OfficialWebserviceResponses:
    """Hermetic `_get` double with official plural resource envelopes."""

    def __init__(
        self,
        *,
        product: dict[str, Any] | None = None,
        combinations: list[dict[str, Any]] | None = None,
        stock_rows: list[dict[str, Any]] | None = None,
        tax_rules: list[dict[str, Any]] | None = None,
        taxes: list[dict[str, Any]] | None = None,
        specific_prices: list[dict[str, Any]] | None = None,
    ) -> None:
        self.product = deepcopy(product or PRODUCT)
        self.combinations = deepcopy(COMBINATIONS if combinations is None else combinations)
        self.stock_rows = deepcopy(STOCK_ROWS if stock_rows is None else stock_rows)
        self.tax_rules = deepcopy([TAX_RULE_21_ES] if tax_rules is None else tax_rules)
        self.taxes = deepcopy([TAX_21] if taxes is None else taxes)
        self.specific_prices = deepcopy(specific_prices or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def _filtered(rows: list[dict[str, Any]], params: dict[str, Any], field: str) -> list[dict[str, Any]]:
        raw = str(params.get(f"filter[{field}]", "")).strip()
        if not raw:
            return rows
        accepted = set(raw.removeprefix("[").removesuffix("]").split("|"))
        return [row for row in rows if str(row.get(field) or "") in accepted]

    async def __call__(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((resource, deepcopy(params)))
        if resource == "products":
            return {"products": [deepcopy(self.product)]}
        if resource == "combinations":
            return {"combinations": deepcopy(self.combinations)}
        if resource == "stock_availables":
            rows = self._filtered(self.stock_rows, params, "id_product")
            rows = self._filtered(rows, params, "id_product_attribute")
            return {"stock_availables": deepcopy(rows)}
        if resource == "specific_prices":
            return {"specific_prices": deepcopy(self.specific_prices)}
        if resource == "tax_rules":
            rows = self._filtered(self.tax_rules, params, "id_tax_rules_group")
            rows = self._filtered(rows, params, "id_country")
            return {"tax_rules": deepcopy(rows)}
        if resource == "taxes":
            return {"taxes": deepcopy(self._filtered(self.taxes, params, "id"))}
        if resource == "countries":
            return {"countries": [{"id": "6", "iso_code": "ES", "active": "1"}]}
        if resource == "currencies":
            return {"currencies": [{"id": "1", "iso_code": "EUR", "active": "1"}]}
        if resource == "categories":
            return {
                "categories": [
                    {"id": "2", "name": {"language": [{"id": "1", "value": "Sillas"}]}}
                ]
            }
        raise AssertionError(f"Recurso Webservice inesperado: {resource}; params={params!r}")


def _adapter(fake_get: OfficialWebserviceResponses, *, country_id: str = "6") -> PrestaShopAdapter:
    adapter = PrestaShopAdapter()
    adapter.shop_id = "1"
    # These explicit numeric contexts deliberately differ from COUNTRY=ES and
    # CURRENCY=EUR. PrestaShop specific-price/tax scopes use resource IDs.
    adapter.country_id = country_id
    adapter.fiscal_country_id = country_id
    adapter.currency_id = "1"
    adapter._get = fake_get  # type: ignore[method-assign]
    return adapter


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
    attributes: dict[str, Any],
    stock_quantity: int = 20,
    tax_rate: Decimal = Decimal("0.21"),
) -> Product:
    product = Product(
        id="contract-product",
        external_id="42",
        sku="PS-CONTRACT-42",
        name="Producto contractual",
        category="Contrato",
        attributes=deepcopy(attributes),
        source="local",
        base_price=Decimal("100.0000"),
        tax_rate=tax_rate,
        stock_quantity=stock_quantity,
        reserved_stock=0,
    )
    db.add(product)
    db.commit()
    return product


def _price_service(db: Session) -> DeterministicToolsService:
    service = DeterministicToolsService(db, country="ES", currency="EUR", default_vat_rate=0.99)
    service.free_shipping_threshold = Decimal("0")
    service.shipping_flat_rate = Decimal("0")
    return service


def test_adapter_resolves_real_tax_rate_and_requests_authority_fields(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_VAT_RATE", 0.99)
    fake_get = OfficialWebserviceResponses()
    adapter = _adapter(fake_get)

    product = asyncio.run(adapter.list_products(limit=1, include_details=True))[0]

    assert Decimal(str(product["tax_rate"])) == Decimal("0.21")
    assert Decimal(str(product["tax_rate"])) != Decimal(str(settings.DEFAULT_VAT_RATE))
    assert product["attributes"]["shop_id"] == "1"
    assert product["attributes"]["country_id"] == "6"
    assert product["attributes"]["currency_id"] == "1"

    list_call = next(
        params
        for resource, params in fake_get.calls
        if resource == "products" and params.get("display") != "full"
    )
    for required_field in ("id_tax_rules_group", "id_default_combination", "id_shop_default"):
        assert required_field in str(list_call["display"])
    assert any(resource == "tax_rules" for resource, _params in fake_get.calls)
    assert any(resource == "taxes" for resource, _params in fake_get.calls)


def test_adapter_treats_tax_rules_group_zero_as_zero_not_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_VAT_RATE", 0.99)
    product_without_tax = {**deepcopy(PRODUCT), "id_tax_rules_group": "0"}
    fake_get = OfficialWebserviceResponses(product=product_without_tax)
    adapter = _adapter(fake_get)

    product = asyncio.run(adapter.list_products(limit=1, include_details=False))[0]

    assert Decimal(str(product["tax_rate"])) == Decimal("0")
    assert not any(resource in {"tax_rules", "taxes"} for resource, _params in fake_get.calls)


@pytest.mark.parametrize(
    ("country_id", "tax_rules"),
    [
        (
            "",
            [
                TAX_RULE_21_ES,
                {**TAX_RULE_21_ES, "id": "702", "id_country": "8", "id_tax": "10"},
            ],
        ),
        (
            "6",
            [
                TAX_RULE_21_ES,
                {**TAX_RULE_21_ES, "id": "703", "id_tax": "10", "description": "Regla solapada"},
            ],
        ),
    ],
    ids=["missing-country-context", "ambiguous-rules"],
)
def test_adapter_fails_closed_when_fiscal_context_is_missing_or_ambiguous(
    monkeypatch,
    country_id: str,
    tax_rules: list[dict[str, Any]],
):
    monkeypatch.setattr(settings, "COUNTRY", "" if not country_id else "ES")
    fake_get = OfficialWebserviceResponses(
        tax_rules=tax_rules,
        taxes=[TAX_21, {**TAX_21, "id": "10", "rate": "10.000"}],
    )
    adapter = _adapter(fake_get, country_id=country_id)

    with pytest.raises(PrestaShopIntegrationError):
        asyncio.run(adapter.list_products(limit=1, include_details=False))


def test_adapter_preserves_default_combination_stock_and_specific_price_scopes():
    official_prices = [
        _official_specific_price(identifier="global"),
        _official_specific_price(identifier="other-shop", shop_id="2"),
        _official_specific_price(identifier="other-customer", customer_id="777"),
        _official_specific_price(identifier="other-group", group_id="888"),
    ]
    fake_get = OfficialWebserviceResponses(specific_prices=official_prices)
    adapter = _adapter(fake_get)

    combinations = asyncio.run(adapter.get_combinations("42", PRODUCT))
    specific_prices = asyncio.run(adapter.get_specific_prices("42"))

    default_combination = next(row for row in combinations if row["default"])
    assert default_combination["id"] == "900"
    assert default_combination["stock_quantity"] == 3
    assert {row["id"] for row in specific_prices} == {
        "global",
        "other-shop",
        "other-customer",
        "other-group",
    }
    assert next(row for row in specific_prices if row["id"] == "other-shop")["shop_id"] == "2"
    assert next(row for row in specific_prices if row["id"] == "other-customer")["customer_id"] == "777"
    assert next(row for row in specific_prices if row["id"] == "other-group")["group_id"] == "888"
    assert next(row for row in specific_prices if row["id"] == "global")["specific_price_rule_id"] == "0"


def test_calculate_price_selects_default_combination_from_adapter(db: Session):
    product_without_tax = {**deepcopy(PRODUCT), "id_tax_rules_group": "0"}
    fake_get = OfficialWebserviceResponses(product=product_without_tax)
    adapter = _adapter(fake_get)
    normalized = asyncio.run(adapter.list_products(limit=1, include_details=True))[0]
    product = _persist_product(
        db,
        attributes=normalized["attributes"],
        stock_quantity=int(normalized["stock_quantity"]),
        tax_rate=Decimal(str(normalized.get("tax_rate", "0"))),
    )

    result = _price_service(db).calculate_price(product.id, 1)

    assert result["combination_id"] == "900"
    assert Decimal(str(result["base_unit_price"])) == Decimal("120.00")


@pytest.mark.parametrize(
    ("scope_field", "scope_value"),
    [
        ("shop_group_id", "20"),
        ("shop_id", "2"),
        ("cart_id", "123"),
        ("currency_id", "2"),
        ("country_id", "8"),
        ("customer_id", "777"),
        ("group_id", "888"),
    ],
    ids=[
        "other-shop-group",
        "other-shop",
        "untrusted-cart",
        "other-currency",
        "other-country",
        "unmapped-customer",
        "unmapped-group",
    ],
)
def test_specific_price_from_other_or_unmapped_scope_is_not_applied(
    db: Session,
    scope_field: str,
    scope_value: str,
):
    bad_scope = {
        "shop_group_id": "10",
        "shop_id": "1",
        "cart_id": "0",
        "currency_id": "1",
        "country_id": "6",
        "customer_id": "0",
        "group_id": "0",
    }
    bad_scope[scope_field] = scope_value
    official_prices = [
        _official_specific_price(identifier="a-global"),
        _official_specific_price(
            identifier="z-out-of-scope",
            reduction="0.500000",
            **bad_scope,
        ),
    ]
    fake_get = OfficialWebserviceResponses(specific_prices=official_prices)
    normalized_prices = asyncio.run(_adapter(fake_get).get_specific_prices("42"))
    attributes = {
        "shop_group_id": "10",
        "shop_id": "1",
        "currency_id": "1",
        "country_id": "6",
        "combinations": [
            {
                "id": "900",
                "reference": "PS-42-DEFAULT",
                "price_impact": 20.0,
                "stock_quantity": 3,
                "default": True,
                "minimal_quantity": 1,
            }
        ],
        "specific_prices": normalized_prices,
    }
    product = _persist_product(db, attributes=attributes)
    # Numeric local IDs intentionally collide with remote PrestaShop IDs. In
    # the absence of an explicit mapping they must still not authorize a
    # customer/group scoped rule.
    db.add(Pricelist(id="888", name="Tarifa local sin mapping", discount_percentage=Decimal("0")))
    db.add(Customer(id="777", name="Cliente local sin mapping", email="local-777@example.invalid", pricelist_id="888"))
    db.commit()

    result = _price_service(db).calculate_price(
        product.id,
        1,
        customer_id="777",
        combination_id="900",
    )

    assert result["specific_price_id"] == "a-global"
    assert Decimal(str(result["discounted_unit_price"])) == Decimal("108.00")


@pytest.mark.parametrize(
    ("reduction_tax", "reduction"),
    [("0", "10.000000"), ("1", "12.100000")],
    ids=["amount-tax-excluded", "amount-tax-included"],
)
def test_amount_reduction_is_converted_deterministically(
    db: Session,
    reduction_tax: str,
    reduction: str,
):
    official_price = _official_specific_price(
        identifier="amount-rule",
        product_attribute_id="0",
        reduction=reduction,
        reduction_type="amount",
        reduction_tax=reduction_tax,
    )
    fake_get = OfficialWebserviceResponses(specific_prices=[official_price])
    normalized_price = asyncio.run(_adapter(fake_get).get_specific_prices("42"))[0]
    product = _persist_product(
        db,
        attributes={
            "shop_id": "1",
            "currency_id": "1",
            "country_id": "6",
            "combinations": [],
            "specific_prices": [normalized_price],
        },
    )

    result = _price_service(db).calculate_price(product.id, 1)

    # EUR 10 tax-exclusive and EUR 12.10 tax-inclusive are equivalent at 21%.
    assert Decimal(str(result["discounted_unit_price"])) == Decimal("90.00")
    assert Decimal(str(result["subtotal"])) == Decimal("90.00")
    assert Decimal(str(result["vat_amount"])) == Decimal("18.90")
    assert Decimal(str(result["grand_total"])) == Decimal("108.90")


def test_specific_price_precedence_matches_prestashop_dates_after_higher_keys(db: Session):
    official_prices = [
        _official_specific_price(
            identifier="99",
            product_attribute_id="0",
            reduction="0.100000",
            starts_at="2020-01-01 00:00:00",
            ends_at="2099-12-31 23:59:59",
        ),
        _official_specific_price(
            identifier="100",
            product_attribute_id="0",
            reduction="0.500000",
            starts_at="2024-01-01 00:00:00",
            ends_at="2099-12-31 23:59:59",
        ),
    ]
    normalized_prices = asyncio.run(
        _adapter(OfficialWebserviceResponses(specific_prices=official_prices)).get_specific_prices("42")
    )
    product = _persist_product(
        db,
        attributes={
            "shop_id": "1",
            "currency_id": "1",
            "country_id": "6",
            "combinations": [],
            "specific_prices": normalized_prices,
        },
    )

    result = _price_service(db).calculate_price(product.id, 1)

    assert result["specific_price_id"] == "100"
    assert Decimal(str(result["discounted_unit_price"])) == Decimal("50.00")


def test_specific_price_rule_id_precedes_score_and_dates(db: Session):
    official_prices = [
        _official_specific_price(
            identifier="direct-rule",
            product_attribute_id="0",
            specific_price_rule_id="0",
            reduction="0.100000",
            starts_at="2020-01-01 00:00:00",
            ends_at="2099-12-31 23:59:59",
        ),
        _official_specific_price(
            identifier="generated-rule",
            product_attribute_id="0",
            specific_price_rule_id="7",
            reduction="0.500000",
            starts_at="2024-01-01 00:00:00",
            ends_at="2099-12-31 23:59:59",
        ),
    ]
    normalized_prices = asyncio.run(
        _adapter(OfficialWebserviceResponses(specific_prices=official_prices)).get_specific_prices("42")
    )
    product = _persist_product(
        db,
        attributes={
            "shop_id": "1",
            "currency_id": "1",
            "country_id": "6",
            "combinations": [],
            "specific_prices": normalized_prices,
        },
    )

    result = _price_service(db).calculate_price(product.id, 1)

    assert result["specific_price_id"] == "direct-rule"
    assert Decimal(str(result["discounted_unit_price"])) == Decimal("90.00")


def test_specific_price_fails_closed_when_remote_score_priority_is_required(db: Session):
    official_prices = [
        _official_specific_price(
            identifier="shop-specific",
            product_attribute_id="0",
            shop_id="1",
            currency_id="0",
        ),
        _official_specific_price(
            identifier="currency-specific",
            product_attribute_id="0",
            shop_id="0",
            currency_id="1",
        ),
    ]
    normalized_prices = asyncio.run(
        _adapter(OfficialWebserviceResponses(specific_prices=official_prices)).get_specific_prices("42")
    )
    product = _persist_product(
        db,
        attributes={
            "shop_id": "1",
            "currency_id": "1",
            "country_id": "6",
            "combinations": [],
            "specific_prices": normalized_prices,
        },
    )

    with pytest.raises(BusinessRuleError, match=r"(?i)(prioridad|ambiguo|autoridad)"):
        _price_service(db).calculate_price(product.id, 1)


def test_quote_free_shipping_threshold_uses_aggregate_subtotal(db: Session):
    products = []
    for index in (1, 2):
        products.append(
            Product(
                id=f"shipping-product-{index}",
                external_id=f"shipping-external-{index}",
                sku=f"SHIP-{index}",
                name=f"Producto envío {index}",
                source="local",
                base_price=Decimal("60.00"),
                tax_rate=Decimal("0"),
                stock_quantity=10,
                reserved_stock=0,
            )
        )
    customer = Customer(
        id="shipping-customer",
        name="Cliente envío",
        email="shipping@example.invalid",
    )
    db.add_all([*products, customer])
    db.commit()
    service = _price_service(db)
    service.free_shipping_threshold = Decimal("100.00")
    service.shipping_flat_rate = Decimal("15.00")

    quote = service.create_quote(
        customer.id,
        [{"product_id": product.id, "qty": 1} for product in products],
    )

    assert Decimal(str(quote["subtotal"])) == Decimal("120.00")
    assert Decimal(str(quote["shipping_total"])) == Decimal("0.00")
    assert Decimal(str(quote["grand_total"])) == Decimal("120.00")


def test_local_variant_cannot_confirm_against_aggregate_stock_without_variant_authority(db: Session):
    variant_stock = [
        {**STOCK_ROWS[0], "quantity": "0"},
        {**STOCK_ROWS[1], "quantity": "0"},
        {**STOCK_ROWS[2], "quantity": "10"},
    ]
    fake_get = OfficialWebserviceResponses(stock_rows=variant_stock)
    adapter = _adapter(fake_get)
    combinations = asyncio.run(adapter.get_combinations("42", PRODUCT))
    aggregate_stock = asyncio.run(adapter.get_stock("42"))
    assert next(row for row in combinations if row["id"] == "900")["stock_quantity"] == 0
    assert aggregate_stock == 10

    product = _persist_product(
        db,
        attributes={
            "default_combination_id": "900",
            "shop_id": "1",
            "currency_id": "1",
            "country_id": "6",
            "combinations": combinations,
            "specific_prices": [],
        },
        stock_quantity=aggregate_stock,
    )
    db.add(Customer(id="variant-customer", name="Cliente variante", email="variant@example.invalid"))
    db.commit()
    service = _price_service(db)

    with pytest.raises(BusinessRuleError, match=r"(?i)(stock|variante|combinaci.n|autoridad)"):
        quote = service.create_quote(
            "variant-customer",
            [{"product_id": product.id, "combination_id": "900", "qty": 1}],
        )
        service.confirm_quote_transactional(
            quote["quote_id"],
            "variant-no-aggregate-authority",
            quote["confirmation_token"],
            confirmed_by="variant-customer",
        )

    assert db.query(Order).count() == 0
    assert db.query(StockReservation).count() == 0
    db.refresh(product)
    assert product.reserved_stock == 0
