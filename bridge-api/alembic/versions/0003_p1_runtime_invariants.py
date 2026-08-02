"""Add durable idempotency leases and an installation-scoped LLM cost ledger.

Revision ID: 0003
Revises: 0002

The migration is additive and safe to re-run after the deliberately
schema-preserving downgrade used by this project. Existing processing rows are
made retryable instead of being silently treated as completed work.
"""

import datetime
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


IDEMPOTENCY_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("updated_at", sa.DateTime(), nullable=True),
    sa.Column("state", sa.String(length=32), nullable=True),
    sa.Column("owner_id", sa.String(length=64), nullable=True),
    sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    sa.Column("event_payload", sa.JSON(), nullable=True),
    sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    sa.Column("attempt_count", sa.Integer(), nullable=True),
    sa.Column("last_error", sa.JSON(), nullable=True),
)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _check_names(table_name: str) -> set[str | None]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name)
    }


def _add_idempotency_columns() -> None:
    existing_columns = _column_names("idempotency_records")
    for column in IDEMPOTENCY_COLUMNS:
        if column.name not in existing_columns:
            op.add_column("idempotency_records", column)

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    records = sa.table(
        "idempotency_records",
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("state", sa.String(length=32)),
        sa.column("status_code", sa.Integer()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("last_error", sa.JSON()),
    )
    op.get_bind().execute(
        records.update()
        .where(records.c.updated_at.is_(None))
        .values(updated_at=sa.func.coalesce(records.c.created_at, now))
    )
    op.get_bind().execute(
        records.update()
        .where(records.c.state.is_(None))
        .values(
            state=sa.case(
                (records.c.status_code == 102, "failed"),
                else_="completed",
            ),
            attempt_count=sa.case(
                (records.c.status_code == 102, 1),
                else_=0,
            ),
        )
    )
    op.get_bind().execute(
        records.update()
        .where(records.c.status_code == 102, records.c.last_error.is_(None))
        .values(
            last_error={
                "type": "legacy_orphan",
                "message": "Claim heredado recuperable",
            }
        )
    )
    op.get_bind().execute(
        records.update()
        .where(records.c.attempt_count.is_(None))
        .values(attempt_count=0)
    )

    with op.batch_alter_table("idempotency_records") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        batch_op.alter_column(
            "state",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch_op.alter_column(
            "attempt_count",
            existing_type=sa.Integer(),
            nullable=False,
        )
        if "ck_idempotency_record_state" not in _check_names("idempotency_records"):
            batch_op.create_check_constraint(
                "ck_idempotency_record_state",
                "state IN ('processing','completed','failed')",
            )


def _create_daily_budget_table() -> None:
    if "daily_llm_budgets" in _table_names():
        return
    op.create_table(
        "daily_llm_budgets",
        sa.Column("installation_id", sa.String(length=128), nullable=False),
        sa.Column("budget_date", sa.Date(), nullable=False),
        sa.Column("spent_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "spent_usd >= 0",
            name="ck_daily_llm_budget_spent_nonnegative",
        ),
        sa.PrimaryKeyConstraint(
            "installation_id",
            "budget_date",
            name="pk_daily_llm_budgets",
        ),
    )


def _backfill_daily_budgets() -> None:
    if "audit_logs" not in _table_names() or "daily_llm_budgets" not in _table_names():
        return
    audits = sa.table(
        "audit_logs",
        sa.column("installation_id", sa.String(length=128)),
        sa.column("timestamp", sa.DateTime()),
        sa.column("estimated_cost_usd", sa.Numeric(14, 6)),
        sa.column("status", sa.String()),
    )
    budgets = sa.table(
        "daily_llm_budgets",
        sa.column("installation_id", sa.String(length=128)),
        sa.column("budget_date", sa.Date()),
        sa.column("spent_usd", sa.Numeric(14, 6)),
        sa.column("updated_at", sa.DateTime()),
    )
    totals: dict[tuple[str, datetime.date], Decimal] = {}
    rows = op.get_bind().execute(
        sa.select(
            audits.c.installation_id,
            audits.c.timestamp,
            audits.c.estimated_cost_usd,
        ).where(audits.c.status.in_(("success", "billing_anomaly")))
    ).all()
    for installation_id, timestamp, cost in rows:
        if not installation_id or timestamp is None or cost is None:
            continue
        budget_date = timestamp.date()
        key = (str(installation_id), budget_date)
        totals[key] = totals.get(key, Decimal("0")) + Decimal(cost)

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    for (installation_id, budget_date), spent_usd in totals.items():
        existing = op.get_bind().execute(
            sa.select(budgets.c.spent_usd).where(
                budgets.c.installation_id == installation_id,
                budgets.c.budget_date == budget_date,
            )
        ).scalar_one_or_none()
        if existing is None:
            op.get_bind().execute(
                budgets.insert().values(
                    installation_id=installation_id,
                    budget_date=budget_date,
                    spent_usd=spent_usd,
                    updated_at=now,
                )
            )
        elif Decimal(existing) < spent_usd:
            op.get_bind().execute(
                budgets.update()
                .where(
                    budgets.c.installation_id == installation_id,
                    budgets.c.budget_date == budget_date,
                )
                .values(spent_usd=spent_usd, updated_at=now)
            )


def upgrade() -> None:
    if "idempotency_records" not in _table_names():
        raise RuntimeError("Falta idempotency_records; aplique primero las revisiones 0001 y 0002")
    _add_idempotency_columns()
    _create_daily_budget_table()
    _backfill_daily_budgets()


def downgrade() -> None:
    # Deliberately preserve the safety schema and all billing/idempotency data.
    # Alembic only moves the revision marker, matching revisions 0001/0002.
    pass
