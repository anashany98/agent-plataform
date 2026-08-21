"""Evals T-083b: notificaciones de automatización con HTML + tracking (GHL).

Cubre:

- ``quote_expiry_reminders`` / ``dunning_processor`` / ``low_stock_alert`` /
  ``cart_abandonment``: con ``EMAIL_PROVIDER=ghl`` y ``EMAIL_TRACKING_BASE_URL``
  el correo sale por el proveedor GHL con la plantilla HTML de marca (pixel de
  apertura + clics reescritos) y registra el evento ``sent`` con su token.
- Con proveedor ``local`` el comportamiento no cambia: sin HTML y sin evento
  de tracking (el spool conserva ``html=None``).
- Sin base URL o con tracking desactivado en el panel (``EmailSettings``) →
  el HTML se omite y se audita ``automation.email.tracking_skipped`` con el
  motivo explícito; el envío GHL sigue ocurriendo.

Hermeticidad D-032: el adaptador GHL se simula con un doble; SQLite efímero.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import (
    Customer,
    EmailSettings,
    EmailTrackingEvent,
    InvoiceDraft,
    Product,
    Quote,
)
from app.services import automations
from app.services import ghl_email_provider as gep
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION = "automation-ghl-html"
TRACKING_BASE = "https://bridge.example"


class FakeGHLAdapter:
    """Doble del adaptador GHL con estado visible para aserciones."""

    instances: list[FakeGHLAdapter] = []

    def __init__(self) -> None:
        self.upserted: list[str] = []
        self.sent: list[dict[str, Any]] = []
        FakeGHLAdapter.instances.append(self)

    def configured(self) -> bool:
        return True

    async def upsert_contact(self, *, email, first_name, phone=None, company_name=None):
        self.upserted.append(email)
        return {"contact": {"id": f"c-{len(self.upserted)}"}}

    async def send_email(self, *, contact_id, subject, content, html=None):
        self.sent.append(
            {"contact_id": contact_id, "subject": subject, "content": content, "html": html}
        )
        return {"id": f"m-{len(self.sent)}"}


@pytest.fixture
def fake_ghl(monkeypatch: pytest.MonkeyPatch) -> FakeGHLAdapter:
    FakeGHLAdapter.instances = []
    monkeypatch.setattr(gep, "GHLAdapter", FakeGHLAdapter)
    return FakeGHLAdapter()


class Env:
    def __init__(self, engine, session_factory):
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


def _set_ghl(monkeypatch: pytest.MonkeyPatch, *, base_url: str | None = TRACKING_BASE) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    monkeypatch.setattr(
        automations.settings,
        "EMAIL_TRACKING_BASE_URL",
        base_url or "",
        raising=False,
    )


def _seed(env: Env) -> None:
    """Presupuesto que caduca pronto + factura vencida (dunning)."""

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
            db.commit()
            inv = db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-a").one()
            inv.created_at = now - dt.timedelta(days=40)
            db.commit()


def _seed_stock_products(env: Env) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add_all(
                [
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
                        id="prod-demo",
                        sku="SKU-DEMO-1",
                        name="Producto demo sin stock",
                        source="demo",
                        base_price=Decimal("1.00"),
                        tax_rate=Decimal("0.21"),
                        stock_quantity=0,
                        reserved_stock=0,
                    ),
                ]
            )
            db.commit()
            _ = now


def _seed_abandoned_quote(env: Env) -> None:
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


def _sent_events(db) -> list[EmailTrackingEvent]:
    return (
        db.query(EmailTrackingEvent)
        .filter(EmailTrackingEvent.event_type == "sent")
        .order_by(EmailTrackingEvent.created_at.asc())
        .all()
    )


def _token_from_html(html: str) -> str | None:
    match = re.search(r"email-tracking/(tk-[0-9a-f]+)/open\.png", html)
    return match.group(1) if match else None


def _assert_tracking_html(payload: dict[str, Any], subject: str) -> str:
    """Comprueba la plantilla HTML de marca + tracking; devuelve el token."""

    html = payload.get("html")
    assert html, "Con GHL + tracking el HTML no debe faltar"
    assert "Agentes IA" in html, "El HTML lleva la marca del portal"
    assert "Control empresarial" in html
    assert subject in html, "El asunto aparece como encabezado escapado"
    assert "/open.png" in html, "El pixel de apertura viaja en el HTML"
    assert "/email-tracking/" in html
    token = _token_from_html(html)
    assert token, "El HTML referencia un token de tracking"
    assert "width=\"1\" height=\"1\"" in html, "El pixel es 1x1"
    return token


# ---------------------------------------------------------------------------
# quote-expiry-reminders con GHL
# ---------------------------------------------------------------------------


def test_quote_expiry_ghl_sends_branded_html_with_tracking(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed(env)
    _set_ghl(monkeypatch)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.quote_expiry_reminders(db)
            db.commit()
            assert result["reminded"] == 1
            assert result["queued_for_manual_delivery"] == 0

            instance = fake_ghl.instances[-1]
            assert instance.upserted == ["cliente-a@example.invalid"]
            payload = instance.sent[-1]
            assert payload["subject"].startswith("Tu presupuesto caduca el")
            token = _assert_tracking_html(payload, "Tu presupuesto caduca el")
            events = _sent_events(db)
            assert len(events) == 1
            assert events[0].token == token
            assert events[0].to == "cliente-a@example.invalid"
    automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# dunning-processor con GHL
# ---------------------------------------------------------------------------


def test_dunning_ghl_sends_branded_html_with_tracking(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed(env)
    _set_ghl(monkeypatch)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.dunning_processor(db)
            db.commit()
            assert result["delivered"] == 1
            assert result["processed"] == 1
            invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == "inv-a").one()
            assert invoice.status == "overdue"

            instance = fake_ghl.instances[-1]
            payload = instance.sent[-1]
            assert "Recordatorio de pago INV-2026-0001" in payload["subject"]
            token = _assert_tracking_html(payload, "Recordatorio de pago")
            events = _sent_events(db)
            assert [e.token for e in events] == [token]
    automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# low-stock-alert con GHL
# ---------------------------------------------------------------------------


def test_low_stock_alert_ghl_sends_branded_html_per_recipient(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed_stock_products(env)
    _set_ghl(monkeypatch)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.low_stock_alert(
                db,
                payload={"recipients": "ops@example.invalid, jefe@example.invalid", "threshold": 5},
                actor="scheduler:test",
            )
            db.commit()
            assert result["alerted"] == 2
            assert result["delivered"] == 2
            assert result["failed"] == 0

            # El adaptador se instancia por llamada: un email por destinatario.
            all_sent = [p for inst in fake_ghl.instances for p in inst.sent]
            assert len(all_sent) == 2, "Un email por destinatario del resumen"
            tokens = set()
            for payload in all_sent:
                assert "Alerta de stock bajo (2 productos)" in payload["subject"]
                tokens.add(_assert_tracking_html(payload, "Alerta de stock bajo"))
            assert len(tokens) == 2, "Cada destinatario tiene su propio token"
            events = _sent_events(db)
            assert len(events) == 2
            assert {e.token for e in events} == tokens
    automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# cart-abandonment con GHL
# ---------------------------------------------------------------------------


def test_cart_abandonment_ghl_sends_branded_html_with_tracking(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed_abandoned_quote(env)
    _set_ghl(monkeypatch)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.cart_abandonment(
                db, payload={"abandoned_days": 3}, actor="scheduler:test"
            )
            db.commit()
            assert result["reminded"] == 1
            assert result["queued_for_manual_delivery"] == 0

            instance = fake_ghl.instances[-1]
            payload = instance.sent[-1]
            assert "quote-abandoned" in payload["subject"]
            token = _assert_tracking_html(payload, "quote-abandoned")
            assert [e.token for e in _sent_events(db)] == [token]
    automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# Sin GHL: el comportamiento no cambia (spool local, sin HTML ni tracking)
# ---------------------------------------------------------------------------


def test_automation_email_unchanged_for_local_provider(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(env)
    # env ya fija EMAIL_PROVIDER=local; sin base URL de tracking.
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.quote_expiry_reminders(db)
            db.commit()
            assert result["queued_for_manual_delivery"] == 1
            assert _sent_events(db) == [], "Sin GHL no se registran eventos de tracking"
    provider = automations.get_local_provider()
    assert len(provider.queued) == 1
    # El spool conserva el cuerpo plano sin HTML.
    spool_files = list(Path(automations.settings.AUTOMATION_EMAIL_DIR).glob("*.json"))
    payload = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert payload["html"] is None
    assert payload["tracking_token"] is None


def test_automation_email_skips_tracking_without_base_url(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed(env)
    _set_ghl(monkeypatch, base_url=None)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.quote_expiry_reminders(db)
            db.commit()
            assert result["reminded"] == 1, "Sin base URL el envío GHL sigue ocurriendo"
            instance = fake_ghl.instances[-1]
            assert instance.sent[-1]["html"] is None, "Sin base URL no se emite HTML con tracking"
            assert _sent_events(db) == [], "Sin base URL no hay evento sent"
            from app.models.models import AuditLog

            skipped = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "automation.email.tracking_skipped")
                .all()
            )
            assert len(skipped) == 1
            assert skipped[0].details["reason"] == "sin_base_url"
    automations._EMAIL_PROVIDERS.pop("ghl", None)


def test_automation_email_skips_tracking_when_disabled_in_panel(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    _seed(env)
    _set_ghl(monkeypatch)
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            db.add(EmailSettings(signature=None, tracking_enabled=False))
            db.commit()
            result = automations.quote_expiry_reminders(db)
            db.commit()
            assert result["reminded"] == 1
            instance = fake_ghl.instances[-1]
            assert instance.sent[-1]["html"] is None, "Tracking apagado en el panel → sin HTML"
            assert _sent_events(db) == []
            from app.models.models import AuditLog

            skipped = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "automation.email.tracking_skipped")
                .all()
            )
            assert len(skipped) == 1
            assert skipped[0].details["reason"] == "tracking_disabled"
    automations._EMAIL_PROVIDERS.pop("ghl", None)


def test_automation_html_escapes_subject_and_rewrites_clicks_once() -> None:
    """La plantilla escapa el asunto y no reescribe dos veces los clics."""

    body = "Revisa tu oferta en https://example.com/oferta?x=1&y=2"
    html = automations._automation_email_html(
        "Asunto <script>alert(1)</script>",
        body,
        TRACKING_BASE,
        "tk-abc123",
        "#0d9488",
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html, "El asunto va escapado"
    # El clic se reescribe una sola vez: la URL de tracking no aparece
    # anidada dentro de otro ?u=.
    assert html.count("email-tracking/tk-abc123/click?u=") == 1
    assert "u=https%3A%2F%2F" in html
    assert "0d9488" in html, "La barra de marca usa el acento dado"
    assert "/open.png" in html
