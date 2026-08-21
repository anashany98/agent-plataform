"""Backup/restore verificable por instalación (D-015) y soporte de rollback (D-016).

El objetivo es que la recuperación sea **demostrable**: un backup no vale si
no se restaura. Este servicio:

- ``create_backup``: vuelca todas las tablas del modelo (filtradas por
  ``installation_id`` cuando la columna existe) a un manifiesto portable con
  conteos y ``sha256`` por tabla. No toca la red ni Docker; opera sobre el
  motor SQLAlchemy que se le pase (SQLite o PostgreSQL).
- ``restore_backup``: recrea el esquema en un motor **vacío** y reinserta los
  datos del manifiesto.
- ``verify_backup``: compara conteos y ``sha256`` del manifiesto contra una
  base restaurada, devolviendo el detalle de cualquier discrepancia.

Los valores se serializan de forma reversible (``datetime`` a ISO, ``Decimal``
a str, JSON tal cual) usando el tipo de columna para reconstruirlos al
restaurar. ``AuditLog`` se incluye: el backup debe preservar también el
registro de cumplimiento.

Esto complementa a ``scripts/backup-restore-integral.sh`` (que cubre
pg_dump/volúmenes/config/cifrado a nivel de contenedor): aquí se verifica la
restauración a nivel de modelo de datos, de forma hermética y reproducible.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database import Base
from sqlalchemy import DateTime, Numeric, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker


def _alembic_schema_version() -> str:
    bridge_root = Path(__file__).resolve().parents[2]
    config = Config(str(bridge_root / "alembic.ini"))
    config.set_main_option("script_location", str(bridge_root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"El grafo Alembic debe tener un único head; encontrados: {heads}")
    return str(heads[0])


SCHEMA_VERSION = _alembic_schema_version()
SCHEMA_VERSION_KEY = "schema_version"

# Tabla efímera usada como marker de "destino preparado para restore".
# Sólo se crea en bases explícitamente preparadas por ``prepare_restore_target``
# y sirve para que ``restore_to_url`` distinga un motor recién inicializado de
# una base con datos reales (que jamás debe ser sobrescrita).
RESTORE_MARKER_TABLE = "_bridge_restore_marker"
RESTORE_MARKER_ROW = {"id": 1, "marker": "prepared"}


class RestoreSafetyError(RuntimeError):
    """El destino del restore no es seguro para sobrescritura."""


def prepare_restore_target(database_url: str, *, schema_version: str | None = None) -> dict[str, Any]:
    """Prepara una base NUEVA con un marker efímero para ``restore_to_url``.

    Crea el esquema vacío (sin tablas de aplicación) y deja únicamente la
    tabla ``_bridge_restore_marker`` con un único registro. Esta función es
    la única vía autorizada para autorizar un destino de restore: cualquier
    base que no contenga el marker es considerada ocupada y rechazada por
    ``restore_to_url``.

    Se delega la creación de esquema a ``Base.metadata.create_all`` sobre una
    transacción que luego descarta todas las tablas de modelo. El motor se
    desecha tras crear el marker para evitar usos cruzados.
    """

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        app_tables = {t.name for t in Base.metadata.sorted_tables}
        # Si la base tiene tablas de modelo, no la preparamos: no podemos
        # distinguir entre "vacía porque se inicializó ahora" y "vacía
        # porque alguien acaba de dropear todo accidentalmente". El caller
        # debe apuntar a una base recién creada (CREATE DATABASE) sin más
        # objetos.
        if app_tables & existing:
            raise RestoreSafetyError(
                "El destino contiene tablas de aplicación. Crea una base nueva "
                "(CREATE DATABASE) y vuelve a llamar a prepare_restore_target."
            )
        if RESTORE_MARKER_TABLE in existing:
            raise RestoreSafetyError(
                "El destino ya tiene un marker de restore previo. "
                "Usa una base recién creada o ejecuta undo_restore_target antes."
            )
        # Crea el esquema de aplicación, añade el marker y borra las tablas
        # de modelo dejando únicamente el marker.
        Base.metadata.create_all(engine)
        # Usamos SQLAlchemy core portable para crear el marker (evita
        # peculiaridades de dialecto en tipos como ``TIMESTAMP``).
        marker_table = sa.Table(
            RESTORE_MARKER_TABLE,
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("marker", sa.String(64), nullable=False),
            sa.Column("schema_version", sa.String(32), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        marker_table.create(engine, checkfirst=True)
        with engine.begin() as conn:
            conn.execute(
                marker_table.insert().values(
                    id=RESTORE_MARKER_ROW["id"],
                    marker=RESTORE_MARKER_ROW["marker"],
                    schema_version=schema_version or SCHEMA_VERSION,
                    created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                )
            )
            # Borrado explícito de las tablas de modelo (que create_all
            # acaba de crear) para dejar el destino con sólo el marker.
            # ``CASCADE`` es PostgreSQL; en SQLite se omite para no romper
            # el dialecto hermético.
            dialect_name = getattr(engine.dialect, "name", "")
            for table in sorted(app_tables, reverse=True):
                if dialect_name == "postgresql":
                    conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                else:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    finally:
        engine.dispose()
    return {"prepared": True, "schema_version": schema_version or SCHEMA_VERSION}


def undo_restore_target(database_url: str) -> dict[str, Any]:
    """Elimina el marker de restore. Útil para preparar el destino de tests."""

    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {RESTORE_MARKER_TABLE}"))
    finally:
        engine.dispose()
    return {"undone": True}


def _assert_restore_marker(engine: Any) -> None:
    """Verifica que la base destino contiene el marker autorizado.

    Lanza ``RestoreSafetyError`` si el marker no existe o es incorrecto, o si
    la base tiene tablas de modelo que no han sido borradas por
    ``restore_backup``. Esta función es la ÚNICA barrera que evita que un
    URL incorrecto apunte a una base con datos y los destruya.
    """

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    if RESTORE_MARKER_TABLE not in existing:
        raise RestoreSafetyError(
            "La base destino NO contiene un marker de restore. "
            "Ejecuta prepare_restore_target(database_url) en una base recién "
            "creada antes de restaurar."
        )
    app_tables = {t.name for t in Base.metadata.sorted_tables}
    overlap = app_tables & existing
    if overlap:
        raise RestoreSafetyError(
            f"La base destino tiene tablas de aplicación antes de restaurar: "
            f"{sorted(overlap)}. Esto indica una base ocupada; se aborta el "
            "restore para evitar destruir datos."
        )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _deserialize_value(value: Any, column: Any) -> Any:
    if value is None:
        return None
    ctype = column.type
    if isinstance(ctype, DateTime):
        return datetime.datetime.fromisoformat(value)
    if isinstance(ctype, Numeric):
        return Decimal(value)
    return value


def _canonical(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _table_rows(db: Session, model: Any, installation_id: str | None) -> list[Any]:
    query = db.query(model)
    if installation_id is not None and hasattr(model, "installation_id"):
        query = query.filter(model.installation_id == installation_id)
    return query.order_by(*model.__table__.primary_key.columns).all()


def create_backup(db: Session, *, installation_id: str | None = None) -> dict[str, Any]:
    """Vuelca todas las tablas a un manifiesto con conteos y sha256."""

    tables: dict[str, Any] = {}
    for name, _model in sorted(Base.metadata.tables.items()):
        cls = _model_for_table(name)
        if cls is None:
            continue
        rows = _table_rows(db, cls, installation_id)
        serialized = [
            {col.key: _serialize_value(getattr(row, col.key)) for col in cls.__table__.columns}
            for row in rows
        ]
        tables[name] = {
            "count": len(serialized),
            "sha256": hashlib.sha256(_canonical(serialized).encode()).hexdigest(),
            "rows": serialized,
        }
    return {
        "installation_id": installation_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        SCHEMA_VERSION_KEY: SCHEMA_VERSION,
        "tables": tables,
    }


def _model_for_table(name: str) -> Any:
    for cls in Base.registry._class_registry.values():
        if getattr(cls, "__table__", None) is not None and cls.__table__.name == name:
            return cls
    return None


def restore_backup(engine: Any, backup: dict[str, Any]) -> dict[str, Any]:
    """Recrea el esquema en un motor vacío y reinserta los datos."""

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    inserted: dict[str, int] = {}
    with factory() as db:
        # Orden topológico para respetar FKs al insertar.
        for table in Base.metadata.sorted_tables:
            name = table.name
            entry = backup["tables"].get(name)
            if entry is None:
                inserted[name] = 0
                continue
            cls = _model_for_table(name)
            if cls is None:
                inserted[name] = 0
                continue
            for row in entry["rows"]:
                kwargs = {
                    col.key: _deserialize_value(row.get(col.key), col)
                    for col in table.columns
                }
                db.add(cls(**kwargs))
            inserted[name] = entry["count"]
        db.commit()
    return {"inserted": inserted}


def verify_backup(db: Session, backup: dict[str, Any], *, installation_id: str | None = None) -> dict[str, Any]:
    """Compara conteos y sha256 del manifiesto contra la base dada."""

    mismatches: list[dict[str, Any]] = []
    for name, entry in sorted(backup["tables"].items()):
        cls = _model_for_table(name)
        if cls is None:
            continue
        rows = _table_rows(db, cls, installation_id)
        serialized = [
            {col.key: _serialize_value(getattr(row, col.key)) for col in cls.__table__.columns}
            for row in rows
        ]
        actual_sha = hashlib.sha256(_canonical(serialized).encode()).hexdigest()
        if len(serialized) != entry["count"] or actual_sha != entry["sha256"]:
            mismatches.append(
                {
                    "table": name,
                    "expected_count": entry["count"],
                    "actual_count": len(serialized),
                    "expected_sha": entry["sha256"],
                    "actual_sha": actual_sha,
                }
            )
    return {"ok": not mismatches, "mismatches": mismatches}


def restore_to_url(backup: dict[str, Any], database_url: str) -> dict[str, Any]:
    """Restaura un manifiesto a una base NUEVA y explícitamente preparada.

    Por seguridad esta función NO llama a ``drop_all`` sobre el destino. Sólo
    es válida cuando la base destino contiene el marker
    ``_bridge_restore_marker`` insertado por ``prepare_restore_target`` y no
    contiene tablas de aplicación; cualquier otro caso se rechaza con
    ``RestoreSafetyError``.

    El flujo correcto para un restore a una base nueva es::

        admin.execute("CREATE DATABASE backup_target")
        backup.prepare_restore_target(target_url)
        backup.restore_to_url(manifest, target_url)

    Llamadas accidentales a una URL equivocada (otra base con datos) o a una
    base que ya contiene tablas de aplicación serán abortadas sin tocar
    ningún dato.
    """

    engine = create_engine(database_url)
    try:
        _assert_restore_marker(engine)
        # Borra el marker para que el esquema de la aplicación quede limpio.
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {RESTORE_MARKER_TABLE}"))
        return restore_backup(engine, backup)
    finally:
        engine.dispose()


def rollback_installation(
    engine: Any, backup: dict[str, Any], *, installation_id: str
) -> dict[str, Any]:
    """Rollback de DATOS de una instalación: borra y reinserta desde el manifiesto.

    El rollback de ESQUEMA lo hace Alembic (downgrade/upgrade, ya probado en
    P0); aquí se restaura el estado de datos de la instalación a un punto
    conocido, de forma independiente del resto de instalaciones.
    """

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    restored: dict[str, int] = {}
    with factory() as db:
        # Borrado en orden inverso de dependencias.
        for table in reversed(Base.metadata.sorted_tables):
            cls = _model_for_table(table.name)
            if cls is None or not hasattr(cls, "installation_id"):
                continue
            db.query(cls).filter(cls.installation_id == installation_id).delete(
                synchronize_session=False
            )
        db.commit()
        # Reinserta solo las filas de la instalación desde el manifiesto.
        for table in Base.metadata.sorted_tables:
            entry = backup["tables"].get(table.name)
            cls = _model_for_table(table.name)
            if entry is None or cls is None or not hasattr(cls, "installation_id"):
                continue
            count = 0
            for row in entry["rows"]:
                if row.get("installation_id") != installation_id:
                    continue
                kwargs = {
                    col.key: _deserialize_value(row.get(col.key), col) for col in table.columns
                }
                db.add(cls(**kwargs))
                count += 1
            restored[table.name] = count
        db.commit()
    return {"restored": restored}
