import datetime
import uuid
from collections.abc import Mapping

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import Session, declared_attr, relationship, with_loader_criteria

from app.config import settings
from app.database import Base
from app.installation_context import (
    InstallationContextError,
    get_current_installation_id,
    validate_installation_id,
)

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # SQLite/tests or minimal development environment
    Vector = None


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def embedding_column_type():
    if Vector is None:
        return JSON
    return Vector(settings.EMBEDDING_DIMENSION).with_variant(JSON, "sqlite")


def generate_uuid() -> str:
    return str(uuid.uuid4())


def stock_reservation_expires_at() -> datetime.datetime:
    return utcnow() + datetime.timedelta(seconds=settings.STOCK_RESERVATION_TTL_SEC)


class InstallationOwnedMixin:
    """Marks rows that must stay inside one installation boundary."""

    @declared_attr
    def installation_id(cls):
        return Column(
            String(128),
            nullable=False,
            index=True,
            default=get_current_installation_id,
        )


class User(InstallationOwnedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "username",
            name="uq_user_installation_username",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer", index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AuditLog(InstallationOwnedMixin, Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=utcnow, nullable=False)
    correlation_id = Column(String, index=True)
    agent_id = Column(String, index=True)
    user_id = Column(String, index=True, nullable=True)
    event_type = Column(String, index=True)
    provider = Column(String)
    model_name = Column(String)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Float, default=0.0, nullable=False)
    estimated_cost_usd = Column(Numeric(14, 6), default=0, nullable=False)
    status = Column(String, nullable=False)
    details = Column(JSON, nullable=True)


class IdempotencyRecord(InstallationOwnedMixin, Base):
    __tablename__ = "idempotency_records"

    installation_id = Column(
        String(128),
        primary_key=True,
        nullable=False,
        default=get_current_installation_id,
    )
    idempotency_key = Column(String, primary_key=True)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    response_body = Column(JSON, nullable=True)
    status_code = Column(Integer, default=200, nullable=False)


class ApprovalRequest(InstallationOwnedMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "action_type",
            "target_key",
            name="uq_approval_installation_action_target",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled','expired','failed')",
            name="ck_approval_status",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    action_type = Column(String, index=True, nullable=False)
    target_key = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    requested_by = Column(String, nullable=True)
    status = Column(String, default="pending", nullable=False, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)

    @property
    def target_id(self) -> str:
        return self.target_key


class Customer(InstallationOwnedMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "email",
            name="uq_customer_installation_email",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_customer_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "pricelist_id"],
            ["pricelists.installation_id", "pricelists.id"],
            name="fk_customer_installation_pricelist",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, index=True, nullable=False)
    phone = Column(String, nullable=True)
    company = Column(String, nullable=True)
    pricelist_id = Column(String, nullable=True)
    tax_exempt = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    pricelist = relationship("Pricelist", lazy="joined")

    @property
    def discount_percentage(self) -> float:
        return float(self.pricelist.discount_percentage) if self.pricelist else 0.0

    @property
    def is_tax_exempt(self) -> bool:
        return bool(self.tax_exempt)


class Product(InstallationOwnedMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "external_id",
            name="uq_product_installation_external_id",
        ),
        UniqueConstraint(
            "installation_id",
            "sku",
            name="uq_product_installation_sku",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_product_installation_id",
        ),
        CheckConstraint("stock_quantity >= 0", name="ck_product_stock_nonnegative"),
        CheckConstraint("reserved_stock >= 0", name="ck_product_reserved_nonnegative"),
        CheckConstraint("reserved_stock <= stock_quantity", name="ck_product_reserved_not_above_stock"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    external_id = Column(String, nullable=True, index=True)
    sku = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, index=True)
    attributes = Column(JSON, nullable=True)
    source = Column(String, default="local", nullable=False)
    source_url = Column(String, nullable=True)
    base_price = Column(Numeric(14, 4), nullable=False)
    tax_rate = Column(Numeric(7, 6), default=0.21, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)
    reserved_stock = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @property
    def unit_price(self) -> float:
        return float(self.base_price)

    @property
    def available_stock(self) -> int:
        return max(0, int(self.stock_quantity) - int(self.reserved_stock))


class Pricelist(InstallationOwnedMixin, Base):
    __tablename__ = "pricelists"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_pricelist_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    discount_percentage = Column(Numeric(7, 4), default=0, nullable=False)


class Quote(InstallationOwnedMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "confirmation_token",
            name="uq_quote_installation_confirmation_token",
        ),
        UniqueConstraint(
            "installation_id",
            "source_message_id",
            name="uq_quote_installation_source_message",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_quote_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_quote_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("status IN ('draft','confirmed','cancelled','expired')", name="ck_quote_status"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False, index=True)
    account_id = Column(String, nullable=True, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    confirmation_token = Column(String, nullable=False)
    confirmation_payload_hash = Column(String(64), nullable=False)
    confirmation_expires_at = Column(DateTime, nullable=False)
    confirmation_consumed_at = Column(DateTime, nullable=True)
    confirmed_by = Column(String(255), nullable=True)
    source_message_id = Column(String, nullable=True, index=True)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)


class Order(InstallationOwnedMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "quote_id",
            name="uq_order_installation_quote_id",
        ),
        UniqueConstraint(
            "installation_id",
            "idempotency_key",
            name="uq_order_installation_idempotency_key",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_order_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_order_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "quote_id"],
            ["quotes.installation_id", "quotes.id"],
            name="fk_order_installation_quote",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False, index=True)
    quote_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="confirmed", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class StockReservation(InstallationOwnedMixin, Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "order_id",
            "product_id",
            name="uq_reservation_installation_order_product",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_reservation_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "product_id"],
            ["products.installation_id", "products.id"],
            name="fk_reservation_installation_product",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("quantity_reserved > 0", name="ck_reservation_quantity_positive"),
        CheckConstraint(
            "status IN ('active','released','expired','cancelled')",
            name="ck_reservation_status",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    order_id = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=False, index=True)
    quantity_reserved = Column(Integer, nullable=False)
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, default=stock_reservation_expires_at, nullable=False)
    released_at = Column(DateTime, nullable=True)


