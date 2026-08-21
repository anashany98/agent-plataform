"""Evals T-083c: reintento con backoff y DLQ para envíos de campaña.

Si el proveedor GHL falla a mitad del envío:

- Los destinatarios fallidos (error transitorio ``ghl_error:*``) se reencolan
  en el outbox durable (``campaign.deliver``) en la misma transacción y la
  campaña queda en ``pending_retry`` (nunca finge entrega).
- El worker reintenta con backoff exponencial (``attempt_count`` y
  ``next_attempt_at`` persistentes); al entregar, el destinatario pasa a
  ``sent`` y la campaña vuelve a ``sent``.
- Un fallo permanente (GHL sin configurar) cae a la DLQ con motivo claro y
  el destinatario queda ``failed``.
- El reenvío de una campaña en ``pending_retry`` es idempotente: no duplica
  destinatarios ni mensajes de outbox.

Hermeticidad D-032: el adaptador GHL se simula con un doble; el worker se
conduce a mano con ``process_due`` (en tests está deshabilitado).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from app.database import SessionLocal
from app.installation_context import installation_scope
from app.main import (
    CAMPAIGN_DELIVER_TOPIC,
    _dispatch_campaign_deliver,
    _dispatch_ghl_lead_capture,
)
from app.models.models import (
    Campaign,
    CampaignRecipient,
    EmailTemplate,
    Lead,
    OutboxMessage,
)
from app.services import automations
from app.services import ghl_email_provider as gep
from app.services.outbox import OutboxService

INSTALLATION_ID = "test-installation"


class _FailingThenOkAdapter:
    """Doble del adaptador GHL: falla los primeros ``fail_times`` envíos."""

    def __init__(self, *, fail_times: int = 0, configured: bool = True) -> None:
        self.fail_times = fail_times
        self._configured = configured
        self.calls = 0
        self.sent: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return self._configured

    async def upsert_contact(self, *, email, first_name, phone=None, company_name=None):
        return {"contact": {"id": "c-1"}}

    async def send_email(self, *, contact_id, subject, content, html=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("GHL caído a mitad del envío")
        self.sent.append(
            {"contact_id": contact_id, "subject": subject, "content": content, "html": html}
        )
        return {"id": f"m-{self.calls}"}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_template_and_lead() -> tuple[str, str, str]:
    db = SessionLocal()
    try:
        template_name = _unique("tpl-retry")
        db.add(
            EmailTemplate(
                name=template_name,
                subject="Retry para {{lead.first_name}}",
                body="Hola {{lead.first_name}}, esto es una campaña de reintento.",
                is_active=True,
            )
        )
        account_id = f"acct-{uuid.uuid4().hex[:8]}"
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Retry",
            company_name=None,
            source="web",
            status="new",
            account_id=account_id,
        )
        db.add(lead)
        db.commit()
        return template_name, account_id, lead.id
    finally:
        db.close()


def _cleanup(template_name: str, campaign_id: str | None) -> None:
    db = SessionLocal()
    try:
        if campaign_id:
            db.query(CampaignRecipient).filter(
                CampaignRecipient.campaign_id == campaign_id
            ).delete()
            db.query(OutboxMessage).filter(
                OutboxMessage.idempotency_key.like(f"campaign-deliver:{campaign_id}:%")
            ).delete()
            db.query(Campaign).filter(Campaign.id == campaign_id).delete()
        db.query(EmailTemplate).filter(EmailTemplate.name == template_name).delete()
        db.commit()
    finally:
        db.close()


def _create_campaign(client, auth_headers, template_name: str, account_id: str) -> str:
    created = client.post(
        "/campaigns",
        json={
            "name": _unique("campaña-retry"),
            "description": "Campaña de reintento",
            "template_name": template_name,
            # Segmento acotado a NUESTRA cuenta para no arrastrar leads de
            # otros tests del mismo proceso (BD compartida).
            "segment": {"account_ids": [account_id]},
        },
        headers={**auth_headers, "Idempotency-Key": f"camp-{uuid.uuid4().hex}"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _outbox_state(db, campaign_id: str) -> OutboxMessage | None:
    return (
        db.query(OutboxMessage)
        .filter(
            OutboxMessage.topic == CAMPAIGN_DELIVER_TOPIC,
            OutboxMessage.idempotency_key.like(f"campaign-deliver:{campaign_id}:%"),
        )
        .first()
    )


def _run_cycle(now: dt.datetime) -> dict[str, int]:
    db = SessionLocal()
    try:
        with installation_scope(INSTALLATION_ID):
            return asyncio.run(
                OutboxService(db).process_due(
                    dispatchers={CAMPAIGN_DELIVER_TOPIC: _dispatch_campaign_deliver},
                    now=now,
                )
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fallo transitorio a mitad del envío → reencolado + backoff + entrega
# ---------------------------------------------------------------------------


def test_campaign_requeues_failed_recipient_with_backoff_and_delivers(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    monkeypatch.setattr(
        automations.settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    adapter = _FailingThenOkAdapter(fail_times=2)
    monkeypatch.setattr(gep, "GHLAdapter", lambda: adapter)

    template_name, account_id, lead_id = _seed_template_and_lead()
    campaign_id: str | None = None
    try:
        campaign_id = _create_campaign(client, auth_headers, template_name, account_id)

        # Primer envío: GHL falla → el destinatario se reencola.
        sent = client.post(f"/campaigns/{campaign_id}/send", headers=auth_headers)
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["sent"] == 0
        assert body["failed"] == 0
        assert body["queued_for_retry"] == 1, body

        db = SessionLocal()
        try:
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "pending_retry", "Campaña pendiente de reintento"
            recipient = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .one()
            )
            assert recipient.status == "queued"
            assert "ghl_error" in (recipient.error or "")
            message = _outbox_state(db, campaign_id)
            assert message is not None
            assert message.state == "pending"
            assert message.attempt_count == 0
        finally:
            db.close()

        # El intento inline del endpoint ya consumió la llamada 1; el worker
        # reintenta con backoff: llamada 2 falla (reintento programado) y la
        # llamada 3 (GHL recuperado) entrega.
        now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        summary = _run_cycle(now)
        assert summary["retry_scheduled"] == 1, summary

        db = SessionLocal()
        try:
            message = _outbox_state(db, campaign_id)
            assert message.state == "pending"
            assert message.attempt_count == 1
            assert message.next_attempt_at is not None
            assert message.next_attempt_at > now, "Backoff: el siguiente intento va al futuro"
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "pending_retry", "Sigue pendiente mientras hay reintentos"
        finally:
            db.close()

        # Intento 2 del worker: GHL recuperado → entrega, destinatario sent.
        summary = _run_cycle(now + dt.timedelta(seconds=30))
        assert summary["sent"] == 1, summary

        db = SessionLocal()
        try:
            message = _outbox_state(db, campaign_id)
            assert message.state == "sent"
            # attempt_count cuenta fallos: hubo uno antes de la entrega.
            assert message.attempt_count == 1
            recipient = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .one()
            )
            assert recipient.status == "sent"
            assert recipient.tracking_token, "El destinatario entregado conserva su token"
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "sent", "La campaña vuelve a sent al agotar la cola"
        finally:
            db.close()
        assert adapter.sent, "El adaptador terminó entregando el email"
    finally:
        _cleanup(template_name, campaign_id)
        automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# Fallo permanente (GHL sin configurar) → falla de inmediato, sin cola
# ---------------------------------------------------------------------------


def test_campaign_fails_immediately_when_ghl_not_configured(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    adapter = _FailingThenOkAdapter(configured=False)
    monkeypatch.setattr(gep, "GHLAdapter", lambda: adapter)

    template_name, account_id, _lead_id = _seed_template_and_lead()
    campaign_id: str | None = None
    try:
        campaign_id = _create_campaign(client, auth_headers, template_name, account_id)
        sent = client.post(f"/campaigns/{campaign_id}/send", headers=auth_headers)
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["failed"] == 1
        assert body["queued_for_retry"] == 0

        db = SessionLocal()
        try:
            recipient = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .one()
            )
            assert recipient.status == "failed"
            assert "ghl_not_configured" in (recipient.error or "")
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "sent", "Sin reintentos pendientes la campaña cierra"
            assert _outbox_state(db, campaign_id) is None, "No se ocupa la cola"
        finally:
            db.close()
    finally:
        _cleanup(template_name, campaign_id)
        automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# Reintentos agotados (fallo transitorio persistente) → DLQ con motivo claro
# ---------------------------------------------------------------------------


def test_campaign_dlq_when_retries_exhausted(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    adapter = _FailingThenOkAdapter(fail_times=99)
    monkeypatch.setattr(gep, "GHLAdapter", lambda: adapter)

    template_name, account_id, _lead_id = _seed_template_and_lead()
    campaign_id: str | None = None
    try:
        campaign_id = _create_campaign(client, auth_headers, template_name, account_id)
        sent = client.post(f"/campaigns/{campaign_id}/send", headers=auth_headers)
        assert sent.status_code == 200, sent.text
        assert sent.json()["queued_for_retry"] == 1

        # El intento inline del endpoint consumió una llamada; los 3 intentos
        # del worker fallan → el mensaje agota el presupuesto y va a la DLQ.
        now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        for _ in range(3):
            summary = _run_cycle(now)
            assert summary["retry_scheduled"] == 1 or summary["dead"] == 1, summary
            now = now + dt.timedelta(seconds=30)

        db = SessionLocal()
        try:
            message = _outbox_state(db, campaign_id)
            assert message is not None
            assert message.state == "dead", "DLQ al agotar el presupuesto de reintentos"
            assert message.attempt_count == int(message.max_attempts)
            assert message.last_error and "ghl_error" in str(message.last_error)
            recipient = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .one()
            )
            assert recipient.status == "failed", "El destinatario termina failed, no en cola"
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "sent", "Sin reintentos pendientes la campaña cierra"
        finally:
            db.close()
    finally:
        _cleanup(template_name, campaign_id)
        automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# Stats con destinatarios en cola + reenvío idempotente de pending_retry
# ---------------------------------------------------------------------------


def test_campaign_stats_include_queued_and_resend_is_idempotent(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(automations.settings, "EMAIL_PROVIDER", "ghl")
    adapter = _FailingThenOkAdapter(fail_times=99)
    monkeypatch.setattr(gep, "GHLAdapter", lambda: adapter)

    template_name, account_id, _lead_id = _seed_template_and_lead()
    campaign_id: str | None = None
    try:
        campaign_id = _create_campaign(client, auth_headers, template_name, account_id)
        sent = client.post(f"/campaigns/{campaign_id}/send", headers=auth_headers)
        assert sent.status_code == 200, sent.text
        assert sent.json()["queued_for_retry"] == 1

        detail = client.get(f"/campaigns/{campaign_id}", headers=auth_headers).json()
        assert detail["status"] == "pending_retry"
        assert detail["stats"]["queued"] == 1
        assert detail["stats"]["failed"] == 0

        # Reenvío de una campaña en pending_retry: idempotente, no duplica.
        again = client.post(f"/campaigns/{campaign_id}/send", headers=auth_headers)
        assert again.status_code == 200, again.text
        assert again.json()["recipients"] == 0, "No se materializan destinatarios nuevos"
        assert again.json()["queued_for_retry"] == 0, "Los que ya están en cola no se reencolan"
        assert again.json()["sent"] == 0

        db = SessionLocal()
        try:
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one()
            assert campaign.status == "pending_retry", "Sigue pendiente: quedan reintentos en cola"
            recipients = (
                db.query(CampaignRecipient)
                .filter(CampaignRecipient.campaign_id == campaign_id)
                .all()
            )
            assert len(recipients) == 1, "Un solo destinatario materializado"
            messages = (
                db.query(OutboxMessage)
                .filter(
                    OutboxMessage.topic == CAMPAIGN_DELIVER_TOPIC,
                    OutboxMessage.idempotency_key.like(f"campaign-deliver:{campaign_id}:%"),
                )
                .all()
            )
            assert len(messages) == 1, "Un solo mensaje de reintento (idempotente)"
        finally:
            db.close()
    finally:
        _cleanup(template_name, campaign_id)
        automations._EMAIL_PROVIDERS.pop("ghl", None)


# ---------------------------------------------------------------------------
# El resto de dispatchers no se ven afectados (registro intacto)
# ---------------------------------------------------------------------------


def test_campaign_dispatcher_registered_without_breaking_others() -> None:
    from app.main import OUTBOX_DISPATCHERS

    assert CAMPAIGN_DELIVER_TOPIC in OUTBOX_DISPATCHERS
    assert OUTBOX_DISPATCHERS[CAMPAIGN_DELIVER_TOPIC] is _dispatch_campaign_deliver
    # El dispatch de captura de leads sigue registrado.
    assert _dispatch_ghl_lead_capture in OUTBOX_DISPATCHERS.values()
