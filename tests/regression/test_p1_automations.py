"""Evals D-012 (lote 1): automatizaciones portadas de FlowWink sin Supabase.

Cobertura:

- ``quote_expiry_reminders`` idempotente por ventana: dos sweeps no duplican
  recordatorios; el email va al proveedor local (sin red).
- ``dunning_processor``: marca ``overdue`` y recuerda una vez por paso, sin
  mutar importes (solo lectura + notificación).
- ``generate_invoice_pdf``: PDF válido (``%PDF``), determinista y con el nº de
  factura; de solo lectura.
- ``send_webhook``: firmado con HMAC-SHA256 y con clave de idempotencia.
- ``send_email``: proveedor local, auditado, sin contactar la red; con
  ``EMAIL_PROVIDER=smtp`` el envío real se hace vía SMTP (STARTTLS/SSL) y,
  si el proveedor falla, degradación controlada al spool local (entrega
  manual) con el error original auditado, o fail-closed si el fallback está
  desactivado.

Hermetismo: SQLite efímero por test, fixtures sintéticos, dobles de
``smtplib`` y sin red.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import (
    Customer,
    InstallationAppearance,
    InvoiceDraft,
    Product,
    Quote,
)
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
    automations.get_local_provider().queued.clear()
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
            assert first["reminded"] == 0
            assert first["queued_for_manual_delivery"] == 1

            second = automations.quote_expiry_reminders(db)
            assert second["reminded"] == 0, "Un segundo sweep no debe duplicar el recordatorio"

    provider = automations.get_local_provider()
    assert len(provider.queued) == 1, "Solo un email local de recordatorio"
    assert "caduca" in provider.queued[0].subject.lower()


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


def test_invoice_pdf_uses_installation_accent(env: Env) -> None:
    """El PDF adopta el acento de la instalación (T-061) en la barra de marca."""

    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(InstallationAppearance(accent_color="#0d9488"))
            db.commit()
            pdf = automations.generate_invoice_pdf(_make_invoice(), db=db)
            # #0d9488 → 0.051 0.580 0.533 en el stream de contenido.
            assert b"0.051 0.580 0.533" in pdf, "El acento de la instalación debe pintar el PDF"
            default_pdf = automations.generate_invoice_pdf(_make_invoice())
            assert b"0.141 0.420 0.992" in default_pdf, "Sin db se usa el acento por defecto #246bfd"


def test_invoice_pdf_uses_default_accent_without_db() -> None:
    """Sin sesión de BD (tests herméticos) el PDF usa el acento por defecto."""

    pdf = automations.generate_invoice_pdf(_make_invoice())
    assert b"0.141 0.420 0.992" in pdf, "Debe contener el acento por defecto #246bfd"
    assert b"/Helvetica-Bold" in pdf, "El título usa la tipografía bold del sistema"
    assert b"Agentes IA" in pdf, "Debe incluir la marca del portal"


def test_invoice_pdf_resolves_customer_label(env: Env) -> None:
    """Con BD el PDF muestra nombre + email del cliente en vez del id."""

    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(
                Customer(
                    id="cust-x",
                    name="Cliente Demo",
                    email="demo@example.invalid",
                    company=None,
                    tax_exempt=False,
                )
            )
            db.commit()
            pdf = automations.generate_invoice_pdf(_make_invoice(), db=db)
            assert b"Cliente Demo" in pdf and b"demo@example.invalid" in pdf
            # La etiqueta no cambia el determinismo: mismo número, mismo PDF salvo acento.
            assert b"cust-x" not in pdf, "El id crudo no debe aparecer cuando hay cliente"


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
            assert result.provider == "local_spool"
            assert result.accepted is False
            assert result.status == "queued_for_manual_delivery"
            from app.models.models import AuditLog

            audits = (
                db.query(AuditLog).filter(AuditLog.event_type == "automation.email_queued").all()
            )
            assert len(audits) == 1
            spool_files = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
            assert len(spool_files) == 1
            payload = json.loads(spool_files[0].read_text(encoding="utf-8"))
            assert payload["installation_id"] == INSTALLATION
            assert payload["delivery_status"] == "queued_for_manual_delivery"
            assert payload["retention_days"] > 0


def test_send_email_local_spool_keeps_pdf_attachment(env: Env) -> None:
    """El spool local conserva los adjuntos (PDF en base64) sin perderlos."""

    pdf_bytes = automations.generate_invoice_pdf(
        InvoiceDraft(
            id="inv-att",
            invoice_number="INV-ATT-0001",
            order_id="order-att",
            customer_id="cust-att",
            items=[],
            total_amount=Decimal("10.00"),
            tax_amount=Decimal("0.00"),
            currency="EUR",
            status="draft",
        )
    )
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db,
                to="cliente@example.invalid",
                subject="Tu factura INV-ATT-0001",
                body="Adjuntamos la factura.",
                attachments=[
                    {
                        "filename": "factura-INV-ATT-0001.pdf",
                        "content": pdf_bytes,
                        "mime_type": "application/pdf",
                    }
                ],
            )
            db.commit()
            assert result.status == "queued_for_manual_delivery"

    spool_files = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
    assert len(spool_files) == 1
    payload = json.loads(spool_files[0].read_text(encoding="utf-8"))
    attachments = payload["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "factura-INV-ATT-0001.pdf"
    assert attachments[0]["mime_type"] == "application/pdf"
    import base64 as _b64

    decoded = _b64.b64decode(attachments[0]["content_base64"])
    assert decoded.startswith(b"%PDF"), "El adjunto debe conservar el PDF completo"


def test_send_invoice_email_sends_pdf_with_store_name(env: Env) -> None:
    """send_invoice_email compone asunto con tienda y adjunta el PDF."""

    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(Customer(id="cust-inv", name="Cliente", email="comprador@example.invalid"))
            db.add(
                InvoiceDraft(
                    id="inv-send",
                    invoice_number="INV-2026-0099",
                    order_id="ord-send",
                    customer_id="cust-inv",
                    items=[{"sku": "SKU-1", "quantity": 1}],
                    total_amount=Decimal("121.00"),
                    tax_amount=Decimal("21.00"),
                    currency="EUR",
                    status="draft",
                )
            )
            db.commit()
            invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-send").one()
            result = automations.send_invoice_email(
                db,
                invoice=invoice,
                order_id="ord-send",
                customer_email="comprador@example.invalid",
                actor="chat:confirm",
                store="BTOP Digital",
            )
            db.commit()
            assert result.subject == "Tu factura INV-2026-0099 de BTOP Digital"
            assert result.to == "comprador@example.invalid"
            assert result.status == "queued_for_manual_delivery"

    spool_files = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
    payload = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert payload["attachments"][0]["filename"] == "factura-INV-2026-0099.pdf"
    assert payload["body"].startswith("Hola,")


# ---------------------------------------------------------------------------
# SMTP real (EMAIL_PROVIDER=smtp) + degradación controlada a spool local
# ---------------------------------------------------------------------------


class FakeSMTP:
    """Doble de ``smtplib.SMTP``: registra llamadas sin tocar la red."""

    instances: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlos = 0
        self.tls = False
        self.login_calls: list[tuple[str, str]] = []
        self.sent: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.ehlos += 1

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.login_calls.append((user, password))

    def send_message(self, message):
        self.sent.append(message)


class FakeSMTP_SSL(FakeSMTP):
    pass


def _smtp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import smtp_provider

    FakeSMTP.instances = []
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "smtp")
    for name, value in (
        ("SMTP_HOST", "smtp.example.invalid"),
        ("SMTP_PORT", 587),
        ("SMTP_USERNAME", "bridge-bot"),
        ("SMTP_PASSWORD", "smtp-secret"),
        ("SMTP_FROM", "bridge@example.invalid"),
        ("SMTP_STARTTLS", True),
        ("SMTP_SSL", False),
        ("SMTP_TIMEOUT_SEC", 5.0),
    ):
        monkeypatch.setattr(smtp_provider.settings, name, value)
        monkeypatch.setattr(automations.settings, name, value)
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP_SSL", FakeSMTP_SSL)


def _register_fake_smtp(fake=None) -> object:
    class FakeProvider:
        name = "smtp"

        def __init__(self, inner):
            self.inner = inner

        def send(
            self,
            to,
            subject,
            body,
            attachments=None,
            html=None,
            tracking_token=None,
        ):
            return self.inner(
                to,
                subject,
                body,
                attachments=attachments,
                html=html,
                tracking_token=tracking_token,
            )

    provider = FakeProvider(fake or (lambda to, subject, body, **kwargs: automations.EmailResult(
        "smtp", to, subject, True, "smtp:ref", status="sent"
    )))
    automations.register_email_provider(provider)
    return provider


def test_smtp_provider_sends_via_starttls_with_login(monkeypatch: pytest.MonkeyPatch, env: Env) -> None:
    """El proveedor SMTP envía el mensaje con STARTTLS, login y cabeceras."""

    _smtp_settings(monkeypatch)
    from app.services.smtp_provider import SmtpEmailProvider

    result = SmtpEmailProvider().send(
        "cliente@example.invalid", "Asunto SMTP", "Cuerpo del correo"
    )
    assert result.accepted is True
    assert result.status == "sent"
    assert result.provider == "smtp"
    assert len(FakeSMTP.instances) == 1
    server = FakeSMTP.instances[0]
    assert server.tls is True, "STARTTLS debe negociarse"
    assert server.login_calls == [("bridge-bot", "smtp-secret")]
    assert len(server.sent) == 1
    message = server.sent[0]
    assert message["To"] == "cliente@example.invalid"
    assert message["Subject"] == "Asunto SMTP"
    assert "bridge@example.invalid" in message["From"]


def test_smtp_provider_fails_closed_without_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``SMTP_HOST`` el proveedor falla cerrado sin tocar la red."""

    _smtp_settings(monkeypatch)
    from app.services.smtp_provider import SmtpEmailProvider

    monkeypatch.setattr(automations.settings, "SMTP_HOST", "")
    result = SmtpEmailProvider().send("x@example.invalid", "S", "B")
    assert result.accepted is False
    assert result.status == "failed"
    assert result.error == "smtp_host_not_configured"
    assert FakeSMTP.instances == [], "No debe abrir ninguna conexión"


