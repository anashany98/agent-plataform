"""Evals T-083: rebotes de email y entregabilidad de campañas.

Cubre:

- ``POST /webhooks/email-bounce``: firma HMAC (timestamp + body) con
  ``EMAIL_BOUNCE_WEBHOOK_SECRET`` (fail-closed: sin secreto o firma mala →
  401); registra el evento ``bounce`` de forma idempotente (replay → un solo
  evento) por token o por email; token desconocido → 404.
- Estadísticas de campaña: ``bounced`` y las tasas ``opened_rate`` /
  ``clicked_rate`` / ``bounce_rate`` (sobre los enviados; 0 si no hay envíos).
- La columna de destinatario ``bounced`` refleja el evento de rebote.

Hermeticidad: SQLite efímero del harness; el envío usa el proveedor local
(spool) y solo el tracking (tokens) alimenta las estadísticas.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid

from app import main as bridge_main
from app.database import SessionLocal
from app.models.models import (
    CampaignRecipient,
    EmailTemplate,
    EmailTrackingEvent,
    Lead,
)
from app.services import automations

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signed_bounce_request(client, payload: dict) -> object:
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(dt.datetime.now(dt.UTC).timestamp()))
    signature = hmac.new(
        bridge_main.settings.EMAIL_BOUNCE_WEBHOOK_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/email-bounce",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Email-Timestamp": timestamp,
            "X-Email-Signature": f"sha256={signature}",
        },
    )


def _seed_sent_campaign(client, token) -> tuple[str, str]:
    """Campaña real enviada (proveedor local) con un destinatario + token.

    Devuelve (campaign_id, tracking_token). El envío registra el evento
    ``sent`` que el webhook de rebote necesita como ancla.
    """

    db = SessionLocal()
    try:
        template_name = _unique("tpl-bounce")
        db.add(
            EmailTemplate(
                name=template_name,
                subject="Asunto {{lead.first_name}}",
                body="Cuerpo con enlace https://example.com/oferta",
                is_active=True,
            )
        )
        account_id = f"acct-{uuid.uuid4().hex[:8]}"
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Bounce",
            source="web",
            status="new",
            account_id=account_id,
        )
        db.add(lead)
        db.commit()
    finally:
        db.close()

    created = client.post(
        "/campaigns",
        json={
            "name": _unique("campaña-bounce"),
            "description": "Campaña de rebote",
            "template_name": template_name,
            "segment": {"account_ids": [account_id]},
        },
        headers={**_auth(token), "Idempotency-Key": f"camp-{uuid.uuid4().hex}"},
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    sent = client.post(f"/campaigns/{campaign_id}/send", headers=_auth(token))
    assert sent.status_code == 200, sent.text
    assert sent.json()["sent"] == 1

    detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(token)).json()
    token_tracking = detail["recipients"][0]["tracking_token"]
    assert token_tracking
    return campaign_id, token_tracking


def _cleanup(client, token, campaign_id: str, template_name: str) -> None:
    db = SessionLocal()
    try:
        db.query(CampaignRecipient).filter(
            CampaignRecipient.campaign_id == campaign_id
        ).delete()
        db.query(__import__("app.models.models", fromlist=["Campaign"]).Campaign).filter(
            __import__("app.models.models", fromlist=["Campaign"]).Campaign.id == campaign_id
        ).delete()
        db.query(EmailTemplate).filter(EmailTemplate.name == template_name).delete()
        db.commit()
    finally:
        db.close()


def test_bounce_webhook_requires_signature(client) -> None:
    raw_body = json.dumps({"token": "tk-x"}, separators=(",", ":")).encode()
    missing = client.post(
        "/webhooks/email-bounce",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert missing.status_code == 401
    wrong = client.post(
        "/webhooks/email-bounce",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Email-Timestamp": str(int(dt.datetime.now(dt.UTC).timestamp())),
            "X-Email-Signature": "sha256=" + "0" * 64,
        },
    )
    assert wrong.status_code == 401


def test_bounce_webhook_registers_and_feeds_campaign_stats(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(
        automations.settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    token = auth_headers["Authorization"].split()[-1]
    campaign_id: str | None = None
    template_name: str = ""
    try:
        campaign_id, token_tracking = _seed_sent_campaign(client, token)
        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(token)).json()
        template_name = detail["template_name"]
        assert detail["stats"]["sent"] == 1
        assert detail["stats"]["opened"] == 0
        assert detail["stats"]["bounced"] == 0
        assert detail["stats"]["bounce_rate"] == 0.0

        reported = _signed_bounce_request(
            client, {"token": token_tracking, "bounce_type": "hard"}
        )
        assert reported.status_code == 200, reported.text
        body = reported.json()
        assert body["status"] == "registered"
        assert body["new"] is True

        # Replay idempotente: mismo token + tipo → un único evento.
        replay = _signed_bounce_request(
            client, {"token": token_tracking, "bounce_type": "hard"}
        )
        assert replay.status_code == 200
        assert replay.json()["new"] is False
        db = SessionLocal()
        try:
            count = (
                db.query(EmailTrackingEvent)
                .filter(
                    EmailTrackingEvent.token == token_tracking,
                    EmailTrackingEvent.event_type == "bounce",
                )
                .count()
            )
            assert count == 1
        finally:
            db.close()

        stats = client.get(f"/campaigns/{campaign_id}", headers=_auth(token)).json()
        assert stats["stats"]["bounced"] == 1
        assert stats["stats"]["bounce_rate"] == 100.0
        assert stats["stats"]["opened_rate"] == 0.0
        # La columna de destinatario refleja el rebote.
        assert stats["recipients"][0]["bounced"] is True
    finally:
        if campaign_id is not None:
            _cleanup(client, token, campaign_id, template_name)


def test_bounce_webhook_by_email_fallback(client, auth_headers, monkeypatch) -> None:
    """Sin token (solo email) se ancla al envío más reciente de la dirección."""

    monkeypatch.setattr(
        automations.settings,
        "EMAIL_TRACKING_BASE_URL",
        "https://bridge.example",
        raising=False,
    )
    token = auth_headers["Authorization"].split()[-1]
    campaign_id: str | None = None
    template_name: str = ""
    try:
        campaign_id, _ = _seed_sent_campaign(client, token)
        detail = client.get(f"/campaigns/{campaign_id}", headers=_auth(token)).json()
        template_name = detail["template_name"]
        recipient_email = detail["recipients"][0]["email"]

        reported = _signed_bounce_request(client, {"email": recipient_email})
        assert reported.status_code == 200, reported.text
        assert reported.json()["new"] is True

        stats = client.get(f"/campaigns/{campaign_id}", headers=_auth(token)).json()
        assert stats["stats"]["bounced"] == 1
    finally:
        if campaign_id is not None:
            _cleanup(client, token, campaign_id, template_name)


def test_bounce_webhook_unknown_token_404(client) -> None:
    reported = _signed_bounce_request(client, {"token": "tk-unknown"})
    assert reported.status_code == 404


def test_bounce_webhook_requires_token_or_email(client) -> None:
    reported = _signed_bounce_request(client, {"bounce_type": "hard"})
    assert reported.status_code == 422
