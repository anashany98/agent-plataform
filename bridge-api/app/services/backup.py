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
from typing import Any

from sqlalchemy import DateTime, Numeric, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base

# Coincide con la revisión de migración más reciente (0005). Si el esquema
# cambia, bump de esta constante para invalidar restores incompatibles.
SCHEMA_VERSION = "0005"
SCHEMA_VERSION_KEY = "schema_version"


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
    """Restaura un manifiesto a una base vacía dada por URL (para pruebas/E2E)."""

    engine = create_engine(database_url)
    try:
        Base.metadata.drop_all(engine)
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
