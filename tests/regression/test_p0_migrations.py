import ast
import datetime
import hashlib
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.config import settings
from app.database import Base
from app.models import models  # noqa: F401
from sqlalchemy import (
    CheckConstraint,
    Engine,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_API_DIR = PROJECT_ROOT / "bridge-api"
ALEMBIC_DIR = BRIDGE_API_DIR / "alembic"
INITIAL_MIGRATION = ALEMBIC_DIR / "versions" / "0001_initial_schema.py"
TENANT_UPGRADE_MIGRATION = ALEMBIC_DIR / "versions" / "0002_tenant_safe_schema.py"
MIGRATION_INSTALLATION_ID = "migration-test-installation"


def _alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", ALEMBIC_DIR.as_posix())
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def sqlite_migration_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "migration-lifecycle.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    monkeypatch.setenv("INSTALLATION_ID", MIGRATION_INSTALLATION_ID)

    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    sa.event.listen(Engine, "connect", enable_sqlite_foreign_keys)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        yield _alembic_config(database_url), engine
    finally:
        engine.dispose()
        sa.event.remove(Engine, "connect", enable_sqlite_foreign_keys)


def _assert_schema_matches_models(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(Base.metadata.tables)
    assert actual_tables == expected_tables

    for table_name in expected_tables:
        actual_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        expected_columns = Base.metadata.tables[table_name].columns
        assert set(actual_columns) == set(expected_columns.keys()), table_name
        for column_name, expected_column in expected_columns.items():
            assert bool(actual_columns[column_name]["nullable"]) == bool(
                expected_column.nullable
            ), f"{table_name}.{column_name}"

        expected_indexes = {
            index.name: bool(index.unique)
            for index in Base.metadata.tables[table_name].indexes
            if index.name is not None
        }
        actual_indexes = {
            index["name"]: bool(index["unique"])
            for index in inspector.get_indexes(table_name)
        }
        assert expected_indexes == actual_indexes, table_name

        actual_primary_key = tuple(inspector.get_pk_constraint(table_name)["constrained_columns"])
        expected_primary_key = tuple(column.name for column in Base.metadata.tables[table_name].primary_key)
        assert actual_primary_key == expected_primary_key, table_name

        expected_unique_constraints = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_unique_constraints = {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(table_name)
        }
        assert expected_unique_constraints == actual_unique_constraints, table_name

        expected_check_constraints = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_check_constraints = {
            constraint["name"] for constraint in inspector.get_check_constraints(table_name)
        }
        assert expected_check_constraints == actual_check_constraints, table_name

        expected_foreign_keys = {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                tuple(element.column.table.name for element in constraint.elements),
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete,
                bool(constraint.deferrable),
                constraint.initially,
            )
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        actual_foreign_keys = set()
        for foreign_key in inspector.get_foreign_keys(table_name):
            options = foreign_key.get("options") or {}
            actual_foreign_keys.add(
                (
                    foreign_key["name"],
                    tuple(foreign_key["constrained_columns"]),
                    tuple(
                        foreign_key["referred_table"]
                        for _column in foreign_key["referred_columns"]
                    ),
                    tuple(foreign_key["referred_columns"]),
                    options.get("ondelete"),
                    bool(options.get("deferrable")),
                    options.get("initially"),
                )
            )
        assert expected_foreign_keys == actual_foreign_keys, table_name


def _operations(connection) -> Operations:
    return Operations(MigrationContext.configure(connection))


def _assert_upgrade_did_not_mutate_0001(engine: Engine) -> None:
    assert _current_revision(engine) == "0001"
    assert "installation_id" not in {
        column["name"] for column in inspect(engine).get_columns("products")
    }
    assert "confirmation_payload_hash" not in {
        column["name"] for column in inspect(engine).get_columns("quotes")
    }
    assert "installation_id" not in {
        column["name"] for column in inspect(engine).get_columns("pricelists")
    }


def _insert_fixture(engine: Engine) -> None:
    created_at = datetime.datetime(2026, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO pricelists (id, name, discount_percentage, installation_id) "
                "VALUES ('fixture-pricelist', 'Fixture', 7.5000, :installation_id)"
            ),
            {"installation_id": MIGRATION_INSTALLATION_ID},
        )
        connection.execute(
            text(
                "INSERT INTO customers "
                "(id, name, email, pricelist_id, tax_exempt, created_at, installation_id) VALUES "
                "('fixture-customer', 'Fixture Customer', 'fixture@example.test', "
                "'fixture-pricelist', 0, :created_at, :installation_id)"
            ),
            {
                "created_at": created_at,
                "installation_id": MIGRATION_INSTALLATION_ID,
            },
        )
        connection.execute(
            text(
                "INSERT INTO products "
                "(id, sku, name, source, base_price, tax_rate, stock_quantity, reserved_stock, "
                "created_at, updated_at, installation_id) VALUES "
                "('fixture-product', 'FIXTURE-SKU', 'Fixture Product', 'local', 10, 0.21, "
                "5, 0, :created_at, :created_at, :installation_id)"
            ),
            {
                "created_at": created_at,
                "installation_id": MIGRATION_INSTALLATION_ID,
            },
        )


def _insert_historical_fixture(
    engine: Engine,
    *,
    reservation_status: str = "released",
) -> None:
    created_at = datetime.datetime(2026, 1, 2, 3, 4, 5)
    items = json.dumps([{"product_id": "legacy-product", "quantity": 1}])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO pricelists (id, name, discount_percentage) "
                "VALUES ('legacy-pricelist', 'Legacy', 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO customers "
                "(id, name, email, pricelist_id, tax_exempt, created_at) VALUES "
                "('legacy-customer', 'Legacy Customer', 'legacy@example.test', "
                "'legacy-pricelist', 0, :created_at)"
            ),
            {"created_at": created_at},
        )
        connection.execute(
            text(
                "INSERT INTO products "
                "(id, sku, name, source, base_price, tax_rate, stock_quantity, reserved_stock, "
                "created_at, updated_at) VALUES "
                "('legacy-product', 'LEGACY-SKU', 'Legacy Product', 'local', 10, 0.21, 5, 1, "
                ":created_at, :created_at)"
            ),
            {"created_at": created_at},
        )
        connection.execute(
            text(
                "INSERT INTO quotes "
                "(id, customer_id, confirmation_token, items, subtotal, tax_total, shipping_total, "
                "grand_total, currency, status, created_at) VALUES "
                "('legacy-quote', 'legacy-customer', 'LEGACY-TOKEN', :items, 10, 2.10, 0, "
                "12.10, 'EUR', 'draft', :created_at)"
            ),
            {"created_at": created_at, "items": items},
        )
        connection.execute(
            text(
                "INSERT INTO orders "
                "(id, customer_id, quote_id, idempotency_key, items, subtotal, tax_total, "
                "shipping_total, grand_total, currency, status, created_at) VALUES "
                "('legacy-order', 'legacy-customer', 'legacy-quote', 'legacy-order-key', :items, "
                "10, 2.10, 0, 12.10, 'EUR', 'confirmed', :created_at)"
            ),
            {"created_at": created_at, "items": items},
        )
        connection.execute(
            text(
                "INSERT INTO stock_reservations "
                "(id, order_id, product_id, quantity_reserved, status, created_at) VALUES "
                "('legacy-reservation', 'legacy-order', 'legacy-product', 1, :status, :created_at)"
            ),
            {"created_at": created_at, "status": reservation_status},
        )


