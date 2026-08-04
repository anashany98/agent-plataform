"""Evals D-015/D-016: backup/restore verificable y rollback de esquema+datos.

Un backup solo vale si se restaura. Estos evals hacen el ciclo completo:

- Sembrar datos reales del modelo (clientes, productos, presupuestos, docs).
- ``create_backup`` con manifiesto (conteos + sha256 por tabla).
- Restaurar a un motor **vacío** y verificar conteos y checksums.
- Corrupción simulada: si la base destino difiere, ``verify_backup`` lo reporta.

El caso SQLite es hermético y siempre corre. El caso PostgreSQL es opt-in
(``RUN_POSTGRES_BACKUP=1`` + ``BACKUP_TEST_PG_URL``) para producir evidencia
real sobre el motor de producción sin romper el harness.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import Customer, Product, Quote
from app.services import backup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION = "backup-instalacion"


def _seed(engine) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with installation_scope(INSTALLATION):
        with factory() as db:
            db.add(Customer(id="cust-b", name="Cliente Backup", email="backup@example.invalid"))
            db.add(
                Product(
                    id="prod-b",
                    external_id="prod-b",
                    sku="SKU-BACKUP-001",
                    name="Producto Backup",
                    description="Fixture de backup.",
                    category="Industrial",
                    attributes={},
                    source="local",
                    base_price=Decimal("77.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=5,
                    reserved_stock=0,
                )
            )
            db.add(
                Quote(
                    id="quote-b",
                    customer_id="cust-b",
                    confirmation_token="tok-b",
                    confirmation_payload_hash="hash-b",
                    confirmation_expires_at=__import__("datetime").datetime.now(
                        __import__("datetime").UTC
                    ).replace(tzinfo=None),
                    items=[{"sku": "SKU-BACKUP-001", "quantity": 1}],
                    subtotal=Decimal("77.00"),
                    tax_total=Decimal("16.17"),
                    shipping_total=Decimal("0.00"),
                    grand_total=Decimal("93.17"),
                    currency="EUR",
                    status="draft",
                )
            )
            db.commit()


def _counts(engine) -> dict:
    factory = sessionmaker(bind=engine)
    with factory() as db:
        return {
            "customers": db.query(Customer).count(),
            "products": db.query(Product).count(),
            "quotes": db.query(Quote).count(),
        }


def test_backup_restore_roundtrip_sqlite() -> None:
    source = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(source)
    _seed(source)

    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    assert manifest["tables"]["customers"]["count"] == 1
    assert manifest["tables"]["products"]["count"] == 1
    assert manifest["tables"]["quotes"]["count"] == 1

    # Restaurar a un motor vacío y verificar.
    target = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with installation_scope(INSTALLATION):
        backup.restore_backup(target, manifest)
        assert _counts(target) == {"customers": 1, "products": 1, "quotes": 1}

        tfactory = sessionmaker(bind=target)
        with tfactory() as db:
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
    assert verification["ok"] is True, f"discrepancias: {verification['mismatches']}"

    source.dispose()
    target.dispose()


def test_verify_detects_corruption() -> None:
    source = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(source)
    _seed(source)
    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)
            # Corrompe: añade un cliente extra no respaldado.
            db.add(Customer(id="cust-extra", name="Extra", email="extra@example.invalid"))
            db.commit()
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
    assert verification["ok"] is False, "Debe detectar que la base difiere del backup"
    assert any(m["table"] == "customers" for m in verification["mismatches"])
    source.dispose()


def test_rollback_installation_restores_known_state() -> None:
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _seed(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

        # Simula una "mala release": borra quotes y muta el cliente.
        with factory() as db:
            db.query(Quote).filter(Quote.installation_id == INSTALLATION).delete()
            cust = db.query(Customer).filter(Customer.id == "cust-b").one()
            cust.name = "Cliente Corrupto"
            db.commit()

        backup.rollback_installation(engine, manifest, installation_id=INSTALLATION)

        with factory() as db:
            assert db.query(Quote).filter(Quote.installation_id == INSTALLATION).count() == 1, (
                "El rollback debe recuperar el presupuesto borrado"
            )
            cust = db.query(Customer).filter(Customer.id == "cust-b").one()
            assert cust.name == "Cliente Backup", "El rollback debe revertir la mutación"
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
        assert verification["ok"] is True
    engine.dispose()


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_BACKUP") != "1",
    reason="Evidencia PostgreSQL opt-in (RUN_POSTGRES_BACKUP=1)",
)
def test_backup_restore_roundtrip_postgres() -> None:
    admin_url = os.getenv(
        "BACKUP_TEST_PG_ADMIN_URL", "postgresql://bridge_user:bridge_pass@localhost:5439/postgres"
    )
    src_url = os.getenv("BACKUP_TEST_PG_URL", "postgresql://bridge_user:bridge_pass@localhost:5439/backup_source")
    tgt_url = src_url.replace("/backup_source", "/backup_target")

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        for db_name in ("backup_source", "backup_target"):
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS {db_name} WITH (FORCE)')
            conn.exec_driver_sql(f"CREATE DATABASE {db_name}")
        for db_name in ("backup_source", "backup_target"):
            conn.exec_driver_sql(f"GRANT ALL ON DATABASE {db_name} TO bridge_user")
    admin.dispose()

    source = create_engine(src_url)
    target = create_engine(tgt_url)
    for eng in (source, target):
        with eng.connect() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()

    Base.metadata.create_all(source)
    _seed(source)
    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)
        backup.restore_backup(target, manifest)
        tfactory = sessionmaker(bind=target)
        with tfactory() as db:
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
    assert verification["ok"] is True, f"discrepancias: {verification['mismatches']}"
    source.dispose()
    target.dispose()
