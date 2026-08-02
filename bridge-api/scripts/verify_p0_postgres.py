"""Verify P0 transaction invariants against an isolated PostgreSQL database."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.installation_context import installation_scope
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    Customer,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    StockReservation,
    User,
)
from app.services.deterministic_tools import DeterministicToolsService, InsufficientStockError


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _require(condition: bool, message: str, details: object | None = None) -> None:
    if condition:
        return
    suffix = f": {details!r}" if details is not None else ""
    raise RuntimeError(f"P0 PostgreSQL verification failed: {message}{suffix}")


def _validated_ephemeral_context() -> tuple[str, str, str]:
    database_url = _required_environment("DATABASE_URL")
    installation_id = _required_environment("INSTALLATION_ID")
    run_id = _required_environment("P0_VERIFY_RUN_ID").lower()
    acknowledgement = _required_environment("P0_VERIFY_EPHEMERAL_ACK")
    _require(
        acknowledgement == "DISPOSABLE-P0-POSTGRES-ONLY",
        "the destructive-test acknowledgement is missing or invalid",
    )
    _require(
        re.fullmatch(r"[0-9a-f]{12}", run_id) is not None,
        "P0_VERIFY_RUN_ID must be exactly 12 lowercase hexadecimal characters",
        run_id,
    )
    expected_database = f"p0_verify_{run_id}"
    expected_installation = f"p0-verify-{run_id}"
    parsed_url = make_url(database_url)
    _require(
        parsed_url.database == expected_database,
        "DATABASE_URL does not name the run-bound disposable database",
        {"expected": expected_database, "actual": parsed_url.database},
    )
    _require(
        installation_id == expected_installation,
        "INSTALLATION_ID is not bound to this disposable verification run",
        {"expected": expected_installation, "actual": installation_id},
    )
    return database_url, installation_id, run_id


def _cleanup_verification_data(engine, installation_ids: tuple[str, str]) -> None:
    # Exact installation-scoped cleanup. The run-bound database guard above
    # prevents this verifier from ever targeting an operational installation.
    tables = (
        "rag_chunks",
        "conversation_states",
        "stock_reservations",
        "invoice_drafts",
        "approval_requests",
        "audit_logs",
        "idempotency_records",
        "orders",
        "quotes",
        "customers",
        "products",
        "pricelists",
        "users",
        "rag_documents",
    )
    parameters = {
        "local_installation": installation_ids[0],
        "foreign_installation": installation_ids[1],
    }
    with engine.begin() as connection:
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for table_name in tables:
            connection.execute(
                text(
                    f'DELETE FROM "{table_name}" '
                    "WHERE installation_id IN (:local_installation, :foreign_installation)"
                ),
                parameters,
            )


def _create_reservation_pair(
    session_factory,
    installation_id: str,
    suffix: str,
    label: str,
) -> dict[str, str]:
    product_id = f"p0-pg-{label}-product-{suffix}"
    customer_ids = [f"p0-pg-{label}-customer-{suffix}-{index}" for index in (1, 2)]
    with installation_scope(installation_id):
        session = session_factory()
        try:
            session.add(
                Product(
                    id=product_id,
                    external_id=f"p0-pg-{label}-external-{suffix}",
                    sku=f"P0-PG-{label.upper()}-{suffix}",
                    name=f"PostgreSQL P0 {label} race product",
                    source="local",
                    base_price=Decimal("15.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=10,
                    reserved_stock=0,
                )
            )
            session.add_all(
                Customer(
                    id=customer_id,
                    name=f"PostgreSQL P0 {label} customer {index}",
                    email=f"{customer_id}@example.invalid",
                )
                for index, customer_id in enumerate(customer_ids, start=1)
            )
            session.commit()
            order_ids: list[str] = []
            reservation_ids: list[str] = []
            for index, customer_id in enumerate(customer_ids, start=1):
                tools = DeterministicToolsService(session)
                quote = tools.create_quote(
                    customer_id,
                    [{"product_id": product_id, "qty": 2}],
                    source_message_id=f"p0-pg-{label}-message-{suffix}-{index}",
                )
                order = tools.confirm_quote_transactional(
                    quote["quote_id"],
                    f"p0-pg-{label}:{quote['quote_id']}",
                    quote["confirmation_token"],
                    confirmed_by=customer_id,
                )
                order_ids.append(str(order["order_id"]))
                reservation_ids.append(
                    str(
                        session.scalar(
                            select(StockReservation.id).where(
                                StockReservation.order_id == order["order_id"]
                            )
                        )
                    )
                )
            return {
                "product_id": product_id,
                "target_order_id": order_ids[0],
                "target_reservation_id": reservation_ids[0],
                "sibling_reservation_id": reservation_ids[1],
            }
        finally:
            session.close()


def _assert_race_inventory(
    session_factory,
    installation_id: str,
    fixture: dict[str, str],
    expected_statuses: set[str],
) -> str:
    with installation_scope(installation_id):
        session = session_factory()
        try:
            product = session.get(Product, fixture["product_id"])
            target = session.get(StockReservation, fixture["target_reservation_id"])
            sibling = session.get(StockReservation, fixture["sibling_reservation_id"])
            _require(product is not None, "race product disappeared", fixture)
            _require(target is not None, "target reservation disappeared", fixture)
            _require(sibling is not None, "sibling reservation disappeared", fixture)
            _require(product.reserved_stock == 2, "race changed reserved stock twice", product.reserved_stock)
            _require(target.status in expected_statuses, "unexpected target reservation status", target.status)
            _require(target.released_at is not None, "target reservation has no release timestamp")
            _require(sibling.status == "active", "sibling reservation was mutated", sibling.status)
            return str(target.status)
        finally:
            session.close()


def _run_verification(engine, installation_id: str) -> dict[str, object]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:12]
    customer_id = f"p0-pg-customer-{suffix}"
    product_id = f"p0-pg-product-{suffix}"

    expected_composite_foreign_keys = {
        "fk_customer_installation_pricelist": ("installation_id", "pricelist_id"),
        "fk_quote_installation_customer": ("installation_id", "customer_id"),
        "fk_order_installation_customer": ("installation_id", "customer_id"),
        "fk_order_installation_quote": ("installation_id", "quote_id"),
        "fk_reservation_installation_order": ("installation_id", "order_id"),
        "fk_reservation_installation_product": ("installation_id", "product_id"),
        "fk_invoice_installation_order": ("installation_id", "order_id"),
        "fk_invoice_installation_customer": ("installation_id", "customer_id"),
        "fk_conversation_installation_customer": ("installation_id", "customer_id"),
        "fk_conversation_installation_quote": ("installation_id", "active_quote_id"),
        "fk_conversation_installation_order": ("installation_id", "order_id"),
        "fk_rag_chunk_installation_document": ("installation_id", "document_id"),
    }
    inspected_foreign_keys: dict[str, dict[str, object]] = {}
    database_inspector = inspect(engine)
    for table_name in (
        "customers",
        "quotes",
        "orders",
        "stock_reservations",
        "invoice_drafts",
        "conversation_states",
        "rag_chunks",
    ):
        for foreign_key in database_inspector.get_foreign_keys(table_name):
            name = str(foreign_key.get("name") or "")
            if name in expected_composite_foreign_keys:
                inspected_foreign_keys[name] = foreign_key
    _require(
        set(inspected_foreign_keys) == set(expected_composite_foreign_keys),
        "composite foreign-key set differs from the required contract",
        {
            "expected": sorted(expected_composite_foreign_keys),
            "actual": sorted(inspected_foreign_keys),
        },
    )
    for name, expected_columns in expected_composite_foreign_keys.items():
        foreign_key = inspected_foreign_keys[name]
        _require(
            tuple(foreign_key["constrained_columns"]) == expected_columns,
            f"{name} constrains the wrong columns",
            foreign_key["constrained_columns"],
        )
        options = foreign_key.get("options") or {}
        _require(options.get("deferrable") is True, f"{name} is not DEFERRABLE", options)
        _require(
            str(options.get("initially") or "").upper() == "DEFERRED",
            f"{name} is not INITIALLY DEFERRED",
            options,
        )

    foreign_installation_id = f"{installation_id}-foreign"
    shared_username = f"p0-shared-user-{suffix}"
    foreign_pricelist_id = f"p0-foreign-pricelist-{suffix}"
    foreign_customer_id = f"p0-foreign-customer-{suffix}"
    same_username_per_installation = False
    pricelist_hidden = False
    cross_installation_fk_rejected = False
    with installation_scope(foreign_installation_id):
        session = session_factory()
        try:
            session.add_all(
                [
                    User(
                        id=f"p0-foreign-user-{suffix}",
                        username=shared_username,
                        password_hash="synthetic-non-authentication-hash",
                    ),
                    Pricelist(
                        id=foreign_pricelist_id,
                        name="Foreign installation pricelist",
                        discount_percentage=Decimal("7.00"),
                    ),
                ]
            )
            session.flush()
            session.add(
                Customer(
                    id=foreign_customer_id,
                    name="Foreign installation customer",
                    email=f"p0-foreign-{suffix}@example.invalid",
                    pricelist_id=foreign_pricelist_id,
                )
            )
            session.commit()
        finally:
            session.close()

    with installation_scope(installation_id):
        session = session_factory()
        try:
            session.add(
                User(
                    id=f"p0-local-user-{suffix}",
                    username=shared_username,
                    password_hash="synthetic-non-authentication-hash",
                )
            )
            session.commit()
            same_username_per_installation = True
            pricelist_hidden = session.get(Pricelist, foreign_pricelist_id) is None
            _require(pricelist_hidden, "foreign pricelist is visible in the local installation")
            updated_foreign_pricelists = (
                session.query(Pricelist)
                .filter(Pricelist.id == foreign_pricelist_id)
                .update({Pricelist.discount_percentage: Decimal("99.00")})
            )
            _require(
                updated_foreign_pricelists == 0,
                "foreign pricelist was mutable from the local installation",
                updated_foreign_pricelists,
            )
            session.add(
                Quote(
                    id=f"p0-cross-installation-quote-{suffix}",
                    customer_id=foreign_customer_id,
                    confirmation_token="a" * 64,
                    confirmation_payload_hash="b" * 64,
                    confirmation_expires_at=(
                        datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
                    ),
                    items=[],
                    subtotal=Decimal("0"),
                    tax_total=Decimal("0"),
                    shipping_total=Decimal("0"),
                    grand_total=Decimal("0"),
                    currency="EUR",
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                cross_installation_fk_rejected = True
            else:
                raise RuntimeError(
                    "P0 PostgreSQL verification failed: PostgreSQL accepted a "
                    "cross-installation foreign key"
                )
        finally:
            session.close()

    with installation_scope(installation_id):
        session = session_factory()
        try:
            session.add_all(
                [
                    Customer(
                        id=customer_id,
                        name="PostgreSQL P0 synthetic customer",
                        email=f"p0-pg-{suffix}@example.invalid",
                    ),
                    Product(
                        id=product_id,
                        external_id=f"p0-pg-external-{suffix}",
                        sku=f"P0-PG-{suffix}",
                        name="PostgreSQL P0 synthetic product",
                        source="local",
                        base_price=Decimal("100.00"),
                        tax_rate=Decimal("0.21"),
                        stock_quantity=5,
                        reserved_stock=0,
                    ),
                ]
            )
            session.commit()
            quote = DeterministicToolsService(session).create_quote(
                customer_id,
                [{"product_id": product_id, "qty": 2}],
                account_id=f"account-{suffix}",
                conversation_id=f"conversation-{suffix}",
                source_message_id=f"message-{suffix}",
            )
        finally:
            session.close()

    quote_id = quote["quote_id"]
    token = quote["confirmation_token"]
    business_key = f"postgres-concurrency:{quote_id}"
    barrier = threading.Barrier(2)

    def confirm(worker_id: int) -> dict[str, object]:
        with installation_scope(installation_id):
            worker_session = session_factory()
            try:
                barrier.wait(timeout=10)
                return DeterministicToolsService(worker_session).confirm_quote_transactional(
                    quote_id,
                    business_key,
                    token,
                    confirmed_by=f"synthetic-worker-{worker_id}",
                )
            finally:
                worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, (1, 2)))

    created_results = [result for result in results if result["created"] is True]
    replay_results = [result for result in results if result["created"] is False]
    order_ids = {str(result["order_id"]) for result in results}
    _require(len(created_results) == 1, "concurrent confirmation created the wrong number of orders", results)
    _require(len(replay_results) == 1, "concurrent confirmation did not return one replay", results)
    _require(len(order_ids) == 1, "concurrent confirmation returned different order IDs", results)

    with installation_scope(installation_id):
        session = session_factory()
        try:
            order_id = order_ids.pop()
            invoice_id = session.scalar(
                select(InvoiceDraft.id).where(InvoiceDraft.order_id == order_id)
            )
            _require(invoice_id is not None, "confirmed order has no invoice draft", order_id)
            counts = {
                "orders": session.scalar(select(func.count()).select_from(Order).where(Order.id == order_id)),
                "reservations": session.scalar(
                    select(func.count()).select_from(StockReservation).where(StockReservation.order_id == order_id)
                ),
                "invoice_drafts": session.scalar(
                    select(func.count()).select_from(InvoiceDraft).where(InvoiceDraft.order_id == order_id)
                ),
                "approvals": session.scalar(
                    select(func.count())
                    .select_from(ApprovalRequest)
                    .where(
                        ApprovalRequest.action_type == "issue_invoice",
                        ApprovalRequest.target_key == invoice_id,
                    )
                ),
                "confirmation_audits": session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.event_type == "quote_confirmed",
                        AuditLog.correlation_id == business_key,
                    )
                ),
            }
            product = session.get(Product, product_id)
            _require(
                counts
                == {
                    "orders": 1,
                    "reservations": 1,
                    "invoice_drafts": 1,
                    "approvals": 1,
                    "confirmation_audits": 1,
                },
                "confirmation effects differ from the exact run-scoped contract",
                counts,
            )
            _require(product is not None, "confirmation product disappeared", product_id)
            _require(product.reserved_stock == 2, "confirmation reserved the wrong stock", product.reserved_stock)
        finally:
            session.close()

    oversell_product_id = f"p0-pg-oversell-product-{suffix}"
    oversell_customer_ids = [f"p0-pg-oversell-customer-{suffix}-{index}" for index in (1, 2)]
    with installation_scope(installation_id):
        session = session_factory()
        try:
            session.add(
                Product(
                    id=oversell_product_id,
                    external_id=f"p0-pg-oversell-external-{suffix}",
                    sku=f"P0-PG-OVERSELL-{suffix}",
                    name="PostgreSQL P0 oversell product",
                    source="local",
                    base_price=Decimal("25.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=3,
                    reserved_stock=0,
                )
            )
            session.add_all(
                [
                    Customer(
                        id=customer,
                        name=f"PostgreSQL P0 oversell customer {index}",
                        email=f"{customer}@example.invalid",
                    )
                    for index, customer in enumerate(oversell_customer_ids, start=1)
                ]
            )
            session.commit()
            oversell_quotes = [
                DeterministicToolsService(session).create_quote(
                    customer,
                    [{"product_id": oversell_product_id, "qty": 2}],
                    source_message_id=f"oversell-message-{suffix}-{index}",
                )
                for index, customer in enumerate(oversell_customer_ids, start=1)
            ]
        finally:
            session.close()

    oversell_barrier = threading.Barrier(2)

    def compete_for_stock(index: int) -> dict[str, object]:
        quote = oversell_quotes[index]
        with installation_scope(installation_id):
            worker_session = session_factory()
            try:
                oversell_barrier.wait(timeout=10)
                result = DeterministicToolsService(worker_session).confirm_quote_transactional(
                    quote["quote_id"],
                    f"postgres-oversell:{quote['quote_id']}",
                    quote["confirmation_token"],
                    confirmed_by=oversell_customer_ids[index],
                )
                return {"outcome": "confirmed", **result}
            except InsufficientStockError:
                return {"outcome": "stock_rejected"}
            finally:
                worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        oversell_results = list(executor.map(compete_for_stock, (0, 1)))
    _require(
        sorted(result["outcome"] for result in oversell_results)
        == ["confirmed", "stock_rejected"],
        "oversell race did not produce exactly one confirmation and one rejection",
        oversell_results,
    )

    with installation_scope(installation_id):
        session = session_factory()
        try:
            oversell_quote_ids = [quote["quote_id"] for quote in oversell_quotes]
            oversell_orders = session.scalar(
                select(func.count()).select_from(Order).where(Order.quote_id.in_(oversell_quote_ids))
            )
            oversell_reservations = session.scalar(
                select(func.count())
                .select_from(StockReservation)
                .where(StockReservation.product_id == oversell_product_id)
            )
            oversell_product = session.get(Product, oversell_product_id)
            _require(oversell_orders == 1, "oversell race created the wrong order count", oversell_orders)
            _require(
                oversell_reservations == 1,
                "oversell race created the wrong reservation count",
                oversell_reservations,
            )
            _require(oversell_product is not None, "oversell product disappeared", oversell_product_id)
            _require(
                oversell_product.reserved_stock == 2,
                "oversell race reserved the wrong stock",
                oversell_product.reserved_stock,
            )
        finally:
            session.close()

    double_release_fixture = _create_reservation_pair(
        session_factory,
        installation_id,
        suffix,
        "double-release",
    )
    release_barrier = threading.Barrier(2)

    def release_same_reservation(_worker_id: int) -> bool:
        with installation_scope(installation_id):
            worker_session = session_factory()
            try:
                release_barrier.wait(timeout=10)
                return DeterministicToolsService(worker_session).release_stock(
                    double_release_fixture["target_reservation_id"]
                )
            finally:
                worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        double_release_results = list(executor.map(release_same_reservation, (1, 2)))
    _require(
        double_release_results == [True, True],
        "idempotent double release returned an unexpected result",
        double_release_results,
    )
    double_release_status = _assert_race_inventory(
        session_factory,
        installation_id,
        double_release_fixture,
        {"released"},
    )

    release_cancel_fixture = _create_reservation_pair(
        session_factory,
        installation_id,
        suffix,
        "release-cancel",
    )
    release_cancel_barrier = threading.Barrier(2)

    def release_or_cancel(action: str) -> bool | int:
        with installation_scope(installation_id):
            worker_session = session_factory()
            try:
                release_cancel_barrier.wait(timeout=10)
                tools = DeterministicToolsService(worker_session)
                if action == "release":
                    return tools.release_stock(release_cancel_fixture["target_reservation_id"])
                return tools.cancel_order_stock(release_cancel_fixture["target_order_id"])
            finally:
                worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        release_cancel_results = list(executor.map(release_or_cancel, ("release", "cancel")))
    _require(
        int(release_cancel_results[0] is True) + int(release_cancel_results[1] == 1) == 1,
        "release/cancel race applied more or fewer than one transition",
        release_cancel_results,
    )
    release_cancel_status = _assert_race_inventory(
        session_factory,
        installation_id,
        release_cancel_fixture,
        {"released", "cancelled"},
    )

    release_expire_fixture = _create_reservation_pair(
        session_factory,
        installation_id,
        suffix,
        "release-expire",
    )
    with installation_scope(installation_id):
        session = session_factory()
        try:
            target = session.get(
                StockReservation,
                release_expire_fixture["target_reservation_id"],
            )
            _require(target is not None, "expiration target reservation disappeared")
            target.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            session.commit()
        finally:
            session.close()
    release_expire_barrier = threading.Barrier(2)

    def release_or_expire(action: str) -> bool | int:
        with installation_scope(installation_id):
            worker_session = session_factory()
            try:
                release_expire_barrier.wait(timeout=10)
                tools = DeterministicToolsService(worker_session)
                if action == "release":
                    return tools.release_stock(release_expire_fixture["target_reservation_id"])
                return tools.expire_stock_reservations()
            finally:
                worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        release_expire_results = list(executor.map(release_or_expire, ("release", "expire")))
    _require(
        int(release_expire_results[0] is True) + int(release_expire_results[1] == 1) == 1,
        "release/expire race applied more or fewer than one transition",
        release_expire_results,
    )
    release_expire_status = _assert_race_inventory(
        session_factory,
        installation_id,
        release_expire_fixture,
        {"released", "expired"},
    )

    return {
        "status": "verified",
        "installation_id": installation_id,
        "concurrent_attempts": len(results),
        "created": len(created_results),
        "idempotent_replays": len(replay_results),
        "effects": counts,
        "oversell": {
            "attempts": len(oversell_results),
            "confirmed": sum(
                result["outcome"] == "confirmed" for result in oversell_results
            ),
            "stock_rejected": sum(
                result["outcome"] == "stock_rejected" for result in oversell_results
            ),
            "orders": oversell_orders,
            "reservations": oversell_reservations,
        },
        "reservation_races": {
            "double_release": double_release_status,
            "release_cancel": release_cancel_status,
            "release_expire": release_expire_status,
        },
        "tenant_isolation": {
            "composite_foreign_keys": len(inspected_foreign_keys),
            "cross_installation_fk_rejected": cross_installation_fk_rejected,
            "pricelist_hidden": pricelist_hidden,
            "same_username_per_installation": same_username_per_installation,
        },
    }


def main() -> None:
    database_url, installation_id, run_id = _validated_ephemeral_context()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _require(
            engine.dialect.name == "postgresql",
            "verify_p0_postgres.py requires a PostgreSQL DATABASE_URL",
            engine.dialect.name,
        )
        with engine.connect() as connection:
            current_database = connection.scalar(text("SELECT current_database()"))
        _require(
            current_database == f"p0_verify_{run_id}",
            "the connected database differs from the guarded URL target",
            current_database,
        )
        try:
            result = _run_verification(engine, installation_id)
        finally:
            _cleanup_verification_data(
                engine,
                (installation_id, f"{installation_id}-foreign"),
            )
        print(json.dumps(result, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
