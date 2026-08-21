"""Apariencia por instalación (T-061): color de acento de la marca.

Una fila por instalación (patrón get-or-create idéntico a
``email_settings``): ``accent_color`` en formato ``#RRGGBB`` que el portal
aplica a las variables CSS ``--accent``/``--accent-soft``. La validación es
estricta (regex hex) para no inyectar CSS arbitrario.
"""

from __future__ import annotations

import datetime
import re

from app.models.models import InstallationAppearance
from sqlalchemy.orm import Session

DEFAULT_ACCENT_COLOR = "#246bfd"
ACCENT_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_valid_accent_color(value: str) -> bool:
    return bool(ACCENT_HEX_RE.match(value or ""))


def get_or_create_appearance(db: Session) -> InstallationAppearance:
    """Devuelve (creando si falta) la fila única de apariencia por instalación."""

    row = db.query(InstallationAppearance).first()
    if row is None:
        row = InstallationAppearance(accent_color=DEFAULT_ACCENT_COLOR)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def appearance_response(row: InstallationAppearance) -> dict[str, str | None]:
    return {
        "accent_color": row.accent_color,
        "updated_at": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
        "updated_by": row.updated_by,
    }


def set_accent_color(
    db: Session, row: InstallationAppearance, accent_color: str, username: str
) -> InstallationAppearance:
    """Aplica el color de acento y marca quién lo cambió (auditable)."""

    row.accent_color = accent_color
    row.updated_by = username
    row.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return row
