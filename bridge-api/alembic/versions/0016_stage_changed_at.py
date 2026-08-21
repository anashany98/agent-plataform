"""Add stage_changed_at to opportunities (sales reporting P1-b aging).

Revision ID: 0016
Revises: 0015

Adds one new nullable-when-migrating column ``opportunities.stage_changed_at``
(backfilled with ``created_at`` for existing rows; NOT NULL after backfill).
It records when the opportunity entered its current pipeline stage and feeds
the per-stage aging of the sales report (``GET /pipeline/report``).

Idempotent (re-upgrade safe). The downgrade is non-destructive following the
migration policy: the column is metadata derived from the stage lifecycle and
is never dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "opportunities" in _table_names():
        columns = _column_names("opportunities")
        if "stage_changed_at" not in columns:
            op.add_column(
                "opportunities",
                sa.Column("stage_changed_at", sa.DateTime(), nullable=True),
            )
            # Backfill: las filas existentes entraron en su etapa actual en la
            # creación (no hay historial previo de cambios de etapa).
            op.execute(
                "UPDATE opportunities SET stage_changed_at = created_at "
                "WHERE stage_changed_at IS NULL"
            )
            # NOT NULL después del backfill vía batch: SQLite no soporta
            # ``ALTER COLUMN SET NOT NULL`` y batch reconstruye la tabla;
            # en PostgreSQL se emite el ALTER directo.
            with op.batch_alter_table("opportunities") as batch_op:
                batch_op.alter_column(
                    "stage_changed_at",
                    existing_type=sa.DateTime(),
                    nullable=False,
                )


def downgrade() -> None:
    # No destructivo (política del proyecto): el instante del último cambio de
    # etapa es metadato del ciclo de vida y no se destruye.
    pass
