"""Evals T-083: email real vía GoHighLevel (``EMAIL_PROVIDER=ghl``).

Cubre:

- ``GhlEmailProvider``: resuelve el contacto con ``upsert_contact`` (por
  email) y envía por la API de mensajes de GHL con el HTML de tracking;
  errores cerrados (``accepted=False``) y sin red.
- ``send_email`` registra el proveedor ``ghl`` de forma perezosa y audita
  el envío como ``automation.email_sent`` con ``provider=ghl``.
- Campañas: con ``EMAIL_PROVIDER=ghl`` los destinatarios se marcan ``sent``
  con su token de tracking, el HTML lleva el pixel y los clics reescritos, y
  los eventos open/click (vía los endpoints públicos) alimentan las
  estadísticas ``opened``/``clicked`` de la campaña.
- Bridge async→sync: el proveedor funciona desde un hilo sin event loop
  (endpoints sync / worker de tareas) y desde un hilo con loop corriendo
  (endpoint async) sin conflictos.

Hermeticidad D-032: el adaptador GHL se simula con un doble; ninguna prueba
toca la red.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

import pytest
from app.database import Base, SessionLocal
from app.installation_context import installation_scope
from app.models.models import CampaignRecipient, EmailTemplate
from app.services import automations
from app.services import ghl_email_provider as gep
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION = "ghl-email-instalacion"
PORTAL_TEST_PASSWORD = "Portal-Test-123!"


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
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
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


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Proveedor GHL
# ---------------------------------------------------------------------------


def test_ghl_email_provider_requires_configuration() -> None:
    """Sin credenciales GHL (conftest las deja vacías) → falla cerrado sin red."""

    result = gep.GhlEmailProvider().send("x@example.invalid", "S", "B")
    assert result.accepted is False
    assert result.status == "failed"
    assert result.error == "ghl_not_configured"


def test_ghl_email_provider_sends_via_adapter(fake_ghl: FakeGHLAdapter) -> None:
    result = gep.GhlEmailProvider().send(
        "ana@example.invalid",
        "Oferta para Ana",
        "Cuerpo plano",
        html="<p>Hola</p>",
    )
    assert result.accepted is True
    assert result.status == "sent"
    assert result.provider == "ghl"
    instance = fake_ghl.instances[-1]
    assert instance.upserted == ["ana@example.invalid"]
    assert instance.sent == [
        {
            "contact_id": "c-1",
            "subject": "Oferta para Ana",
            "content": "Cuerpo plano",
            "html": "<p>Hola</p>",
        }
    ]


def test_ghl_email_provider_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter(FakeGHLAdapter):
        async def send_email(self, *, contact_id, subject, content, html=None):
            raise RuntimeError("GHL caído")

    monkeypatch.setattr(gep, "GHLAdapter", FailingAdapter)
    result = gep.GhlEmailProvider().send("ana@example.invalid", "S", "B")
    assert result.accepted is False
    assert result.status == "failed"
    assert result.error and "ghl_error" in result.error


def test_ghl_email_provider_works_with_running_event_loop(fake_ghl: FakeGHLAdapter) -> None:
    """El puente async→sync también funciona si ya hay un loop corriendo."""

    async def _inside_loop() -> None:
        result = await asyncio.to_thread(
            gep.GhlEmailProvider().send, "ana@example.invalid", "S", "B"
        )
        assert result.accepted is True
        assert result.status == "sent"

    asyncio.run(_inside_loop())


def test_ghl_email_provider_works_from_plain_thread(fake_ghl: FakeGHLAdapter) -> None:
    """El puente usa ``asyncio.run`` en un hilo sin loop (endpoints sync)."""

    captured: dict[str, Any] = {}

    def _run() -> None:
        captured["result"] = gep.GhlEmailProvider().send("ana@example.invalid", "S", "B")

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join()
    assert captured["result"].accepted is True


# ---------------------------------------------------------------------------
# send_email: registro perezoso del proveedor ghl + auditoría
# ---------------------------------------------------------------------------


def test_send_email_ghl_success_is_audited_as_sent(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake_ghl: FakeGHLAdapter
) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            result = automations.send_email(
                db, to="x@example.invalid", subject="S", body="B"
            )
            db.commit()
            assert result.accepted is True
            assert result.status == "sent"
            assert result.provider == "ghl"
            from app.models.models import AuditLog

            audits = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "automation.email_sent")
                .all()
            )
            assert len(audits) == 1
            assert audits[0].status == "success"
            assert audits[0].details["provider"] == "ghl"
    automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# Campañas: entrega real vía GHL + tracking de apertura/clic
# ---------------------------------------------------------------------------


def _seed_html_template(client) -> str:
    db = SessionLocal()
    try:
        name = _unique("tpl-ghl")
        db.add(
            EmailTemplate(
                name=name,
                subject="Oferta para {{lead.first_name}}",
                body='<p>Hola {{lead.first_name}}</p><p><a href="https://example.com/oferta">Ver oferta</a></p>',
                is_active=True,
            )
        )
        db.commit()
        return name
    finally:
        db.close()


def _cleanup_template(name: str) -> None:
    db = SessionLocal()
    try:
        db.query(EmailTemplate).filter(EmailTemplate.name == name).delete()
        db.commit()
    finally:
        db.close()


def _seed_lead(account_id: str) -> str:
    from app.models.models import Lead

    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente GHL",
            company_name="GHL Corp",
            source="web",
            status="new",
            account_id=account_id,
        )
        db.add(lead)
        db.commit()
        return lead.id
    finally:
        db.close()


def _cleanup_lead(lead_id: str) -> None:
    from app.models.models import Lead

    db = SessionLocal()
    try:
        db.query(Lead).filter(Lead.id == lead_id).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_campaign(client, token, campaign_id: str | None) -> None:
    if campaign_id is None:
        return
    client.delete(f"/campaigns/{campaign_id}", headers={"Authorization": f"Bearer {token}"})


def test_campaign_send_with_ghl_delivers_and_tracks(
    client, auth_headers, fake_ghl: FakeGHLAdapter, monkeypatch
) -> None:
    """Campaña con EMAIL_PROVIDER=ghl: entrega real + pixel/clics → stats."""

    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    monkeypatch.setattr(
        automations.settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    token = auth_headers["Authorization"].split()[-1]
    template_name = _seed_html_template(client)
    account_id = f"acct-{uuid.uuid4().hex[:8]}"
    lead_id = _seed_lead(account_id)
    campaign_id: str | None = None
    try:
        created = client.post(
            "/campaigns",
            json={
                "name": _unique("campaña-ghl"),
                "description": "Campaña de prueba GHL",
                "template_name": template_name,
                # Segmento acotado a NUESTRA cuenta para no arrastrar leads
                # de otros tests del mismo proceso (BD compartida).
                "segment": {"account_ids": [account_id]},
            },
            headers={**auth_headers, "Idempotency-Key": f"camp-{uuid.uuid4().hex}"},
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]

        sent = client.post(
            f"/campaigns/{campaign_id}/send", headers=auth_headers
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["sent"] == 1
        assert sent.json()["failed"] == 0

        # El proveedor GHL recibió el email del lead con el HTML de tracking.
        instance = fake_ghl.instances[-1]
        assert instance.upserted and instance.upserted[-1].endswith("@example.invalid")
        payload = instance.sent[-1]
        assert "bridge.example/email-tracking/" in payload["html"]
        assert "/open.png" in payload["html"], "El pixel de apertura viaja en el HTML"
        assert "/click?u=" in payload["html"], "Los clics se reescriben al tracker"

        # El destinatario quedó con token de tracking y estado sent.
        db = SessionLocal()
        try:
            recipient = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .first()
            )
            assert recipient is not None
            assert recipient.status == "sent"
            assert recipient.tracking_token
            token_tracking = recipient.tracking_token
        finally:
            db.close()

        # Apertura y clic reales vía los endpoints públicos (sin auth).
        opened = client.get(f"/email-tracking/{token_tracking}/open.png")
        assert opened.status_code == 200
        clicked = client.get(
            f"/email-tracking/{token_tracking}/click",
            params={"u": "https://example.com/oferta"},
            follow_redirects=False,
        )
        assert clicked.status_code in (200, 302, 307)

        stats = client.get(f"/campaigns/{campaign_id}", headers=auth_headers).json()
        assert stats["stats"]["sent"] == 1
        assert stats["stats"]["opened"] == 1
        assert stats["stats"]["clicked"] == 1
    finally:
        _cleanup_campaign(client, token, campaign_id)
        _cleanup_template(template_name)
        _cleanup_lead(lead_id)
        automations._EMAIL_PROVIDERS.pop("ghl", None)
