"""Add email templates, settings and tracking events (CRM P2, T-044).

Revision ID: 0020
Revises: 0019

Adds three tenant-owned tables for the integrated email module:

- ``email_templates``: per-installation reusable templates (stable ``name``,
  subject/body with ``{{variable}}`` placeholders, optional signature, active
  flag).
- ``email_settings``: one row per installation — footer signature and whether
  open/click tracking is enabled.
- ``email_tracking_events``: token → (sent/open/click) records used by the
  public tracking endpoints (pixel + redirect); unique per
  (installation_id, token, event_type) so re-opens and re-clicks are
  idempotent.

Idempotent (re-upgrade safe). The downgrade is non-destructive following the
migration policy: templates, settings and tracking events are business data
and are never dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _table_names()
    if "email_templates" not in existing:
        op.create_table(
            "email_templates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("signature", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "name",
                name="uq_email_template_installation_name",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_email_template_installation_id",
            ),
        )
        op.create_index(
            "ix_email_templates_installation_id",
            "email_templates",
            ["installation_id"],
        )
        op.create_index(
            "ix_email_templates_name",
            "email_templates",
            ["name"],
        )

    if "email_settings" not in _table_names():
        op.create_table(
            "email_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("signature", sa.Text(), nullable=True),
            sa.Column("tracking_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_email_settings_installation_id",
            ),
        )
        op.create_index(
            "ix_email_settings_installation_id",
            "email_settings",
            ["installation_id"],
        )

    if "email_tracking_events" not in _table_names():
        op.create_table(
            "email_tracking_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(length=16), nullable=False),
            sa.Column("url", sa.String(), nullable=True),
            sa.Column("to", sa.String(), nullable=True),
            sa.Column("template_name", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "token",
                "event_type",
                name="uq_email_tracking_installation_token_event",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_email_tracking_event_installation_id",
            ),
        )
        op.create_index(
            "ix_email_tracking_events_installation_id",
            "email_tracking_events",
            ["installation_id"],
        )
        op.create_index(
            "ix_email_tracking_events_token",
            "email_tracking_events",
            ["token"],
        )
        op.create_index(
            "ix_email_tracking_created",
            "email_tracking_events",
            ["installation_id", "created_at"],
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): plantillas, settings y eventos
    # de tracking son datos de negocio y nunca se destruyen.
    pass