def test_send_email_smtp_success_is_audited_as_sent(monkeypatch: pytest.MonkeyPatch, env: Env) -> None:
    """SMTP con aceptación audita ``email_sent`` con estado success."""

    _smtp_settings(monkeypatch)
    _register_fake_smtp()
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.accepted is True
            assert result.status == "sent"
            from app.models.models import AuditLog

            audits = db.query(AuditLog).filter(
                AuditLog.event_type == "automation.email_sent"
            ).all()
            assert len(audits) == 1
            assert audits[0].status == "success"
            assert audits[0].details["provider"] == "smtp"
    automations._EMAIL_PROVIDERS.pop("smtp", None)


def test_send_email_smtp_failure_degrades_to_local_spool(
    monkeypatch: pytest.MonkeyPatch, env: Env
) -> None:
    """SMTP caído + fallback activo → spool local auditado, correo no se pierde."""

    _smtp_settings(monkeypatch)
    monkeypatch.setattr(automations.settings, "EMAIL_FALLBACK_TO_LOCAL_SPOOL", True)

    def failing(to, subject, body, **kwargs):
        return automations.EmailResult(
            "smtp", to, subject, False, "smtp:fail",
            error="smtp_error:ConnectionRefusedError:boom", status="failed",
        )

    _register_fake_smtp(failing)
    automations.get_local_provider().queued.clear()
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.provider == "local_spool"
            assert result.accepted is False
            assert result.status == "queued_for_manual_delivery"
            assert "smtp_error" in (result.error or ""), "El error original se conserva"
            from app.models.models import AuditLog

            degraded = db.query(AuditLog).filter(
                AuditLog.event_type == "automation.email_degraded_to_local"
            ).all()
            assert len(degraded) == 1
            assert "smtp_error" in (degraded[0].details.get("error") or "")
            spool = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
            assert len(spool) == 1, "El correo degradado queda en el spool para entrega manual"
            payload = json.loads(spool[0].read_text(encoding="utf-8"))
            assert payload["delivery_status"] == "queued_for_manual_delivery"
    automations._EMAIL_PROVIDERS.pop("smtp", None)


