"""Add bounded conversation memory for the commercial chat.

Revision ID: 0014
Revises: 0013

Adds one new tenant-owned table ``conversation_messages``: the webhook
registers each client message and each assistant reply per conversation, and
``commerce_chat`` receives the last N as conversational context (never as a
product-data source). The sequence column provides strict per-conversation
ordering; older rows are pruned on insert to keep the memory bounded.

The downgrade is intentionally non-destructive (history is conversation
memory, not business records), following the existing migration policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # El downgrade es no destructivo (conserva la memoria de conversación),
    # así que un re-upgrade debe ser idempotente: si la tabla ya existe, no
    # se recrea (mismo patrón que la migración 0013).
    if "conversation_messages" in _table_names():
        return
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("installation_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "installation_id",
            "account_id",
            "conversation_id",
            "sequence",
            name="uq_conversation_message_sequence",
        ),
        sa.UniqueConstraint(
            "installation_id",
            "id",
            name="uq_conversation_message_id",
        ),
    )
    op.create_index(
        "ix_conversation_messages_scope",
        "conversation_messages",
        ["installation_id", "account_id", "conversation_id"],
    )
    op.create_index(
        "ix_conversation_messages_installation_id",
        "conversation_messages",
        ["installation_id"],
    )
    op.create_index(
        "ix_conversation_messages_account_id",
        "conversation_messages",
        ["account_id"],
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    # No se destruye el historial de conversación: solo se deja de mantener.
    pass
