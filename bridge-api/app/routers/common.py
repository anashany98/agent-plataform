"""Helpers compartidos por los routers de dominio (B-01).

``audit`` era ``_audit`` en ``app.main``; se extrae aquí para que los
routers puedan auditar sin importar el módulo principal (evita ciclos).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AuditLog
from app.security import Principal


def audit(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: dict[str, Any],
    principal: Principal | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> None:
    """Registra un evento determinista en el audit log de la instalación."""

    db.add(
        AuditLog(
            correlation_id=correlation_id or str(uuid.uuid4()),
            agent_id="system",
            user_id=principal.user_id if principal else None,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )
    if commit:
        db.commit()
