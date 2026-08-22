"""Alertas durables para entrega externa (SS-07).

Revision ID: 0027
Revises: 0026

Crea ``alert_deliveries``: persiste cada alerta disparada por el evaluador
de observabilidad para entregarla fuera del proceso (webhook firmado con
HMAC y/o email) con reintentos y backoff. El ``AlertSink`` in-memory se
pierde al reiniciar; con esta tabla la alerta sobrevive al despliegue y el
worker la entrega cuando el servicio vuelve.

Aditiva e idempotente (re-upgrade safe). Downgrade no destructivo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "alert_deliveries" not in _table_names():
        op.create_table(
            "alert_deliveries",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.Column("rule_id", sa.String(length=128), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("dedup_key", sa.String(length=128), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            # Sin FK hacia installation_lifecycle: mismas convenciones que
            # el resto de tablas tenant-owned (columna plana indexada; el
            # ciclo de vida RGPD gestiona el borrado a nivel de servicio).
            sa.UniqueConstraint(
                "installation_id",
                "dedup_key",
                name="uq_alert_delivery_installation_dedup",
            ),
        )
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {
        ix["name"] for ix in inspector.get_indexes("alert_deliveries")
    }
    if "ix_alert_deliveries_due" not in existing_indexes:
        op.create_index(
            "ix_alert_deliveries_due",
            "alert_deliveries",
            ["status", "next_attempt_at"],
        )
    if "ix_alert_deliveries_rule" not in existing_indexes:
        op.create_index(
            "ix_alert_deliveries_rule",
            "alert_deliveries",
            ["installation_id", "rule_id"],
        )
    if "ix_alert_deliveries_installation_id" not in existing_indexes:
        op.create_index(
            "ix_alert_deliveries_installation_id",
            "alert_deliveries",
            ["installation_id"],
        )


def downgrade() -> None:
    # Política de downgrades preservadores del proyecto: la tabla se
    # conserva para no perder alertas pendientes si el operador vuelve a
    # una revisión previa.
    pass