def _insert_historical_users(engine: Engine, installation_ids: list[str | None]) -> None:
    created_at = datetime.datetime(2026, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        for index, installation_id in enumerate(installation_ids):
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, password_hash, role, installation_id, is_active, "
                    "must_change_password, token_version, created_at) VALUES "
                    "(:id, :username, 'hash', 'admin', :installation_id, 1, 0, 0, :created_at)"
                ),
                {
                    "id": f"historical-user-{index}",
                    "username": f"historical-user-{index}",
                    "installation_id": installation_id,
                    "created_at": created_at,
                },
            )


def _assert_fixture_survives(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT name, installation_id FROM pricelists "
                "WHERE id = 'fixture-pricelist'"
            )
        ).one() == ("Fixture", MIGRATION_INSTALLATION_ID)
        customer = connection.execute(
            text(
                "SELECT name, installation_id, pricelist_id FROM customers "
                "WHERE id = 'fixture-customer'"
            )
        ).one()
        assert customer == (
            "Fixture Customer",
            MIGRATION_INSTALLATION_ID,
            "fixture-pricelist",
        )
        product = connection.execute(
            text(
                "SELECT name, installation_id FROM products "
                "WHERE id = 'fixture-product'"
            )
        ).one()
        assert product == ("Fixture Product", MIGRATION_INSTALLATION_ID)


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def test_initial_revision_uses_explicit_alembic_operations() -> None:
    source = INITIAL_MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "create_all" not in called_attributes
    assert "drop_all" not in called_attributes
    assert "app.database" not in source
    assert "app.models" not in source
    assert "op.create_table" in source


