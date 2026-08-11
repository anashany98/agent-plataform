"""Tablas locales de CRM (leads y oportunidades) para el core sin GHL.

Revision ID: 0007
Revises: 0006

Fase B (bloque 1): ``LocalCRMProvider`` persiste leads y oportunidades en
la BD local cuando GHL no está configurado, manteniendo la semántica de
idempotencia por ``external_reference`` de la reconciliación D-010.

La migración es **aditiva, idempotente y portable**: sólo usa tipos
estándar (String/Numeric/DateTime/JSON) que existen tanto en PostgreSQL
como en SQLite, por lo que —a diferencia de ``0006``— no necesita ser
dialect-aware. El ``downgrade`` sigue la política preservadora del
repositorio (0001-0006): no borra tablas para no perder leads ni
oportunidades ante un rollback de release.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "leads" not in _table_names():
        op.create_table(
            "leads",
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("id", sa.String(length=64), nullable=False),
            # La referencia externa es opcional en el lead (contacto); la
            # unicidad aplica solo cuando hay referencia.
            sa.Column("external_reference", sa.String(length=255), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=255), nullable=False),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column(
                "source", sa.String(length=64), nullable=False, server_default="local"
            ),
            sa.Column(
                "status", sa.String(length=64), nullable=False, server_default="new"
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "installation_id", "email", name="uq_lead_installation_email"
            ),
            sa.UniqueConstraint(
                "installation_id",
                "external_reference",
                name="uq_lead_installation_external_reference",
            ),
            sa.UniqueConstraint(
                "installation_id", "id", name="uq_lead_installation_id"
            ),
        )
        op.create_index("ix_leads_email", "leads", ["email"])
        op.create_index(
            "ix_leads_external_reference", "leads", ["external_reference"]
        )
        op.create_index("ix_leads_installation_id", "leads", ["installation_id"])

    if "opportunities" not in _table_names():
        op.create_table(
            "opportunities",
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("lead_id", sa.String(length=64), nullable=False),
            sa.Column("external_reference", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "monetary_value",
                sa.Numeric(14, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency", sa.String(length=16), nullable=False, server_default="EUR"
            ),
            sa.Column(
                "pipeline", sa.String(length=64), nullable=False, server_default="default"
            ),
            sa.Column(
                "stage", sa.String(length=64), nullable=False, server_default="new"
            ),
            sa.Column(
                "status", sa.String(length=64), nullable=False, server_default="open"
            ),
            sa.Column("notes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "installation_id",
                "external_reference",
                name="uq_opportunity_installation_external_reference",
            ),
            sa.UniqueConstraint(
                "installation_id", "id", name="uq_opportunity_installation_id"
            ),
            sa.ForeignKeyConstraint(
                ["installation_id", "lead_id"],
                ["leads.installation_id", "leads.id"],
                name="fk_opportunity_installation_lead",
                deferrable=True,
                initially="DEFERRED",
            ),
        )
        op.create_index(
            "ix_opportunities_external_reference",
            "opportunities",
            ["external_reference"],
        )
        op.create_index(
            "ix_opportunities_installation_id", "opportunities", ["installation_id"]
        )


def downgrade() -> None:
    # Política de downgrades preservadores (0001-0006): se mantienen las
    # tablas para no perder leads/oportunidades ante un rollback de release.
    pass
