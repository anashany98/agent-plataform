"""Add per-installation appearance settings (T-061).

Revision ID: 0024
Revises: 0023

Apariencia por instalación (una fila por instalación, patrón get-or-create
igual que ``email_settings``):

- ``installation_appearance``: ``accent_color`` (#RRGGBB, default
  ``#246bfd``) que el portal aplica a las variables CSS de acento, con
  ``updated_by`` para la auditoría de quién cambió la marca.

Idempotente (re-upgrade safe). Downgrade no destructivo (política del
proyecto: la configuración es dato de negocio y no se destruye).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "installation_appearance" not in _table_names():
        op.create_table(
            "installation_appearance",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "installation_id", sa.String(length=128), nullable=False, index=True
            ),
            sa.Column(
                "accent_color",
                sa.String(length=7),
                nullable=False,
                server_default="#246bfd",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_installation_appearance_installation_id",
            ),
        )


def downgrade() -> None:
    # Política del proyecto: no destructivo. La tabla se conserva.
    pass
