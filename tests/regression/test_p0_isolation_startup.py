import pytest
from app.config import settings
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    ConversationState,
    Customer,
    IdempotencyRecord,
    InvoiceDraft,
    Order,
    Product,
    Quote,
    RAGChunk,
    RAGDocument,
    StockReservation,
)


def test_tenant_owned_records_require_an_explicit_installation_context():
    tenant_owned_models = (
        ApprovalRequest,
        AuditLog,
        ConversationState,
        Customer,
        IdempotencyRecord,
        InvoiceDraft,
        Order,
        Product,
        Quote,
        RAGChunk,
        RAGDocument,
        StockReservation,
    )

    missing_context = [
        model.__tablename__
        for model in tenant_owned_models
        if not ({"installation_id", "tenant_id", "client_id"} & set(model.__table__.columns.keys()))
    ]

    assert missing_context == [], (
        "Aislamiento no demostrable en repositorios compartidos: faltan claves explícitas de instalación "
        f"en {missing_context}"
    )


def test_production_startup_rejects_demo_data_even_when_seed_is_requested(monkeypatch):
    assert hasattr(settings, "ALLOW_DEMO_DATA"), (
        "P0-001: no existe ALLOW_DEMO_DATA para separar el seed de la autorización de uso"
    )
    assert settings.ALLOW_DEMO_DATA is False

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_SECRET", "synthetic-auth-secret-at-least-32-characters")
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "Synthetic-Admin-Password-123!")
    monkeypatch.setattr(settings, "CHATWOOT_WEBHOOK_SECRET", "synthetic-webhook-secret-at-least-32-chars")
    monkeypatch.setattr(settings, "ALLOW_MOCK_LLM", False)
    monkeypatch.setattr(settings, "ALLOW_INTEGRATION_STUBS", False)
    monkeypatch.setattr(settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(settings, "AUTO_SEED_DEMO_DATA", True)
    monkeypatch.setattr(settings, "ALLOW_DEMO_DATA", True)

    with pytest.raises(RuntimeError, match="ALLOW_DEMO_DATA"):
        settings.validate_runtime_security()
