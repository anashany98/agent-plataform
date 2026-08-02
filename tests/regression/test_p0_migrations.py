import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.database import Base
from app.models import models  # noqa: F401


def _load_initial_migration():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "bridge-api"
        / "alembic"
        / "versions"
        / "0001_initial_schema.py"
    )
    spec = importlib.util.spec_from_file_location("p0_initial_schema", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p0_initial_downgrade_preserves_existing_schema(monkeypatch):
    migration = _load_initial_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
        tables_before = set(inspect(connection).get_table_names())
        assert {"products", "orders", "invoice_drafts"}.issubset(tables_before)
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        migration.downgrade()

        tables_after = set(inspect(connection).get_table_names())
        assert tables_before.issubset(tables_after), (
            "El downgrade inicial no puede eliminar tablas existentes; "
            f"eliminadas: {sorted(tables_before - tables_after)}"
        )