def test_send_email_smtp_failure_without_fallback_fails_closed(
    monkeypatch: pytest.MonkeyPatch, env: Env
) -> None:
    """SMTP caído sin fallback → error auditado y spool vacío (sin pérdida silenciosa)."""

    _smtp_settings(monkeypatch)
    monkeypatch.setattr(automations.settings, "EMAIL_FALLBACK_TO_LOCAL_SPOOL", False)

    def failing(to, subject, body, **kwargs):
        return automations.EmailResult(
            "smtp", to, subject, False, "smtp:fail",
            error="smtp_error:SMTPServerDisconnected:down", status="failed",
        )

    _register_fake_smtp(failing)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.accepted is False
            assert result.status == "failed"
            assert result.provider == "smtp"
            from app.models.models import AuditLog

            failed = db.query(AuditLog).filter(
                AuditLog.event_type == "automation.email_failed"
            ).all()
            assert len(failed) == 1
            assert failed[0].status == "error"
            spool = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
            assert spool == [], "Sin fallback no debe quedar correo en el spool"
    automations._EMAIL_PROVIDERS.pop("smtp", None)


def test_send_email_unknown_provider_fails_closed(monkeypatch: pytest.MonkeyPatch, env: Env) -> None:
    """Un proveedor no registrado falla cerrado sin fingir entrega."""

    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "noexiste")
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.accepted is False
            assert result.status == "failed"
            assert result.error == "email_provider_not_registered:noexiste"