def test_tenant_upgrade_is_explicit_and_does_not_import_models() -> None:
    source = TENANT_UPGRADE_MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "create_all" not in called_attributes
    assert "drop_all" not in called_attributes
    assert "app.database" not in source
    assert "app.models" not in source


def test_clean_install_upgrades_to_explicit_model_schema(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context

    command.upgrade(config, "head")

    _assert_schema_matches_models(engine)
    assert _current_revision(engine) == "0004"


def test_historical_0001_upgrade_backfills_tenant_and_lifecycle_data(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_fixture(engine)

    command.upgrade(config, "head")

    _assert_schema_matches_models(engine)
    with engine.connect() as connection:
        product = connection.execute(
            text("SELECT name, installation_id FROM products WHERE id = 'legacy-product'")
        ).one()
        assert product == ("Legacy Product", MIGRATION_INSTALLATION_ID)

        pricelist = connection.execute(
            text(
                "SELECT name, installation_id FROM pricelists "
                "WHERE id = 'legacy-pricelist'"
            )
        ).one()
        assert pricelist == ("Legacy", MIGRATION_INSTALLATION_ID)

        quote = connection.execute(
            text(
                "SELECT confirmation_token, confirmation_payload_hash, confirmation_expires_at, "
                "confirmation_consumed_at FROM quotes WHERE id = 'legacy-quote'"
            )
        ).one()
        assert quote.confirmation_token == hashlib.sha256(b"LEGACY-TOKEN").hexdigest()
        assert len(quote.confirmation_payload_hash) == 64
        assert quote.confirmation_expires_at is not None
        assert quote.confirmation_consumed_at is None

        reservation = connection.execute(
            text(
                "SELECT installation_id, expires_at, released_at FROM stock_reservations "
                "WHERE id = 'legacy-reservation'"
            )
        ).one()
        assert reservation.installation_id == MIGRATION_INSTALLATION_ID
        assert reservation.expires_at is not None
        assert reservation.released_at is not None
    assert _current_revision(engine) == "0004"


def test_historical_upgrade_fails_closed_without_installation_id(
    sqlite_migration_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_fixture(engine)
    monkeypatch.delenv("INSTALLATION_ID", raising=False)

    with pytest.raises(RuntimeError, match="INSTALLATION_ID"):
        command.upgrade(config, "head")

    assert _current_revision(engine) == "0001"
    assert "installation_id" not in {
        column["name"] for column in inspect(engine).get_columns("products")
    }


def test_historical_upgrade_rejects_orphan_scalar_relationship_before_ddl(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_fixture(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        connection.execute(
            text(
                "UPDATE customers SET pricelist_id = 'missing-pricelist' "
                "WHERE id = 'legacy-customer'"
            )
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    with pytest.raises(RuntimeError, match="customers.*pricelist"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_final_composite_fk_rejects_cross_installation_pricelist(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "head")
    _insert_fixture(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO customers "
                    "(id, name, email, pricelist_id, tax_exempt, created_at, installation_id) "
                    "VALUES ('cross-customer', 'Cross Tenant', 'cross@example.test', "
                    "'fixture-pricelist', 0, :created_at, 'another-installation')"
                ),
                {"created_at": datetime.datetime(2026, 1, 2, 3, 4, 5)},
            )


def test_usernames_are_unique_per_installation_not_globally(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "head")
    created_at = datetime.datetime(2026, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        for user_id, installation_id in (
            ("user-a", MIGRATION_INSTALLATION_ID),
            ("user-b", "another-installation"),
        ):
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, password_hash, role, installation_id, is_active, "
                    "must_change_password, token_version, created_at) VALUES "
                    "(:id, 'shared-username', 'hash', 'admin', :installation_id, 1, 0, 0, "
                    ":created_at)"
                ),
                {
                    "id": user_id,
                    "installation_id": installation_id,
                    "created_at": created_at,
                },
            )


@pytest.mark.parametrize(
    "installation_ids",
    [
        ["migration-test-installatio"],
        [""],
        [MIGRATION_INSTALLATION_ID, "another-installation"],
    ],
)
def test_historical_upgrade_rejects_invalid_user_installation_set_before_mutation(
    sqlite_migration_context,
    installation_ids: list[str],
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_users(engine, installation_ids)

    with pytest.raises(RuntimeError, match="users.*INSTALLATION_ID"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_historical_upgrade_rejects_null_user_installation_before_mutation(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        with _operations(connection).batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "installation_id",
                existing_type=sa.String(),
                nullable=True,
            )
    _insert_historical_users(engine, [None])

    with pytest.raises(RuntimeError, match="users.*INSTALLATION_ID"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_historical_upgrade_rejects_unmanaged_active_reservation_before_mutation(
    sqlite_migration_context,
) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_fixture(engine, reservation_status="active")

    with pytest.raises(RuntimeError, match="reservas activas.*reconciliación"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_missing_required_column(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        with _operations(connection).batch_alter_table("products") as batch_op:
            batch_op.drop_column("source_url")

    with pytest.raises(RuntimeError, match="products.*source_url"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_wrong_critical_column_type(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        with _operations(connection).batch_alter_table("products") as batch_op:
            batch_op.alter_column(
                "base_price",
                existing_type=sa.Numeric(14, 4),
                type_=sa.String(),
            )

    with pytest.raises(RuntimeError, match=r"products\.base_price.*tipo"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_wrong_foreign_key(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    naming_convention = {
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    }
    with engine.begin() as connection:
        with _operations(connection).batch_alter_table(
            "orders",
            naming_convention=naming_convention,
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_orders_quote_id_quotes",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_orders_quote_id_products",
                "products",
                ["quote_id"],
                ["id"],
            )

    with pytest.raises(RuntimeError, match="orders.*foreign key"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_wrong_named_check_expression(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        with _operations(connection).batch_alter_table("products") as batch_op:
            batch_op.drop_constraint(
                "ck_product_stock_nonnegative",
                type_="check",
            )
            batch_op.create_check_constraint(
                "ck_product_stock_nonnegative",
                "stock_quantity >= -999",
            )

    with pytest.raises(RuntimeError, match="ck_product_stock_nonnegative"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_named_index_with_wrong_columns(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        operations = _operations(connection)
        operations.drop_index("ix_products_sku", table_name="products")
        operations.create_index(
            "ix_products_sku",
            "products",
            ["name"],
            unique=False,
        )

    with pytest.raises(RuntimeError, match="ix_products_sku"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_preflight_rejects_named_index_with_wrong_uniqueness(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    with engine.begin() as connection:
        operations = _operations(connection)
        operations.drop_index("ix_products_category", table_name="products")
        operations.create_index(
            "ix_products_category",
            "products",
            ["category"],
            unique=True,
        )

    with pytest.raises(RuntimeError, match="ix_products_category"):
        command.upgrade(config, "head")

    _assert_upgrade_did_not_mutate_0001(engine)


def test_initial_downgrade_preserves_existing_schema_and_fixture(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "head")
    _insert_fixture(engine)

    command.downgrade(config, "base")

    _assert_schema_matches_models(engine)
    _assert_fixture_survives(engine)
    assert _current_revision(engine) is None


def test_0002_downgrade_preserves_safety_schema_and_fixture(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "head")
    _insert_fixture(engine)

    command.downgrade(config, "0001")

    _assert_schema_matches_models(engine)
    _assert_fixture_survives(engine)
    assert _current_revision(engine) == "0001"


def test_reupgrade_after_safe_downgrade_keeps_fixture(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "head")
    _insert_fixture(engine)
    command.downgrade(config, "base")

    command.upgrade(config, "head")

    _assert_schema_matches_models(engine)
    _assert_fixture_survives(engine)
    assert _current_revision(engine) == "0004"


def test_reupgrade_allows_managed_active_reservation(sqlite_migration_context) -> None:
    config, engine = sqlite_migration_context
    command.upgrade(config, "0001")
    _insert_historical_fixture(engine, reservation_status="released")
    command.upgrade(config, "head")
    managed_expiration = datetime.datetime(2035, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stock_reservations SET status = 'active', expires_at = :expires_at, "
                "released_at = NULL WHERE id = 'legacy-reservation'"
            ),
            {"expires_at": managed_expiration},
        )
    command.downgrade(config, "base")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        reservation = connection.execute(
            text(
                "SELECT status, expires_at, installation_id FROM stock_reservations "
                "WHERE id = 'legacy-reservation'"
            )
        ).one()
        assert reservation.status == "active"
        assert reservation.expires_at is not None
        assert reservation.installation_id == MIGRATION_INSTALLATION_ID
    assert _current_revision(engine) == "0004"
