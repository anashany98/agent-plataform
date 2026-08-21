"""Add social listening agent (CRM T-056, fase 1).

Revision ID: 0023
Revises: 0022

Escucha social — conectores de redes (WhatsApp Cloud API y adaptador genérico
JSON+HMAC) que convierten mensajes entrantes en leads, actividades y timeline:

- ``social_channels``: canal configurado por el admin (tipo, nombre, cuenta
  externa, activo, secreto HMAC y verify token — nunca expuestos por API).
- ``social_messages``: mensaje entrante con dedupe por
  ``(installation_id, channel_id, source_message_id)`` (los retries de
  Meta/X no duplican) y estado pending_triage/triaged/dismissed/failed.
- ``social_triages``: resultado de la triage determinista por mensaje
  (intención lead/queja/consulta/spam/otra, idioma, registro, sentimiento,
  urgencia, entidades, ``score_social`` 0-100).

Idempotente (re-upgrade safe). Downgrade no destructivo (política del
proyecto: los mensajes y su triage son datos de negocio y nunca se destruyen).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "social_channels" not in _table_names():
        op.create_table(
            "social_channels",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("channel", sa.String(length=24), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("external_account_id", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("webhook_secret", sa.String(), nullable=False),
            sa.Column("verify_token", sa.String(), nullable=True),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("last_webhook_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_social_channel_installation_id",
            ),
        )
        op.create_index(
            "ix_social_channels_installation_id",
            "social_channels",
            ["installation_id"],
        )

    if "social_messages" not in _table_names():
        op.create_table(
            "social_messages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("channel_id", sa.String(), nullable=False),
            sa.Column("thread_id", sa.String(), nullable=True),
            sa.Column("source_message_id", sa.String(), nullable=False),
            sa.Column("direction", sa.String(length=8), nullable=False),
            sa.Column("sender_handle", sa.String(), nullable=True),
            sa.Column("sender_name", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("phone", sa.String(), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("media_urls", sa.JSON(), nullable=True),
            sa.Column("lead_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "channel_id",
                "source_message_id",
                name="uq_social_message_installation_channel_source",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_social_message_installation_id",
            ),
        )
        op.create_index(
            "ix_social_messages_installation_id",
            "social_messages",
            ["installation_id"],
        )
        op.create_index(
            "ix_social_messages_channel_id", "social_messages", ["channel_id"]
        )
        op.create_index(
            "ix_social_messages_thread_id", "social_messages", ["thread_id"]
        )
        op.create_index("ix_social_messages_lead_id", "social_messages", ["lead_id"])
        op.create_index(
            "ix_social_message_installation_channel",
            "social_messages",
            ["installation_id", "channel_id"],
        )

    if "social_triages" not in _table_names():
        op.create_table(
            "social_triages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("message_id", sa.String(), nullable=False),
            sa.Column("intent", sa.String(length=16), nullable=False),
            sa.Column("language", sa.String(length=8), nullable=True),
            sa.Column("register", sa.String(length=8), nullable=True),
            sa.Column("sentiment", sa.Float(), nullable=True),
            sa.Column("urgency", sa.Integer(), nullable=True),
            sa.Column("entities", sa.JSON(), nullable=True),
            sa.Column("score_social", sa.Integer(), nullable=False),
            sa.Column("summary", sa.String(), nullable=True),
            sa.Column("decided_by", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "message_id",
                name="uq_social_triage_installation_message",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_social_triage_installation_id",
            ),
        )
        op.create_index(
            "ix_social_triages_installation_id",
            "social_triages",
            ["installation_id"],
        )
        op.create_index(
            "ix_social_triages_message_id", "social_triages", ["message_id"]
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): los mensajes y su triage son
    # datos de negocio y nunca se destruyen.
    pass
