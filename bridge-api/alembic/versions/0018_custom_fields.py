"""Add custom field definitions and values (CRM P1-c, T-044).

Revision ID: 0018
Revises: 0017

Adds two new tenant-owned tables: ``custom_field_definitions`` (per
installation, keyed by a stable ``key``, with type/options/required/
visibility/position/is_active) and ``custom_field_values`` (one validated
value per field and entity — lead or opportunity — stored as JSON). Values
reference their definition with a deferrable, installation-composite FK with
ON DELETE CASCADE; deactivating a definition (``is_active``) replaces
deletion so existing values survive.

Idempotent (re-upgrade safe). The downgrade is non-destructive following the
migration policy: custom fields are business data and are never dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _table_names()
    if "custom_field_definitions" not in existing:
        op.create_table(
            "custom_field_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("field_type", sa.String(), nullable=False),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("required", sa.Boolean(), nullable=False),
            sa.Column("visibility", sa.String(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "key",
                name="uq_custom_field_installation_key",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_custom_field_installation_id",
            ),
        )
        op.create_index(
            "ix_custom_field_definitions_installation_id",
            "custom_field_definitions",
            ["installation_id"],
        )
        op.create_index(
            "ix_custom_field_definitions_key",
            "custom_field_definitions",
            ["key"],
        )
        op.create_index(
            "ix_custom_field_definitions_entity_type",
            "custom_field_definitions",
            ["entity_type"],
        )

    if "custom_field_values" not in _table_names():
        op.create_table(
            "custom_field_values",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("field_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "field_id",
                "entity_type",
                "entity_id",
                name="uq_custom_value_installation_field_entity",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_custom_value_installation_id",
            ),
            sa.ForeignKeyConstraint(
                ["installation_id", "field_id"],
                [
                    "custom_field_definitions.installation_id",
                    "custom_field_definitions.id",
                ],
                name="fk_custom_value_installation_field",
                ondelete="CASCADE",
                deferrable=True,
                initially="DEFERRED",
            ),
        )
        op.create_index(
            "ix_custom_field_values_installation_id",
            "custom_field_values",
            ["installation_id"],
        )
        op.create_index(
            "ix_custom_field_values_field_id",
            "custom_field_values",
            ["field_id"],
        )
        op.create_index(
            "ix_custom_value_entity",
            "custom_field_values",
            ["installation_id", "entity_type", "entity_id"],
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): los campos personalizados son
    # datos de negocio y nunca se destruyen.
    pass
