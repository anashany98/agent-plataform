"""Estado de ciclo de vida por instalación (export, erase, legal hold).

Revision ID: 0005
Revises: 0004

Una sola fila por ``installation_id`` controla la política de ciclo de
vida: legal hold, solicitud de borrado con retención y metadatos del
último export. La migración es aditiva e idempotente. El downgrade
preserva la tabla y cualquier fila pendiente para no perder auditoría.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "installation_lifecycle" not in _table_names():
        op.create_table(
            "installation_lifecycle",
            sa.Column("installation_id", sa.String(length=128), primary_key=True),
            sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("legal_hold_reason", sa.Text(), nullable=True),
            sa.Column("legal_hold_by", sa.String(length=255), nullable=True),
            sa.Column("legal_hold_at", sa.DateTime(), nullable=True),
            sa.Column("erase_requested_at", sa.DateTime(), nullable=True),
            sa.Column("erase_requested_by", sa.String(length=255), nullable=True),
            sa.Column("erase_reason", sa.Text(), nullable=True),
            sa.Column("erase_after", sa.DateTime(), nullable=True),
            sa.Column("erase_executed_at", sa.DateTime(), nullable=True),
            sa.Column("last_export_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    # Política de downgrades preservadores (0001-0004): se mantiene la tabla
    # para no perder auditoría si el operador vuelve a una revisión previa.
    pass
