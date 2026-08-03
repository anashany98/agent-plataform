"""Add the durable outbox table with dead-letter queue semantics.

Revision ID: 0004
Revises: 0003

The migration is additive and idempotent. The outbox stores authorized
external side effects (provider leads, notifications) that could not be
completed inline, with bounded retries and a dead-letter state. The
downgrade deliberately preserves the table and all queued work, matching
the schema-preserving downgrade policy of revisions 0001-0003.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    if "outbox_messages" not in _table_names():
        op.create_table(
            "outbox_messages",
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("topic", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.JSON(), nullable=True),
            sa.Column("response_body", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "installation_id",
                "topic",
                "idempotency_key",
                name="uq_outbox_installation_topic_key",
            ),
            sa.CheckConstraint(
                "state IN ('pending','processing','sent','dead')",
                name="ck_outbox_message_state",
            ),
            sa.CheckConstraint(
                "attempt_count >= 0",
                name="ck_outbox_message_attempts_nonnegative",
            ),
            sa.CheckConstraint(
                "max_attempts >= 1",
                name="ck_outbox_message_max_attempts_positive",
            ),
        )
    _create_index_if_missing(
        "ix_outbox_messages_installation_id", "outbox_messages", ["installation_id"]
    )
    _create_index_if_missing("ix_outbox_messages_topic", "outbox_messages", ["topic"])
    _create_index_if_missing("ix_outbox_messages_state", "outbox_messages", ["state"])
    _create_index_if_missing(
        "ix_outbox_messages_next_attempt_at", "outbox_messages", ["next_attempt_at"]
    )


def downgrade() -> None:
    # Deliberately preserve the outbox and all queued/dead-letter work.
    # Alembic only moves the revision marker, matching revisions 0001-0003.
    pass
