import datetime
from decimal import Decimal

import pytest
from app.config import settings
from app.database import Base
from app.installation_context import InstallationContextError, installation_scope
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    ConversationState,
    Customer,
    IdempotencyRecord,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    RAGChunk,
    RAGDocument,
    StockReservation,
    User,
)
from sqlalchemy import create_engine, event, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

TENANT_OWNED_MODELS = (
    ApprovalRequest,
    AuditLog,
    ConversationState,
    Customer,
    IdempotencyRecord,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    RAGChunk,
    RAGDocument,
    StockReservation,
    User,
)

SCALAR_ID_MODELS = tuple(model for model in TENANT_OWNED_MODELS if model is not IdempotencyRecord)


@pytest.fixture
def isolated_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _insert_installation_graph(factory, installation_id: str, suffix: str) -> dict[type, str]:
    identifiers = {
        ApprovalRequest: f"approval-{suffix}",
        AuditLog: f"audit-{suffix}",
        ConversationState: f"conversation-state-{suffix}",
        Customer: f"customer-{suffix}",
        InvoiceDraft: f"invoice-{suffix}",
        Order: f"order-{suffix}",
        Pricelist: f"pricelist-{suffix}",
        Product: f"product-{suffix}",
        Quote: f"quote-{suffix}",
        RAGChunk: f"chunk-{suffix}",
        RAGDocument: f"document-{suffix}",
        StockReservation: f"reservation-{suffix}",
        User: f"user-{suffix}",
    }
    expiration = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(hours=1)

    with installation_scope(installation_id):
        session = factory()
        try:
            session.add_all(
                [
                    User(
                        id=identifiers[User],
                        username="shared-user",
                        password_hash=f"hash-{suffix}",
                    ),
                    Pricelist(
                        id=identifiers[Pricelist],
                        name=f"Pricelist {suffix}",
                        discount_percentage=Decimal("7.50"),
                    ),
                    Product(
                        id=identifiers[Product],
                        external_id="external-shared",
                        sku="SKU-SHARED",
                        name=f"Product {suffix}",
                        base_price=Decimal("10.00"),
                        tax_rate=Decimal("0.21"),
                        stock_quantity=10,
                    ),
                    ApprovalRequest(
                        id=identifiers[ApprovalRequest],
                        action_type="issue_invoice",
                        target_key="target-shared",
                        payload={},
                    ),
                    AuditLog(
                        id=identifiers[AuditLog],
                        correlation_id="correlation-shared",
                        event_type="tenant_isolation_test",
                        status="success",
                    ),
                    IdempotencyRecord(
                        idempotency_key="webhook-key-shared",
                        response_body={"tenant": installation_id},
                    ),
                ]
            )
            session.flush()

            session.add(
                Customer(
                    id=identifiers[Customer],
                    name=f"Customer {suffix}",
                    email="shared@example.test",
                    pricelist_id=identifiers[Pricelist],
                )
            )
            session.flush()

            session.add_all(
                [
                    Quote(
                        id=identifiers[Quote],
                        customer_id=identifiers[Customer],
                        confirmation_token="a" * 64,
                        confirmation_payload_hash="b" * 64,
                        confirmation_expires_at=expiration,
                        source_message_id="source-message-shared",
                        items=[],
                        subtotal=Decimal("0.00"),
                        tax_total=Decimal("0.00"),
                        shipping_total=Decimal("0.00"),
                        grand_total=Decimal("0.00"),
                    ),
                    RAGDocument(
                        id=identifiers[RAGDocument],
                        file_path=f"/{suffix}.txt",
                        file_name=f"{suffix}.txt",
                        sha256="c" * 64,
                    ),
                ]
            )
            session.flush()

            session.add_all(
                [
                    Order(
                        id=identifiers[Order],
                        customer_id=identifiers[Customer],
                        quote_id=identifiers[Quote],
                        idempotency_key="order-key-shared",
                        items=[],
                        subtotal=Decimal("0.00"),
                        tax_total=Decimal("0.00"),
                        shipping_total=Decimal("0.00"),
                        grand_total=Decimal("0.00"),
                    ),
                    RAGChunk(
                        id=identifiers[RAGChunk],
                        document_id=identifiers[RAGDocument],
                        chunk_index=0,
                        text=f"private content {suffix}",
                        embedding=[0.0],
                    ),
                ]
            )
            session.flush()

            session.add_all(
                [
                    StockReservation(
                        id=identifiers[StockReservation],
                        order_id=identifiers[Order],
                        product_id=identifiers[Product],
                        quantity_reserved=1,
                        expires_at=expiration,
                    ),
                    InvoiceDraft(
                        id=identifiers[InvoiceDraft],
                        invoice_number="DRAFT-SHARED",
                        order_id=identifiers[Order],
                        customer_id=identifiers[Customer],
                        items=[],
                    ),
                    ConversationState(
                        id=identifiers[ConversationState],
                        account_id="account-shared",
                        conversation_id="conversation-shared",
                        customer_id=identifiers[Customer],
                        active_quote_id=identifiers[Quote],
                        order_id=identifiers[Order],
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

    return identifiers


def test_all_tenant_owned_models_require_a_non_nullable_installation_id():
    for model in TENANT_OWNED_MODELS:
        installation_column = model.__table__.columns["installation_id"]
        assert installation_column.nullable is False, model.__tablename__


def test_repository_reads_and_id_lookups_cannot_enumerate_another_installation(
    isolated_session_factory,
):
    tenant_a_ids = _insert_installation_graph(isolated_session_factory, "tenant-a", "a")
    tenant_b_ids = _insert_installation_graph(isolated_session_factory, "tenant-b", "b")

    for current_tenant, expected_ids, foreign_ids in (
        ("tenant-a", tenant_a_ids, tenant_b_ids),
        ("tenant-b", tenant_b_ids, tenant_a_ids),
    ):
        with installation_scope(current_tenant):
            session = isolated_session_factory()
            try:
                for model in TENANT_OWNED_MODELS:
                    rows = session.query(model).all()
                    assert len(rows) == 1, model.__tablename__
                    assert rows[0].installation_id == current_tenant
                    if model is not IdempotencyRecord:
                        assert rows[0].id == expected_ids[model]
                    if model is Customer:
                        assert rows[0].pricelist.installation_id == current_tenant

                for model in SCALAR_ID_MODELS:
                    assert session.get(model, foreign_ids[model]) is None, model.__tablename__

                assert (
                    session.get(
                        IdempotencyRecord,
                        ("tenant-b" if current_tenant == "tenant-a" else "tenant-a", "webhook-key-shared"),
                    )
                    is None
                )
                own_idempotency = session.query(IdempotencyRecord).one()
                assert own_idempotency.response_body == {"tenant": current_tenant}
            finally:
                session.close()


def test_bulk_updates_and_deletes_are_scoped_to_the_active_installation(isolated_session_factory):
    tenant_a_ids = _insert_installation_graph(isolated_session_factory, "tenant-a", "a")
    tenant_b_ids = _insert_installation_graph(isolated_session_factory, "tenant-b", "b")

    with installation_scope("tenant-a"):
        session = isolated_session_factory()
        try:
            assert session.query(Customer).update({Customer.company: "A only"}) == 1
            assert session.query(Customer).update({Customer.installation_id: "tenant-b"}) == 1
            assert session.query(Customer).filter(Customer.id == tenant_b_ids[Customer]).delete() == 0
            session.commit()
        finally:
            session.close()

    with installation_scope("tenant-a"):
        session = isolated_session_factory()
        try:
            own_customer = session.query(Customer).one()
            assert own_customer.id == tenant_a_ids[Customer]
            assert own_customer.installation_id == "tenant-a"

            with pytest.raises(InstallationContextError, match="masiva entre instalaciones"):
                session.execute(
                    insert(Customer),
                    {
                        "id": "bulk-foreign",
                        "installation_id": "tenant-b",
                        "name": "Bulk foreign",
                        "email": "bulk-foreign@example.test",
                    },
                )
        finally:
            session.rollback()
            session.close()

    with installation_scope("tenant-b"):
        session = isolated_session_factory()
        try:
            tenant_b_customer = session.query(Customer).one()
            assert tenant_b_customer.company is None
        finally:
            session.close()


def test_username_uniqueness_is_scoped_to_each_installation(isolated_session_factory):
    _insert_installation_graph(isolated_session_factory, "tenant-a", "a")
    _insert_installation_graph(isolated_session_factory, "tenant-b", "b")

    for installation_id in ("tenant-a", "tenant-b"):
        with installation_scope(installation_id):
            session = isolated_session_factory()
            try:
                user = session.query(User).filter(User.username == "shared-user").one()
                assert user.installation_id == installation_id
            finally:
                session.close()

    with installation_scope("tenant-a"):
        session = isolated_session_factory()
        try:
            session.add(
                User(
                    id="duplicate-user-a",
                    username="shared-user",
                    password_hash="irrelevant-test-hash",
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
        finally:
            session.rollback()
            session.close()


def test_composite_foreign_keys_reject_every_cross_installation_relation(
    isolated_session_factory,
):
    tenant_a_ids = _insert_installation_graph(isolated_session_factory, "tenant-a", "a")
    tenant_b_ids = _insert_installation_graph(isolated_session_factory, "tenant-b", "b")
    cross_installation_relations = (
        ("customer.pricelist", Customer, "pricelist_id", Pricelist),
        ("quote.customer", Quote, "customer_id", Customer),
        ("order.customer", Order, "customer_id", Customer),
        ("order.quote", Order, "quote_id", Quote),
        ("reservation.order", StockReservation, "order_id", Order),
        ("reservation.product", StockReservation, "product_id", Product),
        ("invoice.order", InvoiceDraft, "order_id", Order),
        ("invoice.customer", InvoiceDraft, "customer_id", Customer),
        ("conversation.customer", ConversationState, "customer_id", Customer),
        ("conversation.quote", ConversationState, "active_quote_id", Quote),
        ("conversation.order", ConversationState, "order_id", Order),
        ("rag_chunk.document", RAGChunk, "document_id", RAGDocument),
    )

    with installation_scope("tenant-a"):
        for relation_name, child_model, foreign_key_attribute, parent_model in cross_installation_relations:
            session = isolated_session_factory()
            try:
                child = session.get(child_model, tenant_a_ids[child_model])
                assert child is not None, relation_name
                setattr(child, foreign_key_attribute, tenant_b_ids[parent_model])
                with pytest.raises(IntegrityError) as exc_info:
                    session.commit()
                assert "FOREIGN KEY" in str(exc_info.value), relation_name
            finally:
                session.rollback()
                session.close()


def test_identity_map_cannot_leak_after_switching_installation_scope(isolated_session_factory):
    tenant_a_ids = _insert_installation_graph(isolated_session_factory, "tenant-a", "a")
    tenant_b_ids = _insert_installation_graph(isolated_session_factory, "tenant-b", "b")
    session = isolated_session_factory()
    try:
        with installation_scope("tenant-b"):
            tenant_b_customer = session.get(Customer, tenant_b_ids[Customer])
            assert tenant_b_customer is not None
            assert tenant_b_customer.installation_id == "tenant-b"
            newly_persisted_log = AuditLog(
                id="identity-map-new-b",
                event_type="identity_map_test",
                status="success",
            )
            session.add(newly_persisted_log)
            session.commit()
            assert session.get(AuditLog, newly_persisted_log.id) is newly_persisted_log

        with installation_scope("tenant-a"):
            assert session.get(Customer, tenant_b_ids[Customer]) is None
            assert session.get(AuditLog, newly_persisted_log.id) is None
            tenant_a_customer = session.get(Customer, tenant_a_ids[Customer])
            assert tenant_a_customer is not None
            assert tenant_a_customer.installation_id == "tenant-a"

        with installation_scope("tenant-b"):
            assert session.get(Customer, tenant_a_ids[Customer]) is None
            assert session.get(Customer, tenant_b_ids[Customer]) is tenant_b_customer
            assert session.get(AuditLog, newly_persisted_log.id) is newly_persisted_log
    finally:
        session.close()


def test_cross_installation_write_is_rejected(isolated_session_factory):
    with installation_scope("tenant-a"):
        session = isolated_session_factory()
        try:
            session.add(
                Customer(
                    id="foreign-customer",
                    installation_id="tenant-b",
                    name="Foreign",
                    email="foreign@example.test",
                )
            )
            with pytest.raises(InstallationContextError, match="entre instalaciones"):
                session.flush()
        finally:
            session.rollback()
            session.close()


def test_missing_installation_configuration_fails_closed(isolated_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "INSTALLATION_ID", " ")
    session = isolated_session_factory()
    try:
        with pytest.raises(InstallationContextError, match="installation_id"):
            session.query(Customer).all()

        session.add(Customer(id="orphan", name="Orphan", email="orphan@example.test"))
        with pytest.raises(InstallationContextError, match="installation_id"):
            session.flush()
    finally:
        session.rollback()
        session.close()
