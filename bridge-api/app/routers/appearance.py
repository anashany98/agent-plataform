"""Router de apariencia por instalación (extraído de main.py, B-01)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.common import audit
from app.security import ADMIN_ROLES, READ_ROLES, Principal, require_roles
from app.services.appearance_service import (
    appearance_response,
    get_or_create_appearance,
    is_valid_accent_color,
    set_accent_color,
)

router = APIRouter(tags=["Apariencia"])


class AppearanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accent_color: str = Field(min_length=7, max_length=7)


@router.get("/appearance/settings")
def get_appearance_settings(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Color de acento de la marca de la instalación (get-or-create)."""

    return appearance_response(get_or_create_appearance(db))


@router.put("/appearance/settings")
def update_appearance_settings(
    req: AppearanceUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Actualiza el color de acento (solo admin, auditado).

    Formato estricto ``#RRGGBB`` (regex) para no inyectar CSS arbitrario;
    el portal lo aplica a las variables CSS de acento.
    """

    if not is_valid_accent_color(req.accent_color):
        raise HTTPException(
            status_code=422,
            detail="El color de acento debe tener formato #RRGGBB (por ejemplo #246bfd).",
        )
    row = get_or_create_appearance(db)
    changed: list[str] = []
    if row.accent_color != req.accent_color:
        row = set_accent_color(db, row, req.accent_color, principal.username)
        changed.append("accent_color")
    response = appearance_response(row)
    audit(
        db,
        event_type="appearance.settings_updated",
        status_value="success",
        details={"changed": changed, "accent_color": req.accent_color},
        principal=principal,
    )
    return response
