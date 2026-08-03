"""Ciclo de vida de datos por instalación (D-029).

Capacidades:

- ``export_installation``: volcado JSON portable y neutro de todos los
  modelos tenant-owned (clientes, catálogo, presupuestos, pedidos,
  facturas, conversaciones, aprobaciones, RAG, idempotencia y outbox).
  Cubre el derecho de acceso/portabilidad. Nunca exporta ``users``
  (credenciales) y el ``AuditLog`` queda fuera del volcado por ser
  registro de cumplimiento.
- ``request_erase``: solicitud de borrado con retención configurable
  (inmediata con ``retention_days=0``) y motivo obligatorio.
- ``process_due_erases``: ejecuta los borrados cuya retención ha vencido.
- ``set_legal_hold``: bloqueo por litigio/investigación; mientras está
  activo ningún erase se ejecuta (se audita el bloqueo).

El ``AuditLog`` y los usuarios nunca se borran: el registro de
cumplimiento y las cuentas de acceso sobreviven al erase del dato
operativo. Cada acción queda auditada (``lifecycle.export``,
``lifecycle.erase``, ``lifecycle.erase_skipped``, ``lifecycle.legal_hold``).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    ConversationState,
    Customer,
    IdempotencyRecord,
    InstallationLifecycle,
    InvoiceDraft,
    Order,
    OutboxMessage,
    Pricelist,
    Product,
    Quote,
    RAGChunk,
    RAGDocument,
    utcnow,
)


class LifecycleError(ValueError):
    pass


class LegalHoldActive(LifecycleError):
    pass


# Orden de borrado seguro: primero los hijos (FK) y por último los padres.
# El AuditLog y los usuarios quedan fuera del erase por política de
# cumplimiento; el export incluye únicamente datos operativos.
_EXPORTABLE_MODELS: tuple[type, ...] = (
    Customer,
    Pricelist,
    Product,
    Quote,
    Order,
    InvoiceDraft,
    ConversationState,
    RAGDocument,
    RAGChunk,
    ApprovalRequest,
    IdempotencyRecord,
    OutboxMessage,
)

_ERASE_ORDER: tuple[type, ...] = (
    RAGChunk,
    RAGDocument,
    InvoiceDraft,
    Order,
    Quote,
    ConversationState,
    ApprovalRequest,
    IdempotencyRecord,
    OutboxMessage,
    Product,
    Pricelist,
    Customer,
)


@dataclass(slots=True)
class EraseSummary:
    installation_id: str
    executed_at: datetime.datetime
    tables: dict[str, int]
    files_removed: int


def _serialize(value: Any) -> Any:
    """Convierte tipos no serializables a JSON en representaciones portables."""

    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_serialize(item) for item in value]
    if isinstance(value, datetime.date):  # datetime es subclase de date
        return value.isoformat()
    if hasattr(value, "as_tuple"):  # Decimal
        return str(value)
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    mapper = sa_inspect(row).mapper
    return {column.key: _serialize(getattr(row, column.key)) for column in mapper.columns}


class LifecycleService:
    """Servicio de ciclo de vida limitado a la instalación activa."""

    def __init__(self, db: Session, *, installation_id: str) -> None:
        self.db = db
        self.installation_id = installation_id

    # ------------------------------------------------------------------
    # Estado por instalación
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        row = self._state()
        if row is None:
            return {
                "installation_id": self.installation_id,
                "legal_hold": False,
                "erase_requested_at": None,
                "erase_after": None,
                "erase_executed_at": None,
                "last_export_at": None,
            }
        return {
            "installation_id": self.installation_id,
            "legal_hold": bool(row.legal_hold),
            "legal_hold_reason": row.legal_hold_reason,
            "legal_hold_by": row.legal_hold_by,
            "legal_hold_at": row.legal_hold_at.isoformat() if row.legal_hold_at else None,
            "erase_requested_at": row.erase_requested_at.isoformat()
            if row.erase_requested_at
            else None,
            "erase_requested_by": row.erase_requested_by,
            "erase_reason": row.erase_reason,
            "erase_after": row.erase_after.isoformat() if row.erase_after else None,
            "erase_executed_at": row.erase_executed_at.isoformat()
            if row.erase_executed_at
            else None,
            "last_export_at": row.last_export_at.isoformat() if row.last_export_at else None,
        }

    def _state(self) -> InstallationLifecycle | None:
        return (
            self.db.query(InstallationLifecycle)
            .filter(InstallationLifecycle.installation_id == self.installation_id)
            .first()
        )

    def _ensure_state(self) -> InstallationLifecycle:
        row = self._state()
        if row is None:
            row = InstallationLifecycle(
                installation_id=self.installation_id,
                updated_at=utcnow(),
            )
            self.db.add(row)
            self.db.flush()
        return row

    def _scoped(self, model: type) -> Any:
        """Consulta filtrada por instalación (defensa en profundidad)."""

        return self.db.query(model).filter(
            model.installation_id == self.installation_id
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_installation(self, *, actor: str) -> dict[str, Any]:
        sections: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for model in _EXPORTABLE_MODELS:
            rows = self._scoped(model).all()
            counts[model.__tablename__] = len(rows)
            sections[model.__tablename__] = [_row_dict(row) for row in rows]

        now = utcnow()
        state = self._ensure_state()
        state.last_export_at = now
        state.updated_at = now

        self.db.add(
            AuditLog(
                correlation_id=f"lifecycle-export-{now.timestamp()}",
                agent_id="lifecycle",
                user_id=actor,
                event_type="lifecycle.export",
                provider="internal",
                model_name="deterministic",
                status="success",
                details={
                    "installation_id": self.installation_id,
                    "counts": counts,
                    "actor": actor,
                },
            )
        )
        self.db.commit()

        return {
            "installation_id": self.installation_id,
            "exported_at": now.isoformat(),
            "actor": actor,
            "counts": counts,
            "data": sections,
        }

    # ------------------------------------------------------------------
    # Erase
    # ------------------------------------------------------------------

    def request_erase(
        self,
        *,
        actor: str,
        reason: str,
        retention_days: int = 0,
    ) -> dict[str, Any]:
        """Registra la solicitud; ``retention_days=0`` ejecuta el borrado ya."""

        if retention_days < 0:
            raise LifecycleError("retention_days debe ser >= 0")
        state = self._ensure_state()
        if state.legal_hold:
            raise LegalHoldActive(
                f"La instalación {self.installation_id} tiene legal hold activo"
            )

        now = utcnow()
        state.erase_requested_at = now
        state.erase_requested_by = actor
        state.erase_reason = reason
        state.erase_after = now if retention_days == 0 else now + datetime.timedelta(
            days=retention_days
        )
        state.updated_at = now
        self.db.flush()

        executed: EraseSummary | None = None
        if retention_days == 0:
            executed = self._execute_erase(actor=actor, state=state)
        else:
            self._audit(
                event_type="lifecycle.erase_scheduled",
                actor=actor,
                details={
                    "installation_id": self.installation_id,
                    "retention_days": retention_days,
                    "erase_after": state.erase_after.isoformat(),
                    "reason": reason,
                },
            )
            self.db.commit()

        return {
            "state": self.get_state(),
            "executed": _summary(executed),
        }

    def set_legal_hold(
        self,
        *,
        active: bool,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        state = self._ensure_state()
        now = utcnow()
        previous = bool(state.legal_hold)
        state.legal_hold = active
        if active:
            state.legal_hold_reason = reason
            state.legal_hold_by = actor
            state.legal_hold_at = now
        else:
            state.legal_hold_reason = None
            state.legal_hold_by = None
            state.legal_hold_at = None
        state.updated_at = now

        self._audit(
            event_type="lifecycle.legal_hold",
            actor=actor,
            details={
                "installation_id": self.installation_id,
                "previous": previous,
                "active": active,
                "reason": reason,
            },
        )
        self.db.commit()
        return self.get_state()

    def process_due_erases(self, *, actor: str = "system") -> list[dict[str, Any]]:
        """Ejecuta los borrados cuya retención venció; legal hold bloquea."""

        state = self._state()
        if state is None or state.erase_after is None or state.erase_executed_at is not None:
            return []
        if state.erase_after > utcnow():
            return []
        if state.legal_hold:
            self._audit(
                event_type="lifecycle.erase_skipped",
                actor=actor,
                details={
                    "installation_id": self.installation_id,
                    "reason": "legal_hold",
                },
            )
            self.db.commit()
            return []
        summary = self._execute_erase(actor=actor, state=state)
        return [_summary(summary)]

    def _execute_erase(self, *, actor: str, state: InstallationLifecycle) -> EraseSummary:
        if state.legal_hold:
            raise LegalHoldActive(
                f"La instalación {self.installation_id} tiene legal hold activo"
            )

        tables: dict[str, int] = {}
        rag_files: list[str] = []
        for model in _ERASE_ORDER:
            if model is RAGDocument:
                rag_files = [
                    str(row.file_path)
                    for row in self._scoped(RAGDocument).all()
                    if row.file_path
                ]
            query = self._scoped(model)
            count = query.count()
            query.delete(synchronize_session=False)
            tables[model.__tablename__] = count

        files_removed = self._remove_rag_files(rag_files)

        now = utcnow()
        state.erase_executed_at = now
        state.erase_after = None
        state.updated_at = now

        self._audit(
            event_type="lifecycle.erase",
            actor=actor,
            details={
                "installation_id": self.installation_id,
                "tables": tables,
                "files_removed": files_removed,
            },
        )
        self.db.commit()
        return EraseSummary(
            installation_id=self.installation_id,
            executed_at=now,
            tables=tables,
            files_removed=files_removed,
        )

    @staticmethod
    def _remove_rag_files(paths: list[str]) -> int:
        """Elimina únicamente archivos dentro del directorio de subidas."""

        upload_root = Path(settings.RAG_UPLOAD_DIR).resolve()
        removed = 0
        for raw_path in paths:
            try:
                candidate = Path(raw_path).resolve()
            except OSError:
                continue
            if candidate == upload_root or upload_root not in candidate.parents:
                continue
            try:
                candidate.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        return removed

    def _audit(self, *, event_type: str, actor: str, details: dict[str, Any]) -> None:
        self.db.add(
            AuditLog(
                correlation_id=f"lifecycle-{utcnow().timestamp()}",
                agent_id="lifecycle",
                user_id=actor,
                event_type=event_type,
                provider="internal",
                model_name="deterministic",
                status="success" if "skipped" not in event_type else "blocked",
                details=details,
            )
        )


def _summary(summary: EraseSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "installation_id": summary.installation_id,
        "executed_at": summary.executed_at.isoformat(),
        "tables": summary.tables,
        "files_removed": summary.files_removed,
    }


def dump_export(export: dict[str, Any]) -> str:
    """Serializa un export a JSON portable."""

    return json.dumps(export, ensure_ascii=False, separators=(",", ":"), default=str)
