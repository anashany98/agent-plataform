"""Backfill installation ownership and confirmation/reservation lifecycles.

Revision ID: 0002
Revises: 0001

The upgrade accepts an existing 0001 database only when INSTALLATION_ID is
explicitly configured.  Downgrade is deliberately schema-compatible: it only
moves Alembic's revision marker because removing tenant constraints could
re-enable cross-installation relationships.
"""

import datetime
import hashlib
import json
import os
import re
import string
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "audit_logs",
    "idempotency_records",
    "approval_requests",
    "pricelists",
    "customers",
    "products",
    "quotes",
    "orders",
    "stock_reservations",
    "invoice_drafts",
    "conversation_states",
    "rag_documents",
    "rag_chunks",
)

INSTALLATION_INDEX_TABLES = tuple(
    table_name for table_name in TENANT_TABLES if table_name != "idempotency_records"
)

LEGACY_UNIQUE_CONSTRAINTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "approval_requests": (("action_type", "target_key"),),
    "quotes": (("confirmation_token",),),
    "orders": (("quote_id",), ("idempotency_key",)),
    "stock_reservations": (("order_id", "product_id"),),
    "invoice_drafts": (("order_id",), ("invoice_number",)),
    "conversation_states": (("account_id", "conversation_id"),),
    "rag_documents": (("sha256",),),
    "rag_chunks": (("document_id", "chunk_index"),),
}

FINAL_UNIQUE_CONSTRAINTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "users": (
        (
            "uq_user_installation_username",
            ("installation_id", "username"),
        ),
    ),
    "approval_requests": (
        (
            "uq_approval_installation_action_target",
            ("installation_id", "action_type", "target_key"),
        ),
    ),
    "pricelists": (
        ("uq_pricelist_installation_id", ("installation_id", "id")),
    ),
    "customers": (
        ("uq_customer_installation_email", ("installation_id", "email")),
        ("uq_customer_installation_id", ("installation_id", "id")),
    ),
    "products": (
        (
            "uq_product_installation_external_id",
            ("installation_id", "external_id"),
        ),
        ("uq_product_installation_sku", ("installation_id", "sku")),
        ("uq_product_installation_id", ("installation_id", "id")),
    ),
    "quotes": (
        (
            "uq_quote_installation_confirmation_token",
            ("installation_id", "confirmation_token"),
        ),
        (
            "uq_quote_installation_source_message",
            ("installation_id", "source_message_id"),
        ),
        ("uq_quote_installation_id", ("installation_id", "id")),
    ),
    "orders": (
        ("uq_order_installation_quote_id", ("installation_id", "quote_id")),
        (
            "uq_order_installation_idempotency_key",
            ("installation_id", "idempotency_key"),
        ),
        ("uq_order_installation_id", ("installation_id", "id")),
    ),
    "stock_reservations": (
        (
            "uq_reservation_installation_order_product",
            ("installation_id", "order_id", "product_id"),
        ),
    ),
    "invoice_drafts": (
        (
            "uq_invoice_installation_order_id",
            ("installation_id", "order_id"),
        ),
        (
            "uq_invoice_installation_number",
            ("installation_id", "invoice_number"),
        ),
    ),
    "conversation_states": (
        (
            "uq_conversation_installation_account",
            ("installation_id", "account_id", "conversation_id"),
        ),
    ),
    "rag_documents": (
        (
            "uq_rag_document_installation_sha256",
            ("installation_id", "sha256"),
        ),
        ("uq_rag_document_installation_id", ("installation_id", "id")),
    ),
    "rag_chunks": (
        (
            "uq_rag_chunk_installation_document_index",
            ("installation_id", "document_id", "chunk_index"),
        ),
    ),
}

KNOWN_NAMED_UNIQUE_CONSTRAINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "approval_requests": {
        "uq_approval_action_target": ("action_type", "target_key"),
    },
    "quotes": {
        "uq_quote_confirmation_token": ("confirmation_token",),
    },
    "orders": {
        "uq_order_quote_id": ("quote_id",),
        "uq_order_idempotency_key": ("idempotency_key",),
    },
    "stock_reservations": {
        "uq_reservation_order_product": ("order_id", "product_id"),
    },
    "invoice_drafts": {
        "uq_invoice_order_id": ("order_id",),
    },
    "conversation_states": {
        "uq_conversation_account": ("account_id", "conversation_id"),
    },
    "rag_chunks": {
        "uq_rag_doc_chunk": ("document_id", "chunk_index"),
    },
}
for _table_name, _constraints in FINAL_UNIQUE_CONSTRAINTS.items():
    table_contract = KNOWN_NAMED_UNIQUE_CONSTRAINTS.setdefault(_table_name, {})
    for _constraint_name, _constraint_columns in _constraints:
        table_contract[_constraint_name] = _constraint_columns

BATCH_NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}

MONEY_QUANTUM = Decimal("0.01")
LEGACY_RESERVATION_TTL = datetime.timedelta(minutes=15)
ALLOWED_RESERVATION_STATUSES = {"active", "released", "expired", "cancelled"}

