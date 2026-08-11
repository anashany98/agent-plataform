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
import time
from decimal import Decimal
from typing import Any

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import Customer, Lead, Opportunity, Product, Quote
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


def _seed_crm(engine) -> None:
    """Siembra un lead con su oportunidad (Fase B bloque 5)."""

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with installation_scope(INSTALLATION):
        with factory() as db:
            lead = Lead(
                id="lead-backup",
                email="lead-backup@example.invalid",
                first_name="Lead Backup",
                phone="+34600111222",
                company_name="Backup Corp",
                source="local",
                status="new",
            )
            db.add(lead)
            db.flush()
            db.add(
                Opportunity(
                    id="opp-backup",
                    lead_id=lead.id,
                    external_reference="quote-backup",
                    name="Presupuesto Backup",
                    monetary_value=Decimal("136.00"),
                    currency="EUR",
                    pipeline="default",
                    stage="new",
                    status="open",
                    notes=[{"body": "nota", "created_at": "2026-08-10T00:00:00"}],
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


def test_backup_restore_roundtrip_sqlite(tmp_path) -> None:
    """Roundtrip hermético con ``prepare_restore_target`` + ``restore_to_url``.

    Se usan bases SQLite en archivo porque ``restore_to_url`` exige un
    marker persistente entre llamadas y ``:memory:`` recrea la base por
    conexión.
    """
    source_path = tmp_path / "src.db"
    target_path = tmp_path / "tgt.db"
    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(source)
    _seed(source)

    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    assert manifest["tables"]["customers"]["count"] == 1
    assert manifest["tables"]["products"]["count"] == 1
    assert manifest["tables"]["quotes"]["count"] == 1

    # Restaurar a una base NUEVA con marker explícito y verificar.
    target_url = f"sqlite+pysqlite:///{target_path.as_posix()}"
    backup.prepare_restore_target(target_url)
    target = create_engine(target_url)
    with installation_scope(INSTALLATION):
        backup.restore_to_url(manifest, target_url)
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


def test_backup_integral_includes_crm_tables_roundtrip(tmp_path) -> None:
    """Fase B bloque 5: el backup integral cubre leads y oportunidades.

    Las tablas ``leads``/``opportunities`` entran en el manifiesto porque
    viven en ``Base.metadata``; este eval lo fija como contrato: si mañana
    el backup dejara de incluirlas, el restore perdería el CRM local.
    """
    source_path = tmp_path / "src-crm.db"
    target_path = tmp_path / "tgt-crm.db"
    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(source)
    _seed_crm(source)

    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    assert "leads" in manifest["tables"], (
        "El backup integral debe incluir la tabla de leads"
    )
    assert "opportunities" in manifest["tables"]
    assert manifest["tables"]["leads"]["count"] == 1
    assert manifest["tables"]["opportunities"]["count"] == 1

    # Restore a instalación vacía (base nueva con marker) y verificación.
    target_url = f"sqlite+pysqlite:///{target_path.as_posix()}"
    backup.prepare_restore_target(target_url)
    target = create_engine(target_url)
    with installation_scope(INSTALLATION):
        backup.restore_to_url(manifest, target_url)
        tfactory = sessionmaker(bind=target)
        with tfactory() as db:
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
            restored_lead = (
                db.query(Lead)
                .filter(Lead.email == "lead-backup@example.invalid")
                .one()
            )
            restored_opp = (
                db.query(Opportunity)
                .filter(Opportunity.external_reference == "quote-backup")
                .one()
            )
            assert restored_opp.lead_id == restored_lead.id, (
                "La FK lead→oportunidad debe sobrevivir al restore"
            )
            assert restored_opp.notes and restored_opp.notes[0]["body"] == "nota"
    assert verification["ok"] is True, f"discrepancias: {verification['mismatches']}"

    source.dispose()
    target.dispose()


def test_rollback_installation_restores_crm_rows() -> None:
    """Fase B bloque 5: el rollback de datos recupera leads y oportunidades."""

    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _seed_crm(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

        # Simula una mala release: se pierde el CRM local.
        with factory() as db:
            db.query(Opportunity).filter(
                Opportunity.installation_id == INSTALLATION
            ).delete()
            db.query(Lead).filter(Lead.installation_id == INSTALLATION).delete()
            db.commit()
            assert db.query(Lead).count() == 0

        backup.rollback_installation(engine, manifest, installation_id=INSTALLATION)

        with factory() as db:
            assert (
                db.query(Lead).filter(Lead.installation_id == INSTALLATION).count()
                == 1
            ), "El rollback debe recuperar el lead"
            assert (
                db.query(Opportunity)
                .filter(Opportunity.installation_id == INSTALLATION)
                .count()
                == 1
            ), "El rollback debe recuperar la oportunidad"
    engine.dispose()


def test_restore_rto_is_measured_and_bounded(tmp_path) -> None:
    """Fase B bloque 5: mide el RTO del restore y lo acota.

    Metodología RPO/RTO:

    - **RPO** = cadencia programada de backups (parámetro operacional, p.
      ej. cron diario → RPO ≤ 24 h). El RPO no lo fija el código sino el
      scheduler que invoca ``scripts/backup-restore-integral.sh``.
    - **RTO** = tiempo transcurrido del restore hasta datos consultables.
      Este eval lo mide sobre un corpus representativo y exige un límite
      generoso para detectar regresiones patológicas (p. ej. inserciones
      N+1 que degradarían el RTO con catálogos grandes).
    """
    source_path = tmp_path / "src-rto.db"
    target_path = tmp_path / "tgt-rto.db"
    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(source)
    _seed(source)
    _seed_crm(source)

    factory = sessionmaker(bind=source)
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    target_url = f"sqlite+pysqlite:///{target_path.as_posix()}"
    backup.prepare_restore_target(target_url)
    started = time.perf_counter()
    with installation_scope(INSTALLATION):
        backup.restore_to_url(manifest, target_url)
    elapsed = time.perf_counter() - started

    total_rows = sum(entry["count"] for entry in manifest["tables"].values())
    assert elapsed < 10.0, (
        f"RTO del restore excesivo: {elapsed:.2f}s para {total_rows} filas"
    )
    print(
        f"[RTO] restore SQLite: {elapsed:.3f}s para {total_rows} filas "
        f"({manifest['tables']['leads']['count']} leads, "
        f"{manifest['tables']['opportunities']['count']} oportunidades)"
    )

    target = create_engine(target_url)
    with installation_scope(INSTALLATION):
        tfactory = sessionmaker(bind=target)
        with tfactory() as db:
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
    assert verification["ok"] is True
    source.dispose()
    target.dispose()


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
        backup.prepare_restore_target(tgt_url)
        backup.restore_to_url(manifest, tgt_url)
        tfactory = sessionmaker(bind=target)
        with tfactory() as db:
            verification = backup.verify_backup(db, manifest, installation_id=INSTALLATION)
    assert verification["ok"] is True, f"discrepancias: {verification['mismatches']}"
    source.dispose()
    target.dispose()


def test_restore_to_url_refuses_base_without_marker() -> None:
    """restore_to_url aborta si la base NO fue preparada con marker."""

    target = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    target_url = target.url.render_as_string(hide_password=False)

    # Sin prepare_restore_target: la base está vacía pero NO tiene marker.
    factory = sessionmaker(bind=source_for_marker_test())
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    with pytest.raises(backup.RestoreSafetyError):
        backup.restore_to_url(manifest, target_url)
    target.dispose()


def test_restore_to_url_refuses_base_with_app_tables() -> None:
    """restore_to_url aborta si la base destino ya tiene tablas de aplicación.

    Esto evita destruir datos reales si alguien apunta por error a una URL
    ocupada.
    """

    occupied = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(occupied)  # ya tiene tablas de aplicación

    factory = sessionmaker(bind=source_for_marker_test())
    with installation_scope(INSTALLATION):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    with pytest.raises(backup.RestoreSafetyError):
        backup.restore_to_url(
            manifest, occupied.url.render_as_string(hide_password=False)
        )
    occupied.dispose()


def test_restore_to_url_preserves_populated_target() -> None:
    """Una base con datos del cliente NO debe ser tocada aunque su URL sea
    apuntada por error. El test prepara un cliente en una base ocupada y
    verifica que el contenido sigue intacto tras un restore mal apuntado."""

    occupied = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(occupied)
    factory = sessionmaker(bind=occupied)
    with installation_scope(INSTALLATION):
        with factory() as db:
            db.add(Customer(id="cust-survive", name="Cliente Real", email="real@example.invalid"))
            db.commit()
            before = db.query(Customer).count()
        assert before == 1

    src_factory = sessionmaker(bind=source_for_marker_test())
    with installation_scope(INSTALLATION):
        with src_factory() as db:
            manifest = backup.create_backup(db, installation_id=INSTALLATION)

    with pytest.raises(backup.RestoreSafetyError):
        backup.restore_to_url(
            manifest, occupied.url.render_as_string(hide_password=False)
        )

    with installation_scope(INSTALLATION):
        with factory() as db:
            after = db.query(Customer).count()
            surviving = db.query(Customer).filter(Customer.id == "cust-survive").first()
    assert after == 1, "El restore mal apuntado no debe haber tocado la base"
    assert surviving is not None and surviving.name == "Cliente Real"
    occupied.dispose()


def source_for_marker_test() -> Any:  # helper local
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    _seed(engine)
    return engine
