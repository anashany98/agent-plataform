"""Extiende la autonomía por excepción con acciones seguras y tope diario.

Revision ID: 0026
Revises: 0025

Permite que los agentes sean lo más autónomos posible dentro del sobre de
seguridad: ``allowed_actions`` es una lista JSON de tipos de acción seguros y
reversibles (sin impacto financiero) que el agente puede auto-ejecutar en modo
``autonomous``, y ``max_actions_per_day`` acota cuántas decisiones autónomas
puede tomar cada agente por día natural (UTC).

Las acciones con impacto financiero/contable (confirmar pedidos, emitir
facturas, fijar precios, reservar stock) quedan fuera por diseño: siguen
exigiendo aprobación humana.

Aditiva e idempotente (re-upgrade safe). Downgrade no destructivo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _check_names(table: str) -> set[str | None]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
    }


def upgrade() -> None:
    # En el arranque con ``AUTO_CREATE_SCHEMA`` la tabla (y su check del
    # modelo) ya existen; aquí solo completamos lo que falte.
    if "agent_autonomy" not in _table_names():
        return
    existing = _column_names("agent_autonomy")
    if "allowed_actions" not in existing:
        op.add_column(
            "agent_autonomy",
            sa.Column("allowed_actions", sa.JSON(), nullable=True),
        )
    if "max_actions_per_day" not in existing:
        op.add_column(
            "agent_autonomy",
            sa.Column(
                "max_actions_per_day",
                sa.Integer(),
                nullable=False,
                server_default="10",
            ),
        )
    # El check va por batch: SQLite no soporta ``ALTER ... ADD CONSTRAINT``
    # y batch reconstruye la tabla (en PostgreSQL emite el ALTER directo).
    if "ck_agent_autonomy_daily_cap_nonnegative" not in _check_names(
        "agent_autonomy"
    ):
        with op.batch_alter_table("agent_autonomy") as batch_op:
            batch_op.create_check_constraint(
                "ck_agent_autonomy_daily_cap_nonnegative",
                "max_actions_per_day >= 0",
            )


def downgrade() -> None:
    # Política del proyecto: no destructivo. La configuración ampliada se
    # conserva; una versión anterior simplemente la ignora.
    pass