# ---------------------------------------------------------------------------
# sweep agregado
# ---------------------------------------------------------------------------


def test_run_automation_sweep_runs_both(env: Env) -> None:
    _seed(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            summary = automations.run_automation_sweep(db)
            assert summary["quote_expiry"]["queued_for_manual_delivery"] == 1
            assert summary["dunning"]["processed"] == 1


# ---------------------------------------------------------------------------
# low-stock-alert y cart-abandonment (catálogo de tareas programadas)
# ---------------------------------------------------------------------------


def _seed_stock_products(env: Env) -> None:
    from decimal import Decimal

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            products = [
                Product(
                    id="prod-low-1",
                    sku="SKU-LOW-1",
                    name="Tornillo bajo stock",
                    source="prestashop",
                    base_price=Decimal("1.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=0,
                    reserved_stock=0,
                ),
                Product(
                    id="prod-low-2",
                    sku="SKU-LOW-2",
                    name="Arandela casi agotada",
                    source="local",
                    base_price=Decimal("0.50"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=3,
                    reserved_stock=1,
                ),
                Product(
                    id="prod-ok",
                    sku="SKU-OK-1",
                    name="Tuerca con stock",
                    source="prestashop",
                    base_price=Decimal("2.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=50,
                    reserved_stock=0,
                ),
                # Origenes no confiables: jamás se alertan aunque el stock caiga.
                Product(
                    id="prod-demo",
                    sku="SKU-DEMO-1",
                    name="Producto demo sin stock",
                    source="demo",
                    base_price=Decimal("1.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=0,
                    reserved_stock=0,
                ),
                Product(
                    id="prod-fixture",
                    sku="SKU-FIX-1",
                    name="Fixture sin stock",
                    source="fixture",
                    base_price=Decimal("1.00"),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=1,
                    reserved_stock=0,
                ),
            ]
            db.add_all(products)
            db.commit()
            _ = now


def test_low_stock_alert_sends_summary_and_is_idempotent(env: Env) -> None:
    _seed_stock_products(env)
    automations.get_local_provider().queued.clear()
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            first = automations.low_stock_alert(
                db,
                payload={"recipients": "ops@example.invalid, jefe@example.invalid", "threshold": 5},
                actor="scheduler:test",
            )
            db.commit()
            # 2 confiables bajo el umbral; demo/fixture excluidos por origen.
            assert first["evaluated"] == 2
            assert first["alerted"] == 2
            assert first["delivered"] == 2
            assert first["failed"] == 0

            second = automations.low_stock_alert(
                db,
                payload={"recipients": "ops@example.invalid", "threshold": 5},
                actor="scheduler:test",
            )
            assert second["alerted"] == 0, "Misma ventana: no se re-alerta"

    provider = automations.get_local_provider()
    assert len(provider.queued) == 2, "Un email por destinatario del resumen"
    assert "Alerta de stock bajo (2 productos)" in provider.queued[0].subject
    spool = sorted(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
    bodies = "".join(json.loads(f.read_text(encoding="utf-8"))["body"] for f in spool)
    assert "Tornillo bajo stock" in bodies
    assert "Arandela casi agotada" in bodies
    assert "demo" not in bodies.lower()


def test_low_stock_alert_requires_recipients_and_claims_nothing(env: Env) -> None:
    _seed_stock_products(env)
    automations.get_local_provider().queued.clear()
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.low_stock_alert(
                db, payload={"threshold": 5}, actor="scheduler:test"
            )
            db.commit()
            assert result["error"] == "recipients_missing"
            assert result["alerted"] == 0
            # Sin destinatarios no se reclama nada: la siguiente ventana
            # volverá a evaluar los productos.
            retry = automations.low_stock_alert(
                db,
                payload={"recipients": "ops@example.invalid", "threshold": 5},
                actor="scheduler:test",
            )
            assert retry["alerted"] == 2
    assert len(automations.get_local_provider().queued) == 1


def _seed_abandoned_quotes(env: Env) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(Customer(id="cust-a", name="Cliente A", email="cliente-a@example.invalid"))
            db.add(
                Quote(
                    id="quote-abandoned",
                    customer_id="cust-a",
                    confirmation_token="tok-abandoned",
                    confirmation_payload_hash="hash-abandoned",
                    confirmation_expires_at=now + dt.timedelta(days=7),
                    items=[{"sku": "SKU-1", "quantity": 1}],
                    subtotal=Decimal("100.00"),
                    tax_total=Decimal("21.00"),
                    shipping_total=Decimal("0.00"),
                    grand_total=Decimal("121.00"),
                    currency="EUR",
                    status="draft",
                )
            )
            db.commit()
            abandoned = db.query(Quote).filter(Quote.id == "quote-abandoned").one()
            abandoned.created_at = now - dt.timedelta(days=5)
            db.commit()


def test_cart_abandonment_follows_up_and_is_idempotent(env: Env) -> None:
    _seed_abandoned_quotes(env)
    automations.get_local_provider().queued.clear()
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            first = automations.cart_abandonment(
                db, payload={"abandoned_days": 3}, actor="scheduler:test"
            )
            db.commit()
            assert first["evaluated"] == 1
            assert first["queued_for_manual_delivery"] == 1

            second = automations.cart_abandonment(
                db, payload={"abandoned_days": 3}, actor="scheduler:test"
            )
            assert second["queued_for_manual_delivery"] == 0, "Misma ventana: no se repite"

    provider = automations.get_local_provider()
    assert len(provider.queued) == 1
    assert provider.queued[0].to == "cliente-a@example.invalid"
    assert "quote-abandoned" in provider.queued[0].subject


def test_cart_abandonment_ignores_recent_quotes(env: Env) -> None:
    # quote-a de _seed es reciente (creada hoy): no es un carrito abandonado.
    _seed(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.cart_abandonment(
                db, payload={"abandoned_days": 3}, actor="scheduler:test"
            )
            db.commit()
            assert result["evaluated"] == 0
            assert result["queued_for_manual_delivery"] == 0


def test_run_scheduled_task_dispatch_catalog(env: Env) -> None:
    _seed_stock_products(env)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            low = automations.run_scheduled_task(
                db,
                task_type="low_stock_alert",
                payload={"recipients": "ops@example.invalid", "threshold": 5},
                actor="scheduler:test",
            )
            assert low["alerted"] == 2
            sweep = automations.run_scheduled_task(
                db, task_type="automation_sweep", payload={}, actor="scheduler:test"
            )
            assert "quote_expiry" in sweep
            with pytest.raises(ValueError, match="no soportado"):
                automations.run_scheduled_task(
                    db, task_type="noexiste", payload={}, actor="scheduler:test"
                )
