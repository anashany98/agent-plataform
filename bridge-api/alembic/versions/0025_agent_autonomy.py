"""Add agent autonomy by exception (T-068).

Revision ID: 0025
Revises: 0024

Autonomía por excepción: los agentes de módulo pueden EJECUTAR sin
aprobación humana por debajo de un umbral configurado por instalación,
dejando rastro auditable y reversible:

- ``agent_autonomy``: configuración por agente (una fila por instalación +
  agente). ``mode`` es ``manual`` (default, deny-by-default: todo exige
  aprobación humana, comportamiento actual) o ``autonomous``; cuando es
  autónomo, ``max_value_threshold`` (EUR) es el techo de impacto financiero
  y los flags ``allow_follow_ups``/``allow_spam_dismissals`` habilitan los
  tipos de acción de cero coste directo. ``notify_on_deviation_only`` hace
  que el digest solo avise cuando algo se desvía de lo esperado.
- ``agent_decisions``: registro inmutable de cada decisión auto-ejecutada
  (``executed_by`` = agente), con el efecto aplicado, bandera de
  ``deviation`` y los campos de revert (``reverted_at/by`` + motivo) para
  deshacerla con trazabilidad.

Idempotente (re-upgrade safe). Downgrade no destructivo (política del
proyecto: la configuración y el registro de decisiones son datos de
negocio y no se destruyen).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _table_names()
    if "agent_autonomy" not in tables:
        op.create_table(
            "agent_autonomy",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "installation_id", sa.String(length=128), nullable=False, index=True
            ),
            sa.Column("agent_id", sa.String(length=64), nullable=False, index=True),
            sa.Column(
                "mode",
                sa.String(length=16),
                nullable=False,
                server_default="manual",
            ),
            sa.Column(
                "max_value_threshold",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "allow_follow_ups", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "allow_spam_dismissals",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "notify_on_deviation_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.UniqueConstraint(
                "installation_id",
                "agent_id",
                name="uq_agent_autonomy_installation_agent",
            ),
            sa.CheckConstraint(
                "mode IN ('manual','autonomous')",
                name="ck_agent_autonomy_mode",
            ),
            sa.CheckConstraint(
                "max_value_threshold >= 0",
                name="ck_agent_autonomy_threshold_nonnegative",
            ),
        )
    if "agent_decisions" not in tables:
        op.create_table(
            "agent_decisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "installation_id", sa.String(length=128), nullable=False, index=True
            ),
            sa.Column("agent_id", sa.String(length=64), nullable=False, index=True),
            sa.Column(
                "action_type", sa.String(length=128), nullable=False, index=True
            ),
            sa.Column("target_key", sa.String(), nullable=False),
            sa.Column("executed_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("executed_by", sa.String(), nullable=False),
            sa.Column("approval_id", sa.String(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("deviation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reverted_at", sa.DateTime(), nullable=True),
            sa.Column("reverted_by", sa.String(), nullable=True),
            sa.Column("revert_reason", sa.String(), nullable=True),
            sa.UniqueConstraint(
                "installation_id",
                "action_type",
                "target_key",
                name="uq_agent_decision_installation_action_target",
            ),
        )


def downgrade() -> None:
    # Política del proyecto: no destructivo. Las tablas se conservan.
    pass