HISTORICAL_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "users": frozenset(
        {
            "id",
            "username",
            "password_hash",
            "role",
            "installation_id",
            "is_active",
            "must_change_password",
            "token_version",
            "created_at",
        }
    ),
    "audit_logs": frozenset(
        {
            "id",
            "timestamp",
            "correlation_id",
            "agent_id",
            "user_id",
            "event_type",
            "provider",
            "model_name",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "latency_ms",
            "estimated_cost_usd",
            "status",
            "details",
        }
    ),
    "idempotency_records": frozenset(
        {"idempotency_key", "created_at", "response_body", "status_code"}
    ),
    "approval_requests": frozenset(
        {
            "id",
            "created_at",
            "action_type",
            "target_key",
            "payload",
            "requested_by",
            "status",
            "reviewed_at",
            "reviewed_by",
            "rejection_reason",
        }
    ),
    "pricelists": frozenset({"id", "name", "discount_percentage"}),
    "customers": frozenset(
        {
            "id",
            "name",
            "email",
            "phone",
            "company",
            "pricelist_id",
            "tax_exempt",
            "created_at",
        }
    ),
    "products": frozenset(
        {
            "id",
            "external_id",
            "sku",
            "name",
            "description",
            "category",
            "attributes",
            "source",
            "source_url",
            "base_price",
            "tax_rate",
            "stock_quantity",
            "reserved_stock",
            "created_at",
            "updated_at",
        }
    ),
    "quotes": frozenset(
        {
            "id",
            "customer_id",
            "account_id",
            "conversation_id",
            "confirmation_token",
            "source_message_id",
            "items",
            "subtotal",
            "tax_total",
            "shipping_total",
            "grand_total",
            "currency",
            "status",
            "created_at",
            "confirmed_at",
        }
    ),
    "orders": frozenset(
        {
            "id",
            "customer_id",
            "quote_id",
            "idempotency_key",
            "items",
            "subtotal",
            "tax_total",
            "shipping_total",
            "grand_total",
            "currency",
            "status",
            "created_at",
        }
    ),
    "stock_reservations": frozenset(
        {"id", "order_id", "product_id", "quantity_reserved", "status", "created_at"}
    ),
    "invoice_drafts": frozenset(
        {
            "id",
            "invoice_number",
            "order_id",
            "customer_id",
            "items",
            "total_amount",
            "tax_amount",
            "currency",
            "status",
            "created_at",
        }
    ),
    "conversation_states": frozenset(
        {
            "id",
            "account_id",
            "conversation_id",
            "customer_id",
            "active_quote_id",
            "order_id",
            "state",
            "updated_at",
        }
    ),
    "rag_documents": frozenset(
        {"id", "file_path", "file_name", "mime_type", "sha256", "metadata_json", "created_at"}
    ),
    "rag_chunks": frozenset(
        {"id", "document_id", "chunk_index", "text", "embedding", "metadata_json"}
    ),
}

FINAL_REQUIRED_COLUMNS = dict(HISTORICAL_REQUIRED_COLUMNS)
for _tenant_table_name in TENANT_TABLES:
    FINAL_REQUIRED_COLUMNS[_tenant_table_name] = (
        FINAL_REQUIRED_COLUMNS[_tenant_table_name] | {"installation_id"}
    )
FINAL_REQUIRED_COLUMNS["quotes"] = FINAL_REQUIRED_COLUMNS["quotes"] | {
    "confirmation_payload_hash",
    "confirmation_expires_at",
    "confirmation_consumed_at",
    "confirmed_by",
}
FINAL_REQUIRED_COLUMNS["stock_reservations"] = FINAL_REQUIRED_COLUMNS[
    "stock_reservations"
] | {"expires_at", "released_at"}

# Type signatures are deliberately dialect-neutral. String length is checked
# only where it is part of the security contract.
CRITICAL_COLUMN_TYPES: dict[tuple[str, str], tuple[object, ...]] = {
    ("users", "installation_id"): ("string",),
    ("audit_logs", "estimated_cost_usd"): ("numeric", 14, 6),
    ("audit_logs", "details"): ("json",),
    ("idempotency_records", "response_body"): ("json",),
    ("idempotency_records", "status_code"): ("integer",),
    ("approval_requests", "payload"): ("json",),
    ("pricelists", "discount_percentage"): ("numeric", 7, 4),
    ("products", "attributes"): ("json",),
    ("products", "base_price"): ("numeric", 14, 4),
    ("products", "tax_rate"): ("numeric", 7, 6),
    ("products", "stock_quantity"): ("integer",),
    ("products", "reserved_stock"): ("integer",),
    ("quotes", "items"): ("json",),
    ("quotes", "subtotal"): ("numeric", 14, 2),
    ("quotes", "tax_total"): ("numeric", 14, 2),
    ("quotes", "shipping_total"): ("numeric", 14, 2),
    ("quotes", "grand_total"): ("numeric", 14, 2),
    ("quotes", "confirmation_payload_hash"): ("string", 64),
    ("quotes", "confirmation_expires_at"): ("datetime",),
    ("quotes", "confirmation_consumed_at"): ("datetime",),
    ("quotes", "confirmed_by"): ("string", 255),
    ("orders", "items"): ("json",),
    ("orders", "subtotal"): ("numeric", 14, 2),
    ("orders", "tax_total"): ("numeric", 14, 2),
    ("orders", "shipping_total"): ("numeric", 14, 2),
    ("orders", "grand_total"): ("numeric", 14, 2),
    ("stock_reservations", "quantity_reserved"): ("integer",),
    ("stock_reservations", "expires_at"): ("datetime",),
    ("stock_reservations", "released_at"): ("datetime",),
    ("invoice_drafts", "items"): ("json",),
    ("invoice_drafts", "total_amount"): ("numeric", 14, 2),
    ("invoice_drafts", "tax_amount"): ("numeric", 14, 2),
    ("rag_documents", "metadata_json"): ("json",),
    ("rag_chunks", "chunk_index"): ("integer",),
    ("rag_chunks", "embedding"): ("embedding",),
    ("rag_chunks", "metadata_json"): ("json",),
}
for _tenant_table_name in TENANT_TABLES:
    CRITICAL_COLUMN_TYPES[(_tenant_table_name, "installation_id")] = (
        "string",
        128,
    )

RELATIONAL_CLOSURE: tuple[tuple[str, str, str, str, str | None], ...] = (
    (
        "customers",
        "pricelist_id",
        "pricelists",
        "fk_customer_installation_pricelist",
        None,
    ),
    ("quotes", "customer_id", "customers", "fk_quote_installation_customer", None),
    ("orders", "customer_id", "customers", "fk_order_installation_customer", None),
    ("orders", "quote_id", "quotes", "fk_order_installation_quote", None),
    (
        "stock_reservations",
        "order_id",
        "orders",
        "fk_reservation_installation_order",
        None,
    ),
    (
        "stock_reservations",
        "product_id",
        "products",
        "fk_reservation_installation_product",
        None,
    ),
    (
        "invoice_drafts",
        "order_id",
        "orders",
        "fk_invoice_installation_order",
        None,
    ),
    (
        "invoice_drafts",
        "customer_id",
        "customers",
        "fk_invoice_installation_customer",
        None,
    ),
    (
        "conversation_states",
        "customer_id",
        "customers",
        "fk_conversation_installation_customer",
        None,
    ),
    (
        "conversation_states",
        "active_quote_id",
        "quotes",
        "fk_conversation_installation_quote",
        None,
    ),
    (
        "conversation_states",
        "order_id",
        "orders",
        "fk_conversation_installation_order",
        None,
    ),
    (
        "rag_chunks",
        "document_id",
        "rag_documents",
        "fk_rag_chunk_installation_document",
        "CASCADE",
    ),
)

