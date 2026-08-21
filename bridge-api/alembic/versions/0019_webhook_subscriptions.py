"""Add webhook subscriptions for CRM outbound events (P2-f, T-044).

Revision ID: 0019
Revises: 0018

Adds the tenant-owned ``webhook_subscriptions`` table: per installation,
each subscription holds a destination URL, its own HMAC secret (independent
from the product-wide secret), the list of subscribed event types (from the
stable ``WEBHOOK_EVENT_CATALOG``) and an active flag. CRM events enqueue one
durable outbox message per active subscription (topic ``crm.webhook``); the
dispatcher signs with the subscription secret and validates SSRF.

Idempotent (re-upgrade safe). The downgrade is non-destructive following the
migration policy: subscriptions are business data and are never dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _table_names()
    if "webhook_subscriptions" not in existing:
        op.create_table(
            "webhook_subscriptions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("secret", sa.String(), nullable=False),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "name",
                name="uq_webhook_subscription_installation_name",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_webhook_subscription_installation_id",
            ),
        )
        op.create_index(
            "ix_webhook_subscriptions_installation_id",
            "webhook_subscriptions",
            ["installation_id"],
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): las suscripciones son datos de
    # negocio y nunca se destruyen.
    pass
