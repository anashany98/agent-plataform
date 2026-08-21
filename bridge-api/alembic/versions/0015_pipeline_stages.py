"""Add configurable pipeline stages and lead assignment (kanban P1-a).

Revision ID: 0015
Revises: 0014

Adds one new tenant-owned table ``pipeline_stages`` (the ordered, editable
stages of the commercial kanban; ``Opportunity.stage`` stores the stable
``key``) and one new nullable column ``leads.assigned_to`` (owner commercial
id; NULL = unassigned lead that appears in the kanban queue).

Both additions are idempotent (re-upgrade safe) and the downgrade is
non-destructive following the migration policy: the stages are configuration
(seeded on demand) and the assignment is business data — neither is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "pipeline_stages" not in _table_names():
        op.create_table(
            "pipeline_stages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id", "key", name="uq_pipeline_stage_installation_key"
            ),
            sa.UniqueConstraint(
                "installation_id", "name", name="uq_pipeline_stage_installation_name"
            ),
            sa.UniqueConstraint(
                "installation_id", "id", name="uq_pipeline_stage_installation_id"
            ),
        )
        op.create_index(
            "ix_pipeline_stages_installation_id",
            "pipeline_stages",
            ["installation_id"],
        )
        op.create_index("ix_pipeline_stages_key", "pipeline_stages", ["key"])
    if "leads" in _table_names() and "assigned_to" not in _column_names("leads"):
        op.add_column("leads", sa.Column("assigned_to", sa.String(), nullable=True))
        op.create_index("ix_leads_assigned_to", "leads", ["assigned_to"])


def downgrade() -> None:
    # No destructivo (política del proyecto): la configuración de etapas se
    # vuelve a sembrar y la asignación es dato de negocio que no se destruye.
    pass
