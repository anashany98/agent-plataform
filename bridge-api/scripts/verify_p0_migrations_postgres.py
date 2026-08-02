"""Verify P0 Alembic adoption and downgrade/re-upgrade on disposable PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config
from app.installation_context import installation_scope
from app.models.models import Customer, Product, StockReservation
from app.services.deterministic_tools import DeterministicToolsService
from scripts.verify_p0_postgres import (
    _cleanup_verification_data,
    _require,
    _validated_ephemeral_context,
)

BRIDGE_API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BRIDGE_API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BRIDGE_API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _verify_head_cycle(
    engine,
    config: Config,
    installation_id: str,
    run_id: str,
) -> dict[str, object]:
    command.upgrade(config, "head")
    _require(_current_revision(engine) == "0002", "clean upgrade did not reach 0002")
    customer_id = f"p0-cycle-customer-{run_id}"
    product_id = f"p0-cycle-product-{run_id}"
    with installation_scope(installation_id):
        session = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            session.add_all(
                [
                    Customer(
                        id=customer_id,
                        name="P0 migration-cycle customer",
                        email=f"p0-cycle-{run_id}@example.invalid",
                    ),
                    Product(
                        id=product_id,
                        external_id=f"p0-cycle-external-{run_id}",
                        sku=f"P0-CYCLE-{run_id}",
                        name="P0 migration-cycle product",
                        source="local",
                        base_price=Decimal("25.00"),
                        tax_rate=Decimal("0.21"),
                        stock_quantity=5,
                        reserved_stock=0,
                    ),
                ]
            )
            session.commit()
            tools = DeterministicToolsService(session)
            quote = tools.create_quote(
                customer_id,
                [{"product_id": product_id, "qty": 2}],
                source_message_id=f"p0-cycle-message-{run_id}",
            )
            order = tools.confirm_quote_transactional(
                quote["quote_id"],
                f"p0-cycle-confirm-{run_id}",
                quote["confirmation_token"],
                confirmed_by=customer_id,
            )
            reservation = (
                session.query(StockReservation)
                .filter(StockReservation.order_id == order["order_id"])
                .one()
            )
            reservation_id = str(reservation.id)
            _require(reservation.status == "active", "cycle fixture reservation is not active")
            _require(reservation.expires_at is not None, "cycle fixture reservation lacks expiry")
        finally:
            session.close()

    command.downgrade(config, "base")
    _require(_current_revision(engine) is None, "safe downgrade did not move the revision to base")
    with engine.connect() as connection:
        preserved = connection.execute(
            text(
                "SELECT p.reserved_stock, r.status, r.expires_at "
                "FROM products p JOIN stock_reservations r "
                "ON r.installation_id = p.installation_id AND r.product_id = p.id "
                "WHERE p.installation_id = :installation_id AND p.id = :product_id "
                "AND r.id = :reservation_id"
            ),
            {
                "installation_id": installation_id,
                "product_id": product_id,
                "reservation_id": reservation_id,
            },
        ).one_or_none()
    _require(preserved is not None, "safe downgrade lost the active reservation fixture")
    _require(preserved[0] == 2, "safe downgrade changed reserved stock", preserved)
    _require(preserved[1] == "active", "safe downgrade changed reservation state", preserved)
    _require(preserved[2] is not None, "safe downgrade removed reservation expiry", preserved)

    command.upgrade(config, "head")
    _require(_current_revision(engine) == "0002", "re-upgrade did not return to 0002")
    with installation_scope(installation_id):
        session = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            product = session.get(Product, product_id)
            reservation = session.get(StockReservation, reservation_id)
            _require(product is not None, "re-upgrade lost the product fixture")
            _require(reservation is not None, "re-upgrade lost the reservation fixture")
            _require(product.reserved_stock == 2, "re-upgrade changed reserved stock")
            _require(reservation.status == "active", "re-upgrade changed reservation state")
            _require(reservation.expires_at is not None, "re-upgrade removed reservation expiry")
        finally:
            session.close()
    return {
        "mode": "head-cycle",
        "revision": "0002",
        "fixture_preserved": True,
        "active_reservation_preserved": True,
    }


def _insert_historical_fixture(engine, installation_id: str, run_id: str) -> dict[str, str]:
    identifiers = {
        "user": f"p0-legacy-user-{run_id}",
        "pricelist": f"p0-legacy-pricelist-{run_id}",
        "customer": f"p0-legacy-customer-{run_id}",
        "product": f"p0-legacy-product-{run_id}",
        "quote": f"p0-legacy-quote-{run_id}",
        "order": f"p0-legacy-order-{run_id}",
        "reservation": f"p0-legacy-reservation-{run_id}",
    }
    created_at = datetime(2026, 1, 2, 3, 4, 5)
    items = json.dumps([{"product_id": identifiers["product"], "qty": 1}])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, password_hash, role, installation_id, is_active, "
                "must_change_password, token_version, created_at) VALUES "
                "(:id, :username, 'synthetic-hash', 'admin', :installation_id, true, false, 0, :created_at)"
            ),
            {
                "id": identifiers["user"],
                "username": f"p0-legacy-{run_id}",
                "installation_id": installation_id,
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO pricelists (id, name, discount_percentage) "
                "VALUES (:id, 'P0 legacy pricelist', 7.5)"
            ),
            {"id": identifiers["pricelist"]},
        )
        connection.execute(
            text(
                "INSERT INTO customers "
                "(id, name, email, pricelist_id, tax_exempt, created_at) VALUES "
                "(:id, 'P0 legacy customer', :email, :pricelist_id, false, :created_at)"
            ),
            {
                "id": identifiers["customer"],
                "email": f"p0-legacy-{run_id}@example.invalid",
                "pricelist_id": identifiers["pricelist"],
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO products "
                "(id, external_id, sku, name, source, base_price, tax_rate, stock_quantity, "
                "reserved_stock, created_at, updated_at) VALUES "
                "(:id, :external_id, :sku, 'P0 legacy product', 'local', 10, 0.21, 5, 0, "
                ":created_at, :created_at)"
            ),
            {
                "id": identifiers["product"],
                "external_id": f"p0-legacy-external-{run_id}",
                "sku": f"P0-LEGACY-{run_id}",
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO quotes "
                "(id, customer_id, confirmation_token, items, subtotal, tax_total, shipping_total, "
                "grand_total, currency, status, created_at, confirmed_at) VALUES "
                "(:id, :customer_id, 'LEGACY-TOKEN', CAST(:items AS json), 10, 2.10, 0, "
                "12.10, 'EUR', 'confirmed', :created_at, :created_at)"
            ),
            {
                "id": identifiers["quote"],
                "customer_id": identifiers["customer"],
                "items": items,
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO orders "
                "(id, customer_id, quote_id, idempotency_key, items, subtotal, tax_total, "
                "shipping_total, grand_total, currency, status, created_at) VALUES "
                "(:id, :customer_id, :quote_id, :idempotency_key, CAST(:items AS json), "
                "10, 2.10, 0, 12.10, 'EUR', 'confirmed', :created_at)"
            ),
            {
                "id": identifiers["order"],
                "customer_id": identifiers["customer"],
                "quote_id": identifiers["quote"],
                "idempotency_key": f"p0-legacy-key-{run_id}",
                "items": items,
                "created_at": created_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO stock_reservations "
                "(id, order_id, product_id, quantity_reserved, status, created_at) VALUES "
                "(:id, :order_id, :product_id, 1, 'released', :created_at)"
            ),
            {
                "id": identifiers["reservation"],
                "order_id": identifiers["order"],
                "product_id": identifiers["product"],
                "created_at": created_at,
            },
        )
    return identifiers


def _verify_historical_upgrade(
    engine,
    config: Config,
    installation_id: str,
    run_id: str,
) -> dict[str, object]:
    command.upgrade(config, "0001")
    _require(_current_revision(engine) == "0001", "historical setup did not reach 0001")
    identifiers = _insert_historical_fixture(engine, installation_id, run_id)
    command.upgrade(config, "head")
    _require(_current_revision(engine) == "0002", "historical upgrade did not reach 0002")

    expected_token_hash = hashlib.sha256(b"LEGACY-TOKEN").hexdigest()
    with engine.connect() as connection:
        installation_values = connection.execute(
            text(
                "SELECT installation_id FROM pricelists WHERE id = :pricelist "
                "UNION ALL SELECT installation_id FROM customers WHERE id = :customer "
                "UNION ALL SELECT installation_id FROM products WHERE id = :product "
                "UNION ALL SELECT installation_id FROM quotes WHERE id = :quote "
                "UNION ALL SELECT installation_id FROM orders WHERE id = :order "
                "UNION ALL SELECT installation_id FROM stock_reservations WHERE id = :reservation"
            ),
            identifiers,
        ).scalars().all()
        quote = connection.execute(
            text(
                "SELECT confirmation_token, confirmation_payload_hash, "
                "confirmation_expires_at, confirmation_consumed_at "
                "FROM quotes WHERE id = :quote"
            ),
            identifiers,
        ).one_or_none()
        reservation = connection.execute(
            text(
                "SELECT status, expires_at, released_at, installation_id "
                "FROM stock_reservations WHERE id = :reservation"
            ),
            identifiers,
        ).one_or_none()
        user_installation = connection.scalar(
            text("SELECT installation_id FROM users WHERE id = :user"),
            identifiers,
        )
    _require(
        installation_values == [installation_id] * 6,
        "historical rows were not backfilled into exactly one installation",
        installation_values,
    )
    _require(user_installation == installation_id, "historical user installation changed")
    _require(quote is not None, "historical quote disappeared")
    _require(quote[0] == expected_token_hash, "historical confirmation token was not hashed")
    _require(
        isinstance(quote[1], str) and len(quote[1]) == 64,
        "historical confirmation payload hash is invalid",
        quote[1],
    )
    _require(quote[2] is not None, "historical confirmation was not expired during adoption")
    _require(quote[3] is not None, "confirmed historical quote was not marked consumed")
    _require(reservation is not None, "historical reservation disappeared")
    _require(reservation[0] == "released", "historical reservation status changed")
    _require(reservation[1] is not None, "historical reservation lacks expiry")
    _require(reservation[2] is not None, "historical released reservation lacks release time")
    _require(reservation[3] == installation_id, "historical reservation tenant is wrong")

    foreign_keys = {
        foreign_key.get("name")
        for table_name in (
            "customers",
            "quotes",
            "orders",
            "stock_reservations",
            "invoice_drafts",
            "conversation_states",
            "rag_chunks",
        )
        for foreign_key in inspect(engine).get_foreign_keys(table_name)
        if str(foreign_key.get("name") or "").startswith("fk_")
        and "installation" in str(foreign_key.get("name"))
    }
    _require(len(foreign_keys) == 12, "historical upgrade lacks composite foreign keys", foreign_keys)
    return {
        "mode": "historical-upgrade",
        "revision": "0002",
        "fixture_preserved": True,
        "legacy_token_hashed": True,
        "composite_foreign_keys": len(foreign_keys),
    }


def _legacy_fixture_exists(engine) -> bool:
    inspector = inspect(engine)
    return inspector.has_table("products") and "installation_id" not in {
        column["name"] for column in inspector.get_columns("products")
    }


def _cleanup_legacy_fixture(engine, run_id: str) -> None:
    identifiers = {
        "user": f"p0-legacy-user-{run_id}",
        "pricelist": f"p0-legacy-pricelist-{run_id}",
        "customer": f"p0-legacy-customer-{run_id}",
        "product": f"p0-legacy-product-{run_id}",
        "quote": f"p0-legacy-quote-{run_id}",
        "order": f"p0-legacy-order-{run_id}",
        "reservation": f"p0-legacy-reservation-{run_id}",
    }
    statements = (
        ("DELETE FROM stock_reservations WHERE id = :reservation", identifiers),
        ("DELETE FROM orders WHERE id = :order", identifiers),
        ("DELETE FROM quotes WHERE id = :quote", identifiers),
        ("DELETE FROM customers WHERE id = :customer", identifiers),
        ("DELETE FROM products WHERE id = :product", identifiers),
        ("DELETE FROM pricelists WHERE id = :pricelist", identifiers),
        ("DELETE FROM users WHERE id = :user", identifiers),
    )
    with engine.begin() as connection:
        for statement, parameters in statements:
            connection.execute(text(statement), parameters)


def main() -> None:
    database_url, installation_id, run_id = _validated_ephemeral_context()
    mode = os.environ.get("P0_MIGRATION_VERIFY_MODE", "").strip().lower()
    _require(mode in {"head-cycle", "historical-upgrade"}, "unknown migration verification mode", mode)
    engine = create_engine(database_url, pool_pre_ping=True)
    config = _alembic_config(database_url)
    result: dict[str, object] | None = None
    try:
        _require(engine.dialect.name == "postgresql", "migration verifier requires PostgreSQL")
        if mode == "head-cycle":
            result = _verify_head_cycle(engine, config, installation_id, run_id)
        else:
            result = _verify_historical_upgrade(engine, config, installation_id, run_id)
    finally:
        if inspect(engine).has_table("products"):
            if _legacy_fixture_exists(engine):
                _cleanup_legacy_fixture(engine, run_id)
            else:
                _cleanup_verification_data(
                    engine,
                    (installation_id, f"{installation_id}-foreign"),
                )
        engine.dispose()
    _require(result is not None, "migration verification produced no result")
    print(json.dumps({"status": "verified", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