# SQLite cannot rebuild a referenced parent table while FK enforcement is ON.
# Removing outgoing constraints in reverse dependency order first leaves no
# parent referenced during the later safe table rebuilds.
SQLITE_FOREIGN_KEY_DROP_ORDER = (
    "rag_chunks",
    "conversation_states",
    "invoice_drafts",
    "stock_reservations",
    "orders",
    "quotes",
    "customers",
)

_historical_foreign_key_sets: dict[
    str,
    set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]],
] = {}
_final_foreign_key_sets: dict[
    str,
    set[tuple[str, tuple[str, ...], str, tuple[str, ...], str | None]],
] = {}
for (
    _child_table,
    _child_reference,
    _parent_table,
    _foreign_key_name,
    _ondelete,
) in RELATIONAL_CLOSURE:
    _historical_foreign_key_sets.setdefault(_child_table, set()).add(
        ((_child_reference,), _parent_table, ("id",), _ondelete)
    )
    _final_foreign_key_sets.setdefault(_child_table, set()).add(
        (
            _foreign_key_name,
            ("installation_id", _child_reference),
            _parent_table,
            ("installation_id", "id"),
            _ondelete,
        )
    )
HISTORICAL_FOREIGN_KEYS = {
    table_name: frozenset(contracts)
    for table_name, contracts in _historical_foreign_key_sets.items()
}
FINAL_FOREIGN_KEYS = {
    table_name: frozenset(contracts)
    for table_name, contracts in _final_foreign_key_sets.items()
}

CRITICAL_CHECK_CONSTRAINTS: dict[str, dict[str, str]] = {
    "approval_requests": {
        "ck_approval_status": "status IN ('pending','approved','rejected','cancelled','expired','failed')",
    },
    "products": {
        "ck_product_stock_nonnegative": "stock_quantity >= 0",
        "ck_product_reserved_nonnegative": "reserved_stock >= 0",
        "ck_product_reserved_not_above_stock": "reserved_stock <= stock_quantity",
    },
    "quotes": {
        "ck_quote_status": "status IN ('draft','confirmed','cancelled','expired')",
    },
    "stock_reservations": {
        "ck_reservation_quantity_positive": "quantity_reserved > 0",
    },
}
FINAL_RESERVATION_STATUS_CHECK = (
    "ck_reservation_status",
    "status IN ('active','released','expired','cancelled')",
)

HISTORICAL_INDEX_CONTRACTS: dict[
    str,
    dict[str, tuple[tuple[str, ...], frozenset[bool]]],
] = {
    "users": {
        "ix_users_username": (("username",), frozenset({True, False})),
        "ix_users_role": (("role",), frozenset({False})),
        "ix_users_installation_id": (("installation_id",), frozenset({False})),
    },
    "audit_logs": {
        "ix_audit_logs_correlation_id": (("correlation_id",), frozenset({False})),
        "ix_audit_logs_agent_id": (("agent_id",), frozenset({False})),
        "ix_audit_logs_user_id": (("user_id",), frozenset({False})),
        "ix_audit_logs_event_type": (("event_type",), frozenset({False})),
    },
    "idempotency_records": {
        "ix_idempotency_records_created_at": (("created_at",), frozenset({False})),
    },
    "approval_requests": {
        "ix_approval_requests_action_type": (("action_type",), frozenset({False})),
        "ix_approval_requests_target_key": (("target_key",), frozenset({False})),
        "ix_approval_requests_status": (("status",), frozenset({False})),
    },
    "customers": {
        "ix_customers_email": (("email",), frozenset({True, False})),
    },
    "products": {
        "ix_products_external_id": (("external_id",), frozenset({True, False})),
        "ix_products_sku": (("sku",), frozenset({True, False})),
        "ix_products_category": (("category",), frozenset({False})),
    },
    "quotes": {
        "ix_quotes_customer_id": (("customer_id",), frozenset({False})),
        "ix_quotes_account_id": (("account_id",), frozenset({False})),
        "ix_quotes_conversation_id": (("conversation_id",), frozenset({False})),
        "ix_quotes_source_message_id": (("source_message_id",), frozenset({True, False})),
        "ix_quotes_status": (("status",), frozenset({False})),
    },
    "orders": {
        "ix_orders_customer_id": (("customer_id",), frozenset({False})),
        "ix_orders_quote_id": (("quote_id",), frozenset({False})),
    },
    "stock_reservations": {
        "ix_stock_reservations_order_id": (("order_id",), frozenset({False})),
        "ix_stock_reservations_product_id": (("product_id",), frozenset({False})),
    },
    "invoice_drafts": {
        "ix_invoice_drafts_order_id": (("order_id",), frozenset({False})),
        "ix_invoice_drafts_customer_id": (("customer_id",), frozenset({False})),
    },
    "conversation_states": {
        "ix_conversation_states_account_id": (("account_id",), frozenset({False})),
        "ix_conversation_states_conversation_id": (("conversation_id",), frozenset({False})),
    },
    "rag_chunks": {
        "ix_rag_chunks_document_id": (("document_id",), frozenset({False})),
    },
}

FINAL_NON_UNIQUE_INDEXES = {
    "ix_users_username",
    "ix_customers_email",
    "ix_products_external_id",
    "ix_products_sku",
    "ix_quotes_source_message_id",
}

EXPECTED_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    table_name: ("id",) for table_name in HISTORICAL_REQUIRED_COLUMNS
}
EXPECTED_PRIMARY_KEYS["idempotency_records"] = ("idempotency_key",)


def _required_installation_id() -> str:
    raw_value = os.environ.get("INSTALLATION_ID")
    if raw_value is None or not raw_value.strip():
        raise RuntimeError(
            "INSTALLATION_ID explícito es obligatorio para migrar datos históricos"
        )
    installation_id = raw_value.strip()
    if len(installation_id) > 128:
        raise RuntimeError("INSTALLATION_ID no puede superar 128 caracteres")
    return installation_id


