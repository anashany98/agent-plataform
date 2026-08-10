"""Evals D-012 (lote 1): automatizaciones portadas de FlowWink sin Supabase.

Cobertura:

- ``quote_expiry_reminders`` idempotente por ventana: dos sweeps no duplican
  recordatorios; el email va al proveedor local (sin red).
- ``dunning_processor``: marca ``overdue`` y recuerda una vez por paso, sin
  mutar importes (solo lectura + notificación).
- ``generate_invoice_pdf``: PDF válido (``%PDF``), determinista y con el nº de
  factura; de solo lectura.
- ``send_webhook``: firmado con HMAC-SHA256 y con clave de idempotencia.
- ``send_email``: proveedor local, auditado, sin contactar la red.

Hermetismo: SQLite efímero por test, fixtures sintéticos y sin red.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from decimal import Decimal

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import Customer, InvoiceDraft, Quote
from app.services import automations
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION = "automation-instalacion"


class Env:
    def __init__(self, engine: Engine, session_factory: sessionmaker):
        self.engine = engine
        self.session_factory = session_factory


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Env:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "local")
    monkeypatch.setattr(automations.settings, "AUTOMATION_EMAIL_DIR", str(tmp_path / "emails"))
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield Env(engine, session_factory)
    finally:
        engine.dispose()


def _seed(env: Env) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(Customer(id="cust-a", name="Cliente A", email="cliente-a@example.invalid"))
            db.add(
                Quote(
                    id="quote-a",
                    customer_id="cust-a",
                    confirmation_token="tok",
                    confirmation_payload_hash="hash",
                    confirmation_expires_at=now + dt.timedelta(days=2),
                    items=[{"sku": "SKU-1", "quantity": 1}],
                    subtotal=Decimal("100.00"),
                    tax_total=Decimal("21.00"),
                    shipping_total=Decimal("0.00"),
                    grand_total=Decimal("121.00"),
                    currency="EUR",
                    status="draft",
                )
            )
            db.add(
                InvoiceDraft(
                    id="inv-a",
                    invoice_number="INV-2026-0001",
                    order_id="order-a",
                    customer_id="cust-a",
                    items=[{"sku": "SKU-1", "quantity": 1}],
                    total_amount=Decimal("121.00"),
                    tax_amount=Decimal("21.00"),
                    currency="EUR",
                    status="sent",
                )
            )
            # Reescribe created_at para simular vencimiento del dunning.
            db.commit()
            inv = db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-a").one()
            inv.created_at = now - dt.timedelta(days=40)
            db.commit()


def _db(env: Env):
    return installation_scope(INSTALLATION)


# ---------------------------------------------------------------------------
# quote-expiry-reminders
# ---------------------------------------------------------------------------


def test_quote_expiry_reminders_is_idempotent_per_window(env: Env) -> None:
    _seed(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            first = automations.quote_expiry_reminders(db)
            assert first["evaluated"] == 1
            assert first["reminded"] == 1

            second = automations.quote_expiry_reminders(db)
            assert second["reminded"] == 0, "Un segundo sweep no debe duplicar el recordatorio"

    provider = automations.get_local_provider()
    assert len(provider.sent) == 1, "Solo un email local de recordatorio"
    assert "caduca" in provider.sent[0].subject.lower()


# ---------------------------------------------------------------------------
# dunning-processor
# ---------------------------------------------------------------------------


def test_dunning_marks_overdue_and_does_not_mutate_amounts(env: Env) -> None:
    _seed(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            before = (
                db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-a").one()
            )
            before_total = Decimal(before.total_amount)

            result = automations.dunning_processor(db)
            assert result["evaluated"] == 1
            assert result["processed"] == 1

            after = db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-a").one()
            assert after.status == "overdue"
            assert Decimal(after.total_amount) == before_total, "El dunning no muta importes"

            # Un segundo procesado en el mismo paso no duplica.
            again = automations.dunning_processor(db)
            assert again["processed"] == 0


# ---------------------------------------------------------------------------
# generate-invoice-pdf
# ---------------------------------------------------------------------------


def _make_invoice() -> InvoiceDraft:
    return InvoiceDraft(
        id="inv-x",
        invoice_number="INV-2026-0042",
        order_id="order-x",
        customer_id="cust-x",
        items=[],
        total_amount=Decimal("121.00"),
        tax_amount=Decimal("21.00"),
        currency="EUR",
        status="draft",
    )


def test_invoice_pdf_is_valid_and_deterministic() -> None:
    invoice = _make_invoice()
    pdf_a = automations.generate_invoice_pdf(invoice)
    pdf_b = automations.generate_invoice_pdf(invoice)
    assert pdf_a.startswith(b"%PDF"), "Debe ser un PDF válido"
    assert b"%%EOF" in pdf_a
    assert pdf_a == pdf_b, "El PDF debe ser determinista"
    assert b"INV-2026-0042" in pdf_a, "Debe contener el número de factura"


# ---------------------------------------------------------------------------
# send-webhook (firma HMAC)
# ---------------------------------------------------------------------------


def test_webhook_signature_matches_hmac() -> None:
    payload = b'{"a":1}'
    secret = "s3cret"
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert automations.sign_webhook_payload(payload, secret) == expected


def test_send_webhook_returns_signed_idempotent_result(monkeypatch) -> None:
    import asyncio

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    async def fake_guarded(breaker_name, operation):
        captured["breaker"] = breaker_name
        return FakeResponse()

    monkeypatch.setattr(automations, "guarded_request_with_retry", fake_guarded)
    # Política endurecida (auditoría 2026-08-10): se exige un secreto de
    # configuración ≥32 caracteres; no se usa la idempotency_key como HMAC.
    monkeypatch.setattr(
        automations.settings,
        "WEBHOOK_OUTBOUND_SECRET",
        "test-webhook-outbound-secret-32-chars",
    )
    # El validador SSRF resuelve DNS; allowlistamos el host del test para
    # no depender de la red real ni de hosts.example.com. ``monkeypatch.setattr``
    # permite crear atributos dinámicos en instancias de ``pydantic.BaseSettings``.
    monkeypatch.setattr(
        automations.settings,
        "WEBHOOK_OUTBOUND_ALLOWED_HOSTS",
        "destino.example,public.test",
        raising=False,
    )
    result = asyncio.run(
        automations.send_webhook(
            url="https://public.test/hook", payload={"a": 1}, idempotency_key="idem-1"
        )
    )
    assert result["status"] == "sent", result
    assert result["idempotency_key"] == "idem-1"
    assert result["signature"].startswith("sha256=")
    assert captured["breaker"] == "webhook"


def test_send_webhook_rejects_when_secret_missing(monkeypatch) -> None:
    """Sin ``WEBHOOK_OUTBOUND_SECRET`` el envío se rechaza con error explícito."""

    import asyncio

    monkeypatch.setattr(automations.settings, "WEBHOOK_OUTBOUND_SECRET", "")
    monkeypatch.setattr(
        automations.settings,
        "WEBHOOK_OUTBOUND_ALLOWED_HOSTS",
        "destino.example",
        raising=False,
    )
    result = asyncio.run(
        automations.send_webhook(
            url="https://destino.example/hook", payload={"a": 1}, idempotency_key="idem-2"
        )
    )
    assert result["status"] == "rejected"
    assert result["accepted"] is False
    assert "WEBHOOK_OUTBOUND_SECRET" in result["error"]


def test_send_webhook_blocks_private_network_url(monkeypatch) -> None:
    """El validador SSRF bloquea destinos RFC1918 / loopback."""

    import asyncio

    monkeypatch.setattr(
        automations.settings,
        "WEBHOOK_OUTBOUND_SECRET",
        "test-webhook-outbound-secret-32-chars",
    )
    for blocked in ("http://10.0.0.1/hook", "http://127.0.0.1:9000/x", "http://192.168.1.5/x"):
        result = asyncio.run(
            automations.send_webhook(
                url=blocked, payload={"x": 1}, idempotency_key=f"idem-{blocked}"
            )
        )
        assert result["status"] == "rejected", (blocked, result)
        assert result["accepted"] is False
        assert "private_network" in result["error"], (blocked, result)


# ---------------------------------------------------------------------------
# send-email local (sin red)
# ---------------------------------------------------------------------------


def test_send_email_local_is_audited_without_network(env: Env) -> None:
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.provider == "local"
            assert result.accepted is True
            from app.models.models import AuditLog

            audits = (
                db.query(AuditLog).filter(AuditLog.event_type == "automation.email_sent").all()
            )
            assert len(audits) == 1


# ---------------------------------------------------------------------------
# sweep agregado
# ---------------------------------------------------------------------------


def test_run_automation_sweep_runs_both(env: Env) -> None:
    _seed(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            summary = automations.run_automation_sweep(db)
            assert summary["quote_expiry"]["reminded"] == 1
            assert summary["dunning"]["processed"] == 1
