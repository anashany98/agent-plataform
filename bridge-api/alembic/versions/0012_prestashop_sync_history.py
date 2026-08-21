"""Historial auditado de ejecuciones del sync de PrestaShop.

Revision ID: 0012
Revises: 0011

Una fila por ejecución de ``POST /integrations/prestashop/sync`` (completo o
incremental con ``since``): fecha de inicio y fin, duración, ventana del
delta, conteos (creados/actualizados/sin cambios) y estado. Permite verificar
que el cron diario (``scripts/prestashop-sync-incremental.py``) corre y qué
encontró cada día.

Migración aditiva e idempotente (mismo patrón que 0005): si la tabla ya
existe no hace nada. El downgrade preserva la tabla para no perder auditoría.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "prestashop_sync_history" not in _table_names():
        op.create_table(
            "prestashop_sync_history",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("since", sa.String(length=32), nullable=True),
            sa.Column("incremental", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("total_remote", sa.Integer(), nullable=False),
            sa.Column("created", sa.Integer(), nullable=False),
            sa.Column("updated", sa.Integer(), nullable=False),
            sa.Column("unchanged", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_prestashop_sync_history_started_at",
            "prestashop_sync_history",
            ["started_at"],
        )
        op.create_index(
            "ix_prestashop_sync_history_installation_id",
            "prestashop_sync_history",
            ["installation_id"],
        )


def downgrade() -> None:
    # Política de downgrades preservadores (0001-0005): se mantiene la tabla
    # para no perder auditoría si el operador vuelve a una revisión previa.
    pass