def _column_map(table_name: str) -> dict[str, dict[str, object]]:
    return {
        str(column["name"]): column
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _validate_required_tables_and_columns(*, final: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    column_contract = FINAL_REQUIRED_COLUMNS if final else HISTORICAL_REQUIRED_COLUMNS
    missing_tables = [
        table_name for table_name in column_contract if not inspector.has_table(table_name)
    ]
    if missing_tables:
        raise RuntimeError(
            "El esquema 0001 está incompleto; faltan tablas: " + ", ".join(missing_tables)
        )
    for table_name, required_columns in column_contract.items():
        existing_columns = set(_column_map(table_name))
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                f"{table_name} carece de columnas obligatorias: "
                + ", ".join(missing_columns)
            )


def _type_matches(actual_type: object, expected: tuple[object, ...]) -> bool:
    type_family = expected[0]
    if type_family == "string":
        if not isinstance(actual_type, sa.String) or isinstance(actual_type, sa.Text):
            return False
        return len(expected) == 1 or getattr(actual_type, "length", None) == expected[1]
    if type_family == "integer":
        return isinstance(actual_type, sa.Integer) and not isinstance(actual_type, sa.Boolean)
    if type_family == "numeric":
        return (
            isinstance(actual_type, sa.Numeric)
            and not isinstance(actual_type, sa.Float)
            and getattr(actual_type, "precision", None) == expected[1]
            and getattr(actual_type, "scale", None) == expected[2]
        )
    if type_family == "datetime":
        return isinstance(actual_type, sa.DateTime)
    if type_family == "json":
        return isinstance(actual_type, sa.JSON)
    if type_family == "embedding":
        return isinstance(actual_type, sa.JSON) or type(actual_type).__name__.lower() == "vector"
    raise RuntimeError(f"Contrato de tipo desconocido: {type_family}")


def _validate_critical_column_types() -> None:
    for (table_name, column_name), expected_type in CRITICAL_COLUMN_TYPES.items():
        columns = _column_map(table_name)
        if column_name not in columns:
            continue
        actual_type = columns[column_name]["type"]
        if not _type_matches(actual_type, expected_type):
            raise RuntimeError(
                f"{table_name}.{column_name} tiene un tipo incompatible: "
                f"{actual_type}; esperado {expected_type}"
            )


def _foreign_key_core_signature(
    foreign_key: dict[str, object],
) -> tuple[tuple[str, ...], str, tuple[str, ...], str | None]:
    options = foreign_key.get("options") or {}
    ondelete = options.get("ondelete") if isinstance(options, dict) else None
    return (
        tuple(str(column) for column in foreign_key["constrained_columns"]),
        str(foreign_key["referred_table"]),
        tuple(str(column) for column in foreign_key["referred_columns"]),
        str(ondelete).upper() if ondelete else None,
    )


def _foreign_key_final_signature(
    foreign_key: dict[str, object],
) -> tuple[str, tuple[str, ...], str, tuple[str, ...], str | None]:
    local_columns, parent_table, remote_columns, ondelete = (
        _foreign_key_core_signature(foreign_key)
    )
    return (
        str(foreign_key["name"]),
        local_columns,
        parent_table,
        remote_columns,
        ondelete,
    )


def _option_is_true(value: object) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def _foreign_keys_match_final(
    table_name: str,
    actual_foreign_keys: list[dict[str, object]],
) -> bool:
    expected_foreign_keys = FINAL_FOREIGN_KEYS[table_name]
    actual_signatures = frozenset(
        _foreign_key_final_signature(foreign_key)
        for foreign_key in actual_foreign_keys
    )
    if actual_signatures != expected_foreign_keys:
        return False

    # SQLAlchemy exposes these options on PostgreSQL and SQLite.  Some other
    # inspectors omit them; in that case the structural contract is still
    # checked and the database cannot make a false claim about the option.
    for foreign_key in actual_foreign_keys:
        options = foreign_key.get("options") or {}
        if not isinstance(options, dict):
            continue
        if "deferrable" in options and not _option_is_true(options["deferrable"]):
            return False
        if "initially" in options and str(options["initially"]).upper() != "DEFERRED":
            return False
    return True


def _validate_foreign_keys(*, final: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, historical_foreign_keys in HISTORICAL_FOREIGN_KEYS.items():
        actual_foreign_keys = list(inspector.get_foreign_keys(table_name))
        actual_historical_signatures = frozenset(
            _foreign_key_core_signature(foreign_key)
            for foreign_key in actual_foreign_keys
        )
        matches_historical = actual_historical_signatures == historical_foreign_keys
        matches_final = _foreign_keys_match_final(table_name, actual_foreign_keys)
        if (final and not matches_final) or (
            not final and not (matches_historical or matches_final)
        ):
            raise RuntimeError(
                f"{table_name} tiene una definición de foreign key incompatible: "
                f"{actual_foreign_keys!r}"
            )


def _strip_outer_parentheses(expression: str) -> str:
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        wraps_entire_expression = True
        for index, character in enumerate(expression):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(expression) - 1:
                    wraps_entire_expression = False
                    break
        if not wraps_entire_expression:
            break
        expression = expression[1:-1]
    return expression


def _normalize_check_expression(expression: object) -> str:
    normalized = re.sub(r"\s+", "", str(expression).lower())
    normalized = normalized.replace('"', "").replace("`", "")
    return _strip_outer_parentheses(normalized)


def _check_expression_matches(actual: object, expected: str) -> bool:
    actual_normalized = _normalize_check_expression(actual)
    expected_normalized = _normalize_check_expression(expected)
    if actual_normalized == expected_normalized:
        return True

    # PostgreSQL renders IN checks as = ANY(ARRAY[...]) with explicit casts.
    if (
        op.get_bind().dialect.name != "postgresql"
        or "statusin(" not in expected_normalized
    ):
        return False
    expected_values = set(re.findall(r"'([^']+)'", expected.lower()))
    actual_values = set(re.findall(r"'([^']+)'", str(actual).lower()))
    uses_allowed_operator = "statusin(" in actual_normalized or (
        "status" in actual_normalized and "=any(" in actual_normalized
    )
    return (
        "notin" not in actual_normalized
        and "or" not in actual_normalized
        and "and" not in actual_normalized
        and uses_allowed_operator
        and actual_values == expected_values
    )


def _validate_check_constraints(*, final: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, expected_checks in CRITICAL_CHECK_CONSTRAINTS.items():
        actual_checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints(table_name)
        }
        for constraint_name, expected_expression in expected_checks.items():
            if constraint_name not in actual_checks or not _check_expression_matches(
                actual_checks[constraint_name],
                expected_expression,
            ):
                raise RuntimeError(
                    f"{table_name}.{constraint_name} no coincide con la expresión segura"
                )

    status_name, status_expression = FINAL_RESERVATION_STATUS_CHECK
    reservation_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("stock_reservations")
    }
    if final or status_name in reservation_checks:
        if status_name not in reservation_checks or not _check_expression_matches(
            reservation_checks[status_name],
            status_expression,
        ):
            raise RuntimeError(
                f"stock_reservations.{status_name} no coincide con la expresión segura"
            )


def _validate_indexes(*, final: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, expected_indexes in HISTORICAL_INDEX_CONTRACTS.items():
        actual_indexes = {
            str(index["name"]): index for index in inspector.get_indexes(table_name)
        }
        for index_name, (expected_columns, allowed_uniqueness) in expected_indexes.items():
            index = actual_indexes.get(index_name)
            if index is None:
                raise RuntimeError(f"{table_name}.{index_name} no existe")
            actual_columns = tuple(str(column) for column in index["column_names"])
            actual_unique = bool(index["unique"])
            final_allowed_uniqueness = (
                frozenset({False})
                if final and index_name in FINAL_NON_UNIQUE_INDEXES
                else allowed_uniqueness
            )
            if (
                actual_columns != expected_columns
                or actual_unique not in final_allowed_uniqueness
            ):
                raise RuntimeError(
                    f"{table_name}.{index_name} tiene columnas/unique incompatibles: "
                    f"{actual_columns}, unique={actual_unique}"
                )

    for table_name in INSTALLATION_INDEX_TABLES:
        index_name = f"ix_{table_name}_installation_id"
        indexes = {
            str(index["name"]): index for index in inspector.get_indexes(table_name)
        }
        index = indexes.get(index_name)
        if index is None:
            if final:
                raise RuntimeError(f"{table_name}.{index_name} no existe")
            continue
        if tuple(index["column_names"]) != ("installation_id",) or bool(index["unique"]):
            raise RuntimeError(
                f"{table_name}.{index_name} tiene columnas/unique incompatibles"
            )


def _validate_primary_keys(*, final: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, historical_primary_key in EXPECTED_PRIMARY_KEYS.items():
        actual_primary_key = tuple(
            str(column)
            for column in inspector.get_pk_constraint(table_name)["constrained_columns"]
        )
        allowed_primary_keys = {historical_primary_key}
        if table_name == "idempotency_records":
            final_primary_key = ("installation_id", "idempotency_key")
            if final:
                allowed_primary_keys = {final_primary_key}
            else:
                allowed_primary_keys.add(final_primary_key)
        if actual_primary_key not in allowed_primary_keys:
            raise RuntimeError(
                f"{table_name} tiene una primary key incompatible: {actual_primary_key}"
            )


def _validate_named_unique_constraints() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, known_constraints in KNOWN_NAMED_UNIQUE_CONSTRAINTS.items():
        for constraint in inspector.get_unique_constraints(table_name):
            constraint_name = constraint["name"]
            if constraint_name not in known_constraints:
                continue
            actual_columns = tuple(str(column) for column in constraint["column_names"])
            expected_columns = known_constraints[str(constraint_name)]
            if actual_columns != expected_columns:
                raise RuntimeError(
                    f"{table_name}.{constraint_name} tiene columnas de unicidad incompatibles"
                )


def _validate_final_constraints_and_nullability() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, expected_constraints in FINAL_UNIQUE_CONSTRAINTS.items():
        actual_constraints = {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(table_name)
        }
        for expected_constraint in expected_constraints:
            if expected_constraint not in actual_constraints:
                raise RuntimeError(
                    f"{table_name}.{expected_constraint[0]} no coincide con la unicidad final"
                )
        legacy_columns = set(LEGACY_UNIQUE_CONSTRAINTS.get(table_name, ()))
        if any(columns in legacy_columns for _name, columns in actual_constraints):
            raise RuntimeError(f"{table_name} conserva una unicidad legacy incompatible")

    required_non_nullable = {
        (table_name, "installation_id") for table_name in TENANT_TABLES
    } | {
        ("users", "installation_id"),
        ("quotes", "confirmation_payload_hash"),
        ("quotes", "confirmation_expires_at"),
        ("stock_reservations", "expires_at"),
    }
    for table_name, column_name in required_non_nullable:
        if bool(_column_map(table_name)[column_name]["nullable"]):
            raise RuntimeError(f"{table_name}.{column_name} debe ser NOT NULL")

    users_installation_type = _column_map("users")["installation_id"]["type"]
    if not _type_matches(users_installation_type, ("string", 128)):
        raise RuntimeError(
            "users.installation_id debe ser String(128) en el esquema final"
        )


def _validate_schema_contract(*, final: bool) -> None:
    _validate_critical_column_types()
    _validate_foreign_keys(final=final)
    _validate_check_constraints(final=final)
    _validate_indexes(final=final)
    _validate_primary_keys(final=final)
    _validate_named_unique_constraints()
    if final:
        _validate_final_constraints_and_nullability()


def _validate_existing_installation_values(installation_id: str) -> None:
    bind = op.get_bind()
    for table_name in TENANT_TABLES:
        if "installation_id" not in _column_map(table_name):
            continue
        table = sa.table(
            table_name,
            sa.column("installation_id", sa.String(128)),
        )
        existing_values = {
            str(value).strip()
            for value in bind.execute(
                sa.select(table.c.installation_id).distinct().where(
                    table.c.installation_id.is_not(None)
                )
            ).scalars()
            if str(value).strip()
        }
        unexpected_values = existing_values - {installation_id}
        if unexpected_values:
            raise RuntimeError(
                f"{table_name} contiene INSTALLATION_ID ajenos: "
                + ", ".join(sorted(unexpected_values))
            )


def _validate_users_installation_values(installation_id: str) -> None:
    users = sa.table(
        "users",
        sa.column("installation_id", sa.String()),
    )
    bind = op.get_bind()
    row_count = bind.execute(
        sa.select(sa.func.count()).select_from(users)
    ).scalar_one()
    if row_count == 0:
        return

    invalid_count = bind.execute(
        sa.select(sa.func.count())
        .select_from(users)
        .where(
            sa.or_(
                users.c.installation_id.is_(None),
                users.c.installation_id != installation_id,
            )
        )
    ).scalar_one()
    if invalid_count:
        raise RuntimeError(
            "users contiene INSTALLATION_ID inválidos; "
            f"se esperaba exactamente {{{installation_id}}}"
        )


def _effective_installation_expression(
    table: sa.TableClause,
    *,
    has_installation_column: bool,
    installation_id: str,
) -> sa.ColumnElement[object]:
    configured_installation = sa.literal(installation_id, type_=sa.String(128))
    if not has_installation_column:
        return configured_installation
    return sa.func.coalesce(
        sa.func.nullif(sa.func.trim(table.c.installation_id), ""),
        configured_installation,
    )


def _validate_relationship_rows(installation_id: str) -> None:
    """Reject orphaned or cross-installation scalar relationships.

    Before backfill, a missing/blank installation column is evaluated as the
    explicitly configured installation.  The same check is repeated after
    backfill so no composite FK DDL starts with incoherent rows.
    """

    bind = op.get_bind()
    for child_table, child_reference, parent_table, _name, _ondelete in (
        RELATIONAL_CLOSURE
    ):
        child_has_installation = "installation_id" in _column_map(child_table)
        parent_has_installation = "installation_id" in _column_map(parent_table)
        child = sa.table(
            child_table,
            sa.column(child_reference, sa.String()),
            *(
                [sa.column("installation_id", sa.String(128))]
                if child_has_installation
                else []
            ),
        )
        parent = sa.table(
            parent_table,
            sa.column("id", sa.String()),
            *(
                [sa.column("installation_id", sa.String(128))]
                if parent_has_installation
                else []
            ),
        )
        child_installation = _effective_installation_expression(
            child,
            has_installation_column=child_has_installation,
            installation_id=installation_id,
        )
        parent_installation = _effective_installation_expression(
            parent,
            has_installation_column=parent_has_installation,
            installation_id=installation_id,
        )
        relationship_join = sa.and_(
            child.c[child_reference] == parent.c.id,
            child_installation == parent_installation,
        )
        incoherent_rows = bind.execute(
            sa.select(sa.func.count())
            .select_from(child.outerjoin(parent, relationship_join))
            .where(
                child.c[child_reference].is_not(None),
                parent.c.id.is_(None),
            )
        ).scalar_one()
        if incoherent_rows:
            raise RuntimeError(
                f"{child_table}.{child_reference} contiene {incoherent_rows} "
                f"referencias sin padre {parent_table} en la misma instalación"
            )


def _validate_reservation_statuses() -> None:
    columns = _column_map("stock_reservations")
    reservation = sa.table(
        "stock_reservations",
        sa.column("status", sa.String()),
        *(
            [sa.column("expires_at", sa.DateTime())]
            if "expires_at" in columns
            else []
        ),
    )
    bind = op.get_bind()
    existing_statuses = {
        str(value)
        for value in bind.execute(sa.select(reservation.c.status).distinct()).scalars()
    }
    invalid_statuses = existing_statuses - ALLOWED_RESERVATION_STATUSES
    if invalid_statuses:
        raise RuntimeError(
            "stock_reservations contiene estados incompatibles: "
            + ", ".join(sorted(invalid_statuses))
        )

    unmanaged_active_condition = reservation.c.status == "active"
    if "expires_at" in columns:
        unmanaged_active_condition = sa.and_(
            unmanaged_active_condition,
            reservation.c.expires_at.is_(None),
        )
    unmanaged_active_count = bind.execute(
        sa.select(sa.func.count())
        .select_from(reservation)
        .where(unmanaged_active_condition)
    ).scalar_one()
    if unmanaged_active_count:
        raise RuntimeError(
            "stock_reservations contiene reservas activas no gestionadas; "
            "requieren reconciliación explícita"
        )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_map(table_name):
        op.add_column(table_name, column)


def _add_upgrade_columns() -> None:
    for table_name in TENANT_TABLES:
        _add_column_if_missing(
            table_name,
            sa.Column("installation_id", sa.String(128), nullable=True),
        )

    _add_column_if_missing(
        "quotes",
        sa.Column("confirmation_payload_hash", sa.String(64), nullable=True),
    )
    _add_column_if_missing(
        "quotes",
        sa.Column("confirmation_expires_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "quotes",
        sa.Column("confirmation_consumed_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "quotes",
        sa.Column("confirmed_by", sa.String(255), nullable=True),
    )
    _add_column_if_missing(
        "stock_reservations",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "stock_reservations",
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )


def _backfill_installation_ids(installation_id: str) -> None:
    bind = op.get_bind()
    for table_name in TENANT_TABLES:
        table = sa.table(
            table_name,
            sa.column("installation_id", sa.String(128)),
        )
        bind.execute(
            table.update()
            .where(
                sa.or_(
                    table.c.installation_id.is_(None),
                    sa.func.trim(table.c.installation_id) == "",
                    sa.func.trim(table.c.installation_id) == installation_id,
                )
            )
            .values(installation_id=installation_id)
        )
        remaining = bind.execute(
            sa.select(sa.func.count())
            .select_from(table)
            .where(
                sa.or_(
                    table.c.installation_id.is_(None),
                    table.c.installation_id != installation_id,
                )
            )
        ).scalar_one()
        if remaining:
            raise RuntimeError(f"No se pudo aislar completamente la tabla {table_name}")


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _confirmation_payload_hash(row: sa.RowMapping) -> str:
    canonical = json.dumps(
        {
            "customer_id": row["customer_id"],
            "items": _json_value(row["items"]),
            "subtotal": str(_money(row["subtotal"])),
            "tax_total": str(_money(row["tax_total"])),
            "shipping_total": str(_money(row["shipping_total"])),
            "grand_total": str(_money(row["grand_total"])),
            "currency": row["currency"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_legacy_token(token: object) -> str:
    normalized = str(token).strip()
    if len(normalized) == 64 and all(character in string.hexdigits for character in normalized):
        return normalized.lower()
    return hashlib.sha256(normalized.upper().encode("utf-8")).hexdigest()


def _as_datetime(value: object) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _backfill_quotes() -> None:
    bind = op.get_bind()
    quote = sa.table(
        "quotes",
        sa.column("id", sa.String()),
        sa.column("customer_id", sa.String()),
        sa.column("confirmation_token", sa.String()),
        sa.column("confirmation_payload_hash", sa.String(64)),
        sa.column("confirmation_expires_at", sa.DateTime()),
        sa.column("confirmation_consumed_at", sa.DateTime()),
        sa.column("items", sa.JSON()),
        sa.column("subtotal", sa.Numeric(14, 2)),
        sa.column("tax_total", sa.Numeric(14, 2)),
        sa.column("shipping_total", sa.Numeric(14, 2)),
        sa.column("grand_total", sa.Numeric(14, 2)),
        sa.column("currency", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("confirmed_at", sa.DateTime()),
    )
    rows = bind.execute(sa.select(quote)).mappings().all()
    for row in rows:
        created_at = _as_datetime(row["created_at"])
        values: dict[str, object] = {
            "confirmation_token": _hash_legacy_token(row["confirmation_token"]),
        }
        if not row["confirmation_payload_hash"]:
            values["confirmation_payload_hash"] = _confirmation_payload_hash(row)
        if row["confirmation_expires_at"] is None:
            # Historical confirmation tokens are expired during adoption.  This
            # prevents a pre-state-machine token from authorising new effects.
            values["confirmation_expires_at"] = created_at
        if row["status"] == "confirmed" and row["confirmation_consumed_at"] is None:
            values["confirmation_consumed_at"] = row["confirmed_at"] or created_at
        bind.execute(quote.update().where(quote.c.id == row["id"]).values(**values))


def _backfill_reservations() -> None:
    bind = op.get_bind()
    reservation = sa.table(
        "stock_reservations",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("expires_at", sa.DateTime()),
        sa.column("released_at", sa.DateTime()),
    )
    rows = bind.execute(sa.select(reservation)).mappings().all()
    for row in rows:
        created_at = _as_datetime(row["created_at"])
        values: dict[str, object] = {}
        if row["expires_at"] is None:
            values["expires_at"] = created_at + LEGACY_RESERVATION_TTL
        if row["status"] != "active" and row["released_at"] is None:
            values["released_at"] = created_at
        if values:
            bind.execute(
                reservation.update().where(reservation.c.id == row["id"]).values(**values)
            )


def _unnamed_unique_name(table_name: str, columns: tuple[str, ...]) -> str:
    return f"uq_{table_name}_{columns[0]}"


def _unique_constraints(table_name: str) -> list[dict[str, object]]:
    return list(sa.inspect(op.get_bind()).get_unique_constraints(table_name))


def _matching_unique_names(table_name: str, columns: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for constraint in _unique_constraints(table_name):
        if tuple(constraint["column_names"]) != columns:
            continue
        name = constraint["name"] or _unnamed_unique_name(table_name, columns)
        names.append(str(name))
    return names


def _has_unique_constraint(table_name: str, name: str, columns: tuple[str, ...]) -> bool:
    return any(
        constraint["name"] == name and tuple(constraint["column_names"]) == columns
        for constraint in _unique_constraints(table_name)
    )


def _migrate_table_shape(
    table_name: str,
    *,
    non_nullable_columns: tuple[str, ...] = ("installation_id",),
    type_changes: tuple[
        tuple[str, object, tuple[object, ...]],
        ...,
    ] = (),
    composite_primary_key: tuple[str, ...] | None = None,
    add_reservation_status_check: bool = False,
) -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {str(column["name"]): column for column in inspector.get_columns(table_name)}
    nullable_columns = [
        column_name
        for column_name in non_nullable_columns
        if bool(columns[column_name]["nullable"])
    ]
    pending_type_changes = [
        (column_name, final_type)
        for column_name, final_type, final_contract in type_changes
        if not _type_matches(columns[column_name]["type"], final_contract)
    ]
    legacy_constraint_names = [
        constraint_name
        for constraint_columns in LEGACY_UNIQUE_CONSTRAINTS.get(table_name, ())
        for constraint_name in _matching_unique_names(table_name, constraint_columns)
    ]
    missing_final_constraints = [
        (constraint_name, constraint_columns)
        for constraint_name, constraint_columns in FINAL_UNIQUE_CONSTRAINTS.get(table_name, ())
        if not _has_unique_constraint(table_name, constraint_name, constraint_columns)
    ]

    primary_key_change: tuple[str, tuple[str, ...]] | None = None
    if composite_primary_key is not None:
        existing_primary_key = inspector.get_pk_constraint(table_name)
        existing_columns = tuple(existing_primary_key["constrained_columns"])
        if existing_columns != composite_primary_key:
            existing_name = existing_primary_key["name"] or f"pk_{table_name}"
            primary_key_change = (str(existing_name), composite_primary_key)

    check_constraint_missing = False
    if add_reservation_status_check:
        check_constraint_missing = not any(
            constraint["name"] == "ck_reservation_status"
            for constraint in inspector.get_check_constraints(table_name)
        )

    if not any(
        (
            nullable_columns,
            pending_type_changes,
            legacy_constraint_names,
            missing_final_constraints,
            primary_key_change,
            check_constraint_missing,
        )
    ):
        return

    with op.batch_alter_table(
        table_name,
        naming_convention=BATCH_NAMING_CONVENTION,
    ) as batch_op:
        type_change_columns = {
            column_name for column_name, _final_type in pending_type_changes
        }
        for column_name in set(nullable_columns) - type_change_columns:
            batch_op.alter_column(
                column_name,
                existing_type=columns[column_name]["type"],
                nullable=False,
            )
        for column_name, final_type in pending_type_changes:
            batch_op.alter_column(
                column_name,
                existing_type=columns[column_name]["type"],
                type_=final_type,
                nullable=(
                    False
                    if column_name in nullable_columns
                    else bool(columns[column_name]["nullable"])
                ),
            )
        for constraint_name, constraint_columns in missing_final_constraints:
            batch_op.create_unique_constraint(constraint_name, list(constraint_columns))
        for constraint_name in legacy_constraint_names:
            batch_op.drop_constraint(constraint_name, type_="unique")
        if primary_key_change is not None:
            existing_name, final_columns = primary_key_change
            batch_op.drop_constraint(existing_name, type_="primary")
            batch_op.create_primary_key(f"pk_{table_name}", list(final_columns))
        if check_constraint_missing:
            batch_op.create_check_constraint(
                "ck_reservation_status",
                "status IN ('active','released','expired','cancelled')",
            )


def _ensure_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = sa.inspect(op.get_bind())
    existing_index = next(
        (index for index in inspector.get_indexes(table_name) if index["name"] == index_name),
        None,
    )
    if existing_index is not None and bool(existing_index["unique"]) != unique:
        op.drop_index(index_name, table_name=table_name)
        existing_index = None
    if existing_index is None:
        op.create_index(index_name, table_name, columns, unique=unique)


def _migrate_constraints_and_nullability() -> None:
    _migrate_table_shape(
        "users",
        non_nullable_columns=(),
        type_changes=(
            ("installation_id", sa.String(128), ("string", 128)),
        ),
    )
    _migrate_table_shape("audit_logs")
    _migrate_table_shape(
        "idempotency_records",
        composite_primary_key=("installation_id", "idempotency_key"),
    )
    _migrate_table_shape("approval_requests")
    _migrate_table_shape("pricelists")
    _migrate_table_shape("customers")
    _migrate_table_shape("products")
    _migrate_table_shape(
        "quotes",
        non_nullable_columns=(
            "installation_id",
            "confirmation_payload_hash",
            "confirmation_expires_at",
        ),
    )
    _migrate_table_shape("orders")
    _migrate_table_shape(
        "stock_reservations",
        non_nullable_columns=("installation_id", "expires_at"),
        add_reservation_status_check=True,
    )
    _migrate_table_shape("invoice_drafts")
    _migrate_table_shape("conversation_states")
    _migrate_table_shape("rag_documents")
    _migrate_table_shape("rag_chunks")


def _reflected_foreign_key_name(
    table_name: str,
    foreign_key: dict[str, object],
) -> str:
    reflected_name = foreign_key.get("name")
    if reflected_name:
        return str(reflected_name)
    first_column = str(foreign_key["constrained_columns"][0])
    parent_table = str(foreign_key["referred_table"])
    return f"fk_{table_name}_{first_column}_{parent_table}"


def _stage_sqlite_foreign_keys() -> frozenset[str]:
    if op.get_bind().dialect.name != "sqlite":
        return frozenset()

    reflected_foreign_keys = {
        table_name: list(sa.inspect(op.get_bind()).get_foreign_keys(table_name))
        for table_name in HISTORICAL_FOREIGN_KEYS
    }
    if all(
        _foreign_keys_match_final(table_name, foreign_keys)
        for table_name, foreign_keys in reflected_foreign_keys.items()
    ):
        return frozenset()

    staged_tables: set[str] = set()
    for table_name in SQLITE_FOREIGN_KEY_DROP_ORDER:
        foreign_keys = list(
            sa.inspect(op.get_bind()).get_foreign_keys(table_name)
        )
        if not foreign_keys:
            continue
        with op.batch_alter_table(
            table_name,
            naming_convention=BATCH_NAMING_CONVENTION,
        ) as batch_op:
            for foreign_key in foreign_keys:
                batch_op.drop_constraint(
                    _reflected_foreign_key_name(table_name, foreign_key),
                    type_="foreignkey",
                )
        staged_tables.add(table_name)
    return frozenset(staged_tables)


def _migrate_composite_foreign_keys(
    *,
    staged_tables: frozenset[str] = frozenset(),
) -> None:
    for table_name, historical_contract in HISTORICAL_FOREIGN_KEYS.items():
        actual_foreign_keys = list(
            sa.inspect(op.get_bind()).get_foreign_keys(table_name)
        )
        if _foreign_keys_match_final(table_name, actual_foreign_keys):
            continue
        actual_historical_contract = frozenset(
            _foreign_key_core_signature(foreign_key)
            for foreign_key in actual_foreign_keys
        )
        was_safely_staged = table_name in staged_tables and not actual_foreign_keys
        if actual_historical_contract != historical_contract and not was_safely_staged:
            raise RuntimeError(
                f"{table_name} cambió sus foreign keys durante la migración"
            )

        with op.batch_alter_table(
            table_name,
            naming_convention=BATCH_NAMING_CONVENTION,
        ) as batch_op:
            for foreign_key in actual_foreign_keys:
                batch_op.drop_constraint(
                    _reflected_foreign_key_name(table_name, foreign_key),
                    type_="foreignkey",
                )
            for (
                child_table,
                child_reference,
                parent_table,
                foreign_key_name,
                ondelete,
            ) in RELATIONAL_CLOSURE:
                if child_table != table_name:
                    continue
                batch_op.create_foreign_key(
                    foreign_key_name,
                    parent_table,
                    ["installation_id", child_reference],
                    ["installation_id", "id"],
                    ondelete=ondelete,
                    deferrable=True,
                    initially="DEFERRED",
                )


def _migrate_indexes() -> None:
    for table_name in INSTALLATION_INDEX_TABLES:
        _ensure_index(
            f"ix_{table_name}_installation_id",
            table_name,
            ["installation_id"],
        )
    _ensure_index("ix_customers_email", "customers", ["email"])
    _ensure_index("ix_products_external_id", "products", ["external_id"])
    _ensure_index("ix_products_sku", "products", ["sku"])
    _ensure_index("ix_quotes_source_message_id", "quotes", ["source_message_id"])
    _ensure_index("ix_users_username", "users", ["username"])


def _validate_database_foreign_key_integrity() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        raise RuntimeError(
            "SQLite detectó relaciones inválidas tras la migración: "
            f"{violations!r}"
        )


def upgrade() -> None:
    installation_id = _required_installation_id()
    _validate_required_tables_and_columns(final=False)
    _validate_users_installation_values(installation_id)
    _validate_existing_installation_values(installation_id)
    _validate_reservation_statuses()
    _validate_relationship_rows(installation_id)
    _validate_schema_contract(final=False)

    _add_upgrade_columns()
    _backfill_installation_ids(installation_id)
    _validate_relationship_rows(installation_id)
    _backfill_quotes()
    _backfill_reservations()
    staged_foreign_keys = _stage_sqlite_foreign_keys()
    _migrate_constraints_and_nullability()
    _migrate_composite_foreign_keys(staged_tables=staged_foreign_keys)
    _migrate_indexes()

    _validate_required_tables_and_columns(final=True)
    _validate_users_installation_values(installation_id)
    _validate_existing_installation_values(installation_id)
    _validate_reservation_statuses()
    _validate_relationship_rows(installation_id)
    _validate_schema_contract(final=True)
    _validate_database_foreign_key_integrity()


def downgrade() -> None:
    # Schema-compatible downgrade: tenant ownership and relational closure are
    # retained because removing either would re-enable cross-installation data
    # mixing and discard audit-relevant confirmation state.
    pass