class InvoiceDraft(InstallationOwnedMixin, Base):
    __tablename__ = "invoice_drafts"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "order_id",
            name="uq_invoice_installation_order_id",
        ),
        UniqueConstraint(
            "installation_id",
            "invoice_number",
            name="uq_invoice_installation_number",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_invoice_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_invoice_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    invoice_number = Column(String, nullable=False)
    order_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    items = Column(JSON, nullable=False)
    total_amount = Column(Numeric(14, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(14, 2), default=0, nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    @property
    def amount(self) -> float:
        return float(self.total_amount)


class ConversationState(InstallationOwnedMixin, Base):
    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "account_id",
            "conversation_id",
            name="uq_conversation_installation_account",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_conversation_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "active_quote_id"],
            ["quotes.installation_id", "quotes.id"],
            name="fk_conversation_installation_quote",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_conversation_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=True)
    active_quote_id = Column(String, nullable=True)
    order_id = Column(String, nullable=True)
    state = Column(String, default="idle", nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class RAGDocument(InstallationOwnedMixin, Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "sha256",
            name="uq_rag_document_installation_sha256",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_rag_document_installation_id",
        ),
    )

    id = Column(String, primary_key=True)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    sha256 = Column(String, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RAGChunk(InstallationOwnedMixin, Base):
    __tablename__ = "rag_chunks"

    id = Column(String, primary_key=True)
    document_id = Column(String, nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(embedding_column_type(), nullable=False)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "document_id",
            "chunk_index",
            name="uq_rag_chunk_installation_document_index",
        ),
        ForeignKeyConstraint(
            ["installation_id", "document_id"],
            ["rag_documents.installation_id", "rag_documents.id"],
            name="fk_rag_chunk_installation_document",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


def _installation_owned_instances(session: Session):
    """Return rows whose pending lifecycle operation crosses the tenant boundary."""

    seen: set[int] = set()
    for collection in (session.new, session.dirty, session.deleted):
        for instance in collection:
            identity = id(instance)
            if identity in seen or not isinstance(instance, InstallationOwnedMixin):
                continue
            seen.add(identity)
            yield instance


@event.listens_for(Session, "before_flush")
def enforce_installation_on_flush(session, _flush_context, _instances) -> None:
    """Populate the active installation and reject cross-installation writes."""

    owned_instances = tuple(_installation_owned_instances(session))
    if not owned_instances:
        return

    current_installation_id = get_current_installation_id()
    for instance in owned_instances:
        is_new = instance in session.new
        instance_installation_id = instance.installation_id
        if instance_installation_id is None:
            if is_new:
                instance.installation_id = current_installation_id
                sa_inspect(instance).identity_token = current_installation_id
                continue
            raise InstallationContextError(
                f"{type(instance).__name__} no tiene installation_id"
            )

        normalized_installation_id = validate_installation_id(instance_installation_id)
        if normalized_installation_id != current_installation_id:
            raise InstallationContextError(
                "Operación entre instalaciones rechazada: "
                f"contexto={current_installation_id}, registro={normalized_installation_id}"
            )
        instance.installation_id = normalized_installation_id
        if is_new:
            # Keep identity-map keys tenant-aware. Otherwise Session.get() can
            # return an object cached under a previous installation without SQL.
            sa_inspect(instance).identity_token = current_installation_id


def _validate_bulk_installation_parameters(parameters, current_installation_id: str) -> None:
    if parameters is None:
        return

    parameter_sets = (parameters,) if isinstance(parameters, Mapping) else parameters
    for parameter_values in parameter_sets:
        if not isinstance(parameter_values, Mapping) or "installation_id" not in parameter_values:
            continue
        supplied_installation_id = validate_installation_id(parameter_values["installation_id"])
        if supplied_installation_id != current_installation_id:
            raise InstallationContextError(
                "Operación masiva entre instalaciones rechazada: "
                f"contexto={current_installation_id}, registro={supplied_installation_id}"
            )


@event.listens_for(Session, "do_orm_execute")
def scope_installation_orm_operations(execute_state) -> None:
    """Apply deny-by-default installation criteria to ORM reads and bulk writes."""

    if not execute_state.is_orm_statement:
        return

    if execute_state.is_select:
        current_installation_id = get_current_installation_id()
        execute_state.update_execution_options(
            identity_token=current_installation_id,
        )
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                InstallationOwnedMixin,
                lambda model: model.installation_id == current_installation_id,
                include_aliases=True,
            )
        )
        return

    mapper = execute_state.bind_mapper
    if mapper is None or not issubclass(mapper.class_, InstallationOwnedMixin):
        return

    current_installation_id = get_current_installation_id()
    if execute_state.is_insert:
        _validate_bulk_installation_parameters(
            execute_state.parameters,
            current_installation_id,
        )
        execute_state.statement = execute_state.statement.values(
            installation_id=current_installation_id
        )
        return

    if not (execute_state.is_update or execute_state.is_delete):
        return

    execute_state.statement = execute_state.statement.where(
        mapper.class_.installation_id == current_installation_id
    )
    if execute_state.is_update:
        _validate_bulk_installation_parameters(
            execute_state.parameters,
            current_installation_id,
        )
        execute_state.statement = execute_state.statement.values(
            installation_id=current_installation_id
        )
