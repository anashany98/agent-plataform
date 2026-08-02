import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.config import settings
from app.database import Base

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


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer", index=True)
    installation_id = Column(String, nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AuditLog(Base):
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


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idempotency_key = Column(String, primary_key=True)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    response_body = Column(JSON, nullable=True)
    status_code = Column(Integer, default=200, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("action_type", "target_key", name="uq_approval_action_target"),
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


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    company = Column(String, nullable=True)
    pricelist_id = Column(String, ForeignKey("pricelists.id"), nullable=True)
    tax_exempt = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    pricelist = relationship("Pricelist", lazy="joined")

    @property
    def discount_percentage(self) -> float:
        return float(self.pricelist.discount_percentage) if self.pricelist else 0.0

    @property
    def is_tax_exempt(self) -> bool:
        return bool(self.tax_exempt)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_product_stock_nonnegative"),
        CheckConstraint("reserved_stock >= 0", name="ck_product_reserved_nonnegative"),
        CheckConstraint("reserved_stock <= stock_quantity", name="ck_product_reserved_not_above_stock"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    external_id = Column(String, nullable=True, unique=True, index=True)
    sku = Column(String, unique=True, index=True, nullable=False)
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


class Pricelist(Base):
    __tablename__ = "pricelists"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    discount_percentage = Column(Numeric(7, 4), default=0, nullable=False)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("confirmation_token", name="uq_quote_confirmation_token"),
        CheckConstraint("status IN ('draft','confirmed','cancelled','expired')", name="ck_quote_status"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    account_id = Column(String, nullable=True, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    confirmation_token = Column(String, nullable=False, unique=True)
    source_message_id = Column(String, nullable=True, unique=True, index=True)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("quote_id", name="uq_order_quote_id"),
        UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    quote_id = Column(String, ForeignKey("quotes.id"), nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="confirmed", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class StockReservation(Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_reservation_order_product"),
        CheckConstraint("quantity_reserved > 0", name="ck_reservation_quantity_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(String, ForeignKey("products.id"), nullable=False, index=True)
    quantity_reserved = Column(Integer, nullable=False)
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class InvoiceDraft(Base):
    __tablename__ = "invoice_drafts"
    __table_args__ = (UniqueConstraint("order_id", name="uq_invoice_order_id"),)

    id = Column(String, primary_key=True, default=generate_uuid)
    invoice_number = Column(String, unique=True, nullable=False)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    items = Column(JSON, nullable=False)
    total_amount = Column(Numeric(14, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(14, 2), default=0, nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    @property
    def amount(self) -> float:
        return float(self.total_amount)


class ConversationState(Base):
    __tablename__ = "conversation_states"
    __table_args__ = (UniqueConstraint("account_id", "conversation_id", name="uq_conversation_account"),)

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    active_quote_id = Column(String, ForeignKey("quotes.id"), nullable=True)
    order_id = Column(String, ForeignKey("orders.id"), nullable=True)
    state = Column(String, default="idle", nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class RAGDocument(Base):
    __tablename__ = "rag_documents"

    id = Column(String, primary_key=True)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    sha256 = Column(String, nullable=False, unique=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RAGChunk(Base):
    __tablename__ = "rag_chunks"

    id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(embedding_column_type(), nullable=False)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_rag_doc_chunk"),)
