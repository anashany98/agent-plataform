"""Add activities (commercial tasks with reminders, T-044).

Revision ID: 0017
Revises: 0016

Adds one new tenant-owned table ``activities``: commercial tasks linked to a
lead (and optionally an opportunity) with a due date, an optional email
reminder (``remind_at`` + ``remind_email``) and a lifecycle status. The
reminder worker scans ``ix_activity_due`` (installation, status, remind_at).

Idempotent (re-upgrade safe). The downgrade is non-destructive following the
migration policy: activities are business data and are never dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "activities" not in _table_names():
        op.create_table(
            "activities",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("lead_id", sa.String(), nullable=True),
            sa.Column("opportunity_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("remind_at", sa.DateTime(), nullable=True),
            sa.Column("reminded_at", sa.DateTime(), nullable=True),
            sa.Column("remind_email", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("assigned_to", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("completed_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_activity_installation_id",
            ),
        )
        op.create_index("ix_activity_due", "activities", ["installation_id", "status", "remind_at"])
        op.create_index("ix_activities_installation_id", "activities", ["installation_id"])
        op.create_index("ix_activities_lead_id", "activities", ["lead_id"])
        op.create_index("ix_activities_opportunity_id", "activities", ["opportunity_id"])
        op.create_index("ix_activities_status", "activities", ["status"])


def downgrade() -> None:
    # No destructivo (política del proyecto): las actividades son datos de
    # negocio y nunca se destruyen.
    pass
