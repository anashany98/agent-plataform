"""Add master data: accounts, contacts, merge and close fields (CRM T-054).

Revision ID: 0021
Revises: 0020

Datos maestros del CRM — separar cuenta (empresa) de contacto (persona),
merge de duplicados, probabilidad por etapa y motivo de pérdida/ganancia:

- ``accounts``: empresa (name única por instalación) con datos de contacto
  e industria.
- ``contacts``: persona vinculada a una cuenta (FK blanda), email único por
  instalación; ``merged_into_contact_id`` marca absorbidos por un merge.
- ``leads``: + ``account_id``/``contact_id`` (asociación a cuenta y persona)
  y ``merged_into_lead_id`` (lead absorbido por un merge).
- ``opportunities``: + ``probability`` (override en %), ``lost_reason`` y
  ``won_at``/``lost_at`` para el cierre ganada/perdida.
- ``pipeline_stages``: + ``probability`` (probabilidad de cierre por etapa).

Idempotente (re-upgrade safe). Downgrade no destructivo (política del
proyecto: los datos maestros son datos de negocio y nunca se destruyen).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    if "accounts" not in _table_names():
        op.create_table(
            "accounts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("industry", sa.String(), nullable=True),
            sa.Column("website", sa.String(), nullable=True),
            sa.Column("phone", sa.String(), nullable=True),
            sa.Column("city", sa.String(), nullable=True),
            sa.Column("country", sa.String(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "name",
                name="uq_account_installation_name",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_account_installation_id",
            ),
        )
        op.create_index(
            "ix_accounts_installation_id", "accounts", ["installation_id"]
        )
        op.create_index("ix_accounts_name", "accounts", ["name"])

    if "contacts" not in _table_names():
        op.create_table(
            "contacts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("account_id", sa.String(), nullable=True),
            sa.Column("first_name", sa.String(), nullable=False),
            sa.Column("last_name", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("phone", sa.String(), nullable=True),
            sa.Column("job_title", sa.String(), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column("merged_into_contact_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "email",
                name="uq_contact_installation_email",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_contact_installation_id",
            ),
        )
        op.create_index(
            "ix_contacts_installation_id", "contacts", ["installation_id"]
        )
        op.create_index("ix_contacts_account_id", "contacts", ["account_id"])
        op.create_index("ix_contacts_email", "contacts", ["email"])
        op.create_index(
            "ix_contacts_merged_into_contact_id",
            "contacts",
            ["merged_into_contact_id"],
        )
        op.create_index(
            "ix_contact_account", "contacts", ["installation_id", "account_id"]
        )

    leads_cols = _columns("leads") if "leads" in _table_names() else set()
    if "account_id" not in leads_cols:
        op.add_column(
            "leads", sa.Column("account_id", sa.String(), nullable=True)
        )
        op.add_column("leads", sa.Column("contact_id", sa.String(), nullable=True))
        op.add_column(
            "leads", sa.Column("merged_into_lead_id", sa.String(), nullable=True)
        )
        op.create_index("ix_leads_account_id", "leads", ["account_id"])
        op.create_index("ix_leads_contact_id", "leads", ["contact_id"])
        op.create_index(
            "ix_leads_merged_into_lead_id", "leads", ["merged_into_lead_id"]
        )

    opp_cols = (
        _columns("opportunities") if "opportunities" in _table_names() else set()
    )
    if "probability" not in opp_cols:
        op.add_column(
            "opportunities",
            sa.Column("probability", sa.Integer(), nullable=True),
        )
        op.add_column(
            "opportunities", sa.Column("lost_reason", sa.String(), nullable=True)
        )
        op.add_column(
            "opportunities", sa.Column("won_at", sa.DateTime(), nullable=True)
        )
        op.add_column(
            "opportunities", sa.Column("lost_at", sa.DateTime(), nullable=True)
        )

    stage_cols = (
        _columns("pipeline_stages") if "pipeline_stages" in _table_names() else set()
    )
    if "probability" not in stage_cols:
        op.add_column(
            "pipeline_stages",
            sa.Column(
                "probability",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    # No destructivo (política del proyecto): cuentas, contactos, merges y
    # motivos de cierre son datos de negocio y nunca se destruyen.
    pass
