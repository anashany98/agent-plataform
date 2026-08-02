"""Create the historical transactional schema without importing application metadata.

Revision ID: 0001
Revises: None

This revision is also the adoption boundary for databases created before Alembic
was enforced.  Every operation is therefore idempotent and its downgrade is
intentionally non-destructive.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_dimension() -> int:
    raw_value = os.environ.get("EMBEDDING_DIMENSION", "768")
    try:
        dimension = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_DIMENSION debe ser un entero positivo") from exc
    if dimension <= 0:
        raise RuntimeError("EMBEDDING_DIMENSION debe ser un entero positivo")
    return dimension


def _create_table_if_missing(table_name: str, *elements: object) -> None:
    if not sa.inspect(op.get_bind()).has_table(table_name):
        op.create_table(table_name, *elements)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    _create_table_if_missing(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("installation_id", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_users_username", "users", ["username"], unique=True)
    _create_index_if_missing("ix_users_role", "users", ["role"])
    _create_index_if_missing("ix_users_installation_id", "users", ["installation_id"])

    _create_table_if_missing(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])
    _create_index_if_missing("ix_audit_logs_agent_id", "audit_logs", ["agent_id"])
    _create_index_if_missing("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    _create_index_if_missing("ix_audit_logs_event_type", "audit_logs", ["event_type"])

    _create_table_if_missing(
        "idempotency_records",
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    _create_index_if_missing(
        "ix_idempotency_records_created_at",
        "idempotency_records",
        ["created_at"],
    )

    _create_table_if_missing(
        "approval_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled','expired','failed')",
            name="ck_approval_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_type", "target_key", name="uq_approval_action_target"),
    )
    _create_index_if_missing("ix_approval_requests_action_type", "approval_requests", ["action_type"])
    _create_index_if_missing("ix_approval_requests_target_key", "approval_requests", ["target_key"])
    _create_index_if_missing("ix_approval_requests_status", "approval_requests", ["status"])

    _create_table_if_missing(
        "pricelists",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("discount_percentage", sa.Numeric(7, 4), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    _create_table_if_missing(
        "customers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("pricelist_id", sa.String(), nullable=True),
        sa.Column("tax_exempt", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pricelist_id"], ["pricelists.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_customers_email", "customers", ["email"], unique=True)

    _create_table_if_missing(
        "products",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("base_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_stock", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_product_stock_nonnegative"),
        sa.CheckConstraint("reserved_stock >= 0", name="ck_product_reserved_nonnegative"),
        sa.CheckConstraint(
            "reserved_stock <= stock_quantity",
            name="ck_product_reserved_not_above_stock",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_products_external_id", "products", ["external_id"], unique=True)
    _create_index_if_missing("ix_products_sku", "products", ["sku"], unique=True)
    _create_index_if_missing("ix_products_category", "products", ["category"])

    _create_table_if_missing(
        "quotes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("confirmation_token", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("shipping_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("grand_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','confirmed','cancelled','expired')",
            name="ck_quote_status",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_token"),
        sa.UniqueConstraint("confirmation_token", name="uq_quote_confirmation_token"),
    )
    _create_index_if_missing("ix_quotes_customer_id", "quotes", ["customer_id"])
    _create_index_if_missing("ix_quotes_account_id", "quotes", ["account_id"])
    _create_index_if_missing("ix_quotes_conversation_id", "quotes", ["conversation_id"])
    _create_index_if_missing(
        "ix_quotes_source_message_id",
        "quotes",
        ["source_message_id"],
        unique=True,
    )
    _create_index_if_missing("ix_quotes_status", "quotes", ["status"])

    _create_table_if_missing(
        "orders",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("quote_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("shipping_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("grand_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),
        sa.UniqueConstraint("quote_id", name="uq_order_quote_id"),
    )
    _create_index_if_missing("ix_orders_customer_id", "orders", ["customer_id"])
    _create_index_if_missing("ix_orders_quote_id", "orders", ["quote_id"])

    _create_table_if_missing(
        "stock_reservations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity_reserved > 0", name="ck_reservation_quantity_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "product_id",
            name="uq_reservation_order_product",
        ),
    )
    _create_index_if_missing("ix_stock_reservations_order_id", "stock_reservations", ["order_id"])
    _create_index_if_missing(
        "ix_stock_reservations_product_id",
        "stock_reservations",
        ["product_id"],
    )

    _create_table_if_missing(
        "invoice_drafts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_number"),
        sa.UniqueConstraint("order_id", name="uq_invoice_order_id"),
    )
    _create_index_if_missing("ix_invoice_drafts_order_id", "invoice_drafts", ["order_id"])
    _create_index_if_missing(
        "ix_invoice_drafts_customer_id",
        "invoice_drafts",
        ["customer_id"],
    )

    _create_table_if_missing(
        "conversation_states",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.Column("active_quote_id", sa.String(), nullable=True),
        sa.Column("order_id", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["active_quote_id"], ["quotes.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "conversation_id",
            name="uq_conversation_account",
        ),
    )
    _create_index_if_missing("ix_conversation_states_account_id", "conversation_states", ["account_id"])
    _create_index_if_missing(
        "ix_conversation_states_conversation_id",
        "conversation_states",
        ["conversation_id"],
    )

    _create_table_if_missing(
        "rag_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )

    embedding_type = Vector(_embedding_dimension()).with_variant(sa.JSON(), "sqlite")
    _create_table_if_missing(
        "rag_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["rag_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_rag_doc_chunk"),
    )
    _create_index_if_missing("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])


def downgrade() -> None:
    # 0001 is an adoption boundary. Removing it from Alembic's version history
    # must never delete an already-owned production schema or its data.
    pass
