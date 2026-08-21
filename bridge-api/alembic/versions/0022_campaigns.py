"""Add segmented email campaigns (CRM T-055).

Revision ID: 0022
Revises: 0021

Campañas segmentadas (P2): envíos de email a un segmento de leads definido
por score, fuente, comercial asignado, cuenta y/o valores de campos
personalizados, renderizados con las plantillas existentes y con tracking
por destinatario:

- ``campaigns``: nombre único por instalación, plantilla por nombre,
  segmento JSON, estado (draft/active/sent/cancelled), opcional
  ``scheduled_at`` y ``sent_at``.
- ``campaign_recipients``: destinatarios materializados al enviar
  (único por campaña y lead), con estado pending/sent/failed/skipped y
  ``tracking_token`` para derivar aperturas/clics desde
  ``email_tracking_events``.
- ``leads``: + ``email_opt_out`` (consentimiento RGPD): los leads que optan
  fuera quedan ``skipped`` en cualquier campaña.

Idempotente (re-upgrade safe). Downgrade no destructivo (política del
proyecto: los datos de negocio nunca se destruyen).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    if "campaigns" not in _table_names():
        op.create_table(
            "campaigns",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("template_name", sa.String(), nullable=False),
            sa.Column("segment", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "name",
                name="uq_campaign_installation_name",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_campaign_installation_id",
            ),
        )
        op.create_index(
            "ix_campaigns_installation_id", "campaigns", ["installation_id"]
        )
        op.create_index("ix_campaigns_name", "campaigns", ["name"])

    if "campaign_recipients" not in _table_names():
        op.create_table(
            "campaign_recipients",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("campaign_id", sa.String(), nullable=False),
            sa.Column("lead_id", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("first_name", sa.String(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("tracking_token", sa.String(), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "campaign_id",
                "lead_id",
                name="uq_campaign_recipient_installation_campaign_lead",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_campaign_recipient_installation_id",
            ),
        )
        op.create_index(
            "ix_campaign_recipients_installation_id",
            "campaign_recipients",
            ["installation_id"],
        )
        op.create_index(
            "ix_campaign_recipients_campaign_id",
            "campaign_recipients",
            ["campaign_id"],
        )
        op.create_index(
            "ix_campaign_recipients_lead_id", "campaign_recipients", ["lead_id"]
        )
        op.create_index(
            "ix_campaign_recipient_installation_campaign",
            "campaign_recipients",
            ["installation_id", "campaign_id"],
        )

    leads_cols = _columns("leads") if "leads" in _table_names() else set()
    if "email_opt_out" not in leads_cols:
        op.add_column(
            "leads",
            sa.Column(
                "email_opt_out",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): campañas, destinatarios y el
    # consentimiento de email son datos de negocio y nunca se destruyen.
    pass
