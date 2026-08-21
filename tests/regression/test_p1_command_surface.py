"""Evals T-069: superficie de mando del dueño por email/WhatsApp.

El propietario consulta y da órdenes a los agentes desde el canal que ya
usa, sin abrir el portal, reutilizando el spool de email y la escucha
social:

- **Email**: webhook entrante (HMAC con ``OWNER_COMMAND_EMAIL_WEBHOOK_``
  ``SECRET``) → la intención se resuelve con el CEO agent (memoria por
  conversación) → la respuesta sale por ``send_email`` (spool/SMTP).
  Fail-closed: sin secreto → 401; remitente distinto del configurado → 202
  ignorado auditado, sin respuesta.
- **WhatsApp**: el webhook de escucha social intercepta el número del dueño
  ANTES del triaje comercial → CEO chat → respuesta registrada como mensaje
  saliente (``direction="out"``) en el mismo canal; el entrante se marca
  ``triaged`` con intención ``command``. Fail-closed: número distinto →
  mensaje ``dismissed`` auditado, sin respuesta; superficie desactivada →
  triaje comercial normal.

Hermeticidad D-032: SQLite de test, sin red (spool local), HMAC local y
limpieza en ``finally``; la configuración del dueño se inyecta con
``monkeypatch`` sobre ``settings`` (se restaura sola).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest
from app.config import settings
from app.database import SessionLocal
from app.models.models import AuditLog, SocialChannel, SocialMessage, SocialTriage

PORTAL_TEST_PASSWORD = "Portal-Test-123!"
OWNER_EMAIL = "dueno@miempresa.com"
OWNER_PHONE = "+34600111222"
OWNER_PHONE_DIGITS = "34600111222"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module", autouse=True)
def _restore_business_entities():
    """Hermeticidad sobre la BD compartida del corpus.

    El test de triaje normal (superficie desactivada) deja un lead y/o una
    actividad de follow-up que la limpieza por canal no conoce y que inflan
    los totales de otros tests (p. ej. el calendario/agenda). Este fixture
    elimina en bloque (delta) los leads y actividades creados durante este
    módulo.
    """

    from app.models.models import Activity, Lead

    db = SessionLocal()
    try:
        before_leads = {row[0] for row in db.query(Lead.id).all()}
        before_acts = {row[0] for row in db.query(Activity.id).all()}
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        new_leads = {row[0] for row in db.query(Lead.id).all()} - before_leads
        if new_leads:
            db.query(Activity).filter(Activity.lead_id.in_(new_leads)).delete()
            db.query(Lead).filter(Lead.id.in_(new_leads)).delete()
        new_acts = {row[0] for row in db.query(Activity.id).all()} - before_acts
        if new_acts:
            db.query(Activity).filter(Activity.id.in_(new_acts)).delete()
        db.commit()
    finally:
        db.close()


def _hmac(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _email_signature(raw: bytes, secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed = f"{timestamp}.{raw.decode('utf-8')}"
    return {
        "X-Command-Timestamp": timestamp,
        "X-Command-Signature": f"sha256={_hmac(signed.encode('utf-8'), secret)}",
    }


def _create_channel(client, auth_headers, *, channel: str = "whatsapp") -> str:
    response = client.post(
        "/social/channels",
        json={
            "name": _unique("cmd-canal"),
            "channel": channel,
            "webhook_secret": "cmd-secret-123",
            "verify_token": "cmd-verify",
        },
        headers={
            **auth_headers,
            "Idempotency-Key": f"idem-{uuid.uuid4().hex[:12]}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _whatsapp_webhook(
    client, channel_id: str, *, phone: str, body: str, sender_name: str = "El dueño"
):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "456"},
                            "contacts": [{"profile": {"name": sender_name}}],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": _unique("wamid"),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        }
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    return client.post(
        f"/social/webhook/{channel_id}",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={_hmac(raw, 'cmd-secret-123')}",
        },
    )


def _email_webhook(client, *, sender: str, subject: str, text: str, secret: str):
    payload = {"from": sender, "subject": subject, "text": text}
    raw = json.dumps(payload).encode("utf-8")
    return client.post(
        "/commands/email/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            **_email_signature(raw, secret),
        },
    )


def _cleanup_channels(channel_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        if channel_ids:
            message_ids = [
                row[0]
                for row in db.query(SocialMessage.id)
                .filter(SocialMessage.channel_id.in_(channel_ids))
                .all()
            ]
            if message_ids:
                db.query(SocialTriage).filter(
                    SocialTriage.message_id.in_(message_ids)
                ).delete()
                db.query(SocialMessage).filter(
                    SocialMessage.id.in_(message_ids)
                ).delete()
            db.query(SocialChannel).filter(
                SocialChannel.id.in_(channel_ids)
            ).delete()
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Email: happy path con CEO chat + respuesta por el spool
# ---------------------------------------------------------------------------

def test_email_owner_command_resolves_and_replies(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    monkeypatch.setattr(
        settings, "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", "cmd-email-secret-1"
    )
    response = _email_webhook(
        client,
        sender=OWNER_EMAIL,
        subject="¿cómo van las ventas?",
        text="",
        secret="cmd-email-secret-1",
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["handled"] is True
    assert data["intent"] == "sales_summary"
    assert data["reply_ref"]
    assert "ventas" in data.get("intent_label", "")

    db = SessionLocal()
    try:
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.installation_id == "test-installation",
                AuditLog.event_type == "ceo_command.email",
            )
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert audit is not None
        details = audit.details or {}
        assert details["sender"] == OWNER_EMAIL
        assert details["intent"] == "sales_summary"
        assert details["reply_ref"] == data["reply_ref"]
        assert details["conversation_id"] == f"email-{OWNER_EMAIL}"
    finally:
        db.close()


def test_email_unknown_sender_ignored_without_reply(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_EMAIL", OWNER_EMAIL)
    monkeypatch.setattr(
        settings, "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", "cmd-email-secret-2"
    )
    response = _email_webhook(
        client,
        sender="spam@otra.com",
        subject="¿cómo va todo?",
        text="",
        secret="cmd-email-secret-2",
    )
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["handled"] is False
    assert data["reason"] == "unknown_sender"

    db = SessionLocal()
    try:
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.installation_id == "test-installation",
                AuditLog.event_type == "ceo_command.email.ignored",
            )
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert audit is not None
        assert (audit.details or {}).get("reason") == "unknown_sender"
        # No debe existir ningún envío de respuesta para ese remitente.
        sent = (
            db.query(AuditLog)
            .filter(
                AuditLog.installation_id == "test-installation",
                AuditLog.event_type == "automation.email_queued",
            )
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert sent is None or (sent.details or {}).get("to") != "spam@otra.com"
    finally:
        db.close()


def test_email_webhook_fails_closed_without_secret_or_bad_hmac(
    client, auth_headers
) -> None:
    # Sin secreto configurado (default del entorno de test) → 401.
    response = client.post(
        "/commands/email/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_email_webhook_bad_signature_rejected(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", "cmd-email-secret-3"
    )
    payload = {"from": OWNER_EMAIL, "subject": "hola", "text": ""}
    raw = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/commands/email/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Command-Timestamp": str(int(time.time())),
            "X-Command-Signature": "sha256=deadbeef",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# WhatsApp: el número del dueño se resuelve como comando y se responde
# ---------------------------------------------------------------------------

def test_whatsapp_owner_command_replies_inline(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_PHONE", OWNER_PHONE)
    channel_id = _create_channel(client, auth_headers, channel="whatsapp")
    try:
        response = _whatsapp_webhook(
            client, channel_id, phone=OWNER_PHONE, body="¿cómo va el pipeline?"
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "owner_command"
        assert data["intent"] == "pipeline_status"
        assert data["reply_message_id"]

        db = SessionLocal()
        try:
            inbound = (
                db.query(SocialMessage)
                .filter(
                    SocialMessage.channel_id == channel_id,
                    SocialMessage.direction == "in",
                )
                .order_by(SocialMessage.created_at.desc())
                .first()
            )
            assert inbound is not None
            assert inbound.status == "triaged"
            triage = (
                db.query(SocialTriage)
                .filter(SocialTriage.message_id == inbound.id)
                .first()
            )
            assert triage is not None
            assert triage.intent == "command"

            outbound = (
                db.query(SocialMessage)
                .filter(SocialMessage.id == data["reply_message_id"])
                .first()
            )
            assert outbound is not None
            assert outbound.direction == "out"
            assert "pipeline" in (outbound.body or "").lower() or "etapa" in (
                outbound.body or ""
            ).lower()

            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.installation_id == "test-installation",
                    AuditLog.event_type == "ceo_command.whatsapp",
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            details = audit.details or {}
            assert details["intent"] == "pipeline_status"
            assert details["reply_message_id"] == outbound.id
        finally:
            db.close()
    finally:
        _cleanup_channels([channel_id])


def test_whatsapp_unknown_sender_dismissed_silently(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_PHONE", OWNER_PHONE)
    channel_id = _create_channel(client, auth_headers, channel="whatsapp")
    try:
        response = _whatsapp_webhook(
            client, channel_id, phone="+34999000111", body="hola"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ignored"

        db = SessionLocal()
        try:
            inbound = (
                db.query(SocialMessage)
                .filter(
                    SocialMessage.channel_id == channel_id,
                    SocialMessage.direction == "in",
                )
                .order_by(SocialMessage.created_at.desc())
                .first()
            )
            assert inbound is not None
            assert inbound.status == "dismissed"
            assert (
                db.query(SocialMessage)
                .filter(SocialMessage.direction == "out")
                .count()
            ) == 0
            audit = (
                db.query(AuditLog)
                .filter(
                    AuditLog.installation_id == "test-installation",
                    AuditLog.event_type == "ceo_command.whatsapp.ignored",
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert (audit.details or {}).get("reason") == "unknown_sender"
        finally:
            db.close()
    finally:
        _cleanup_channels([channel_id])


def test_whatsapp_surface_disabled_keeps_normal_triage(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "OWNER_COMMAND_PHONE", "")
    channel_id = _create_channel(client, auth_headers, channel="whatsapp")
    try:
        response = _whatsapp_webhook(
            client, channel_id, phone=OWNER_PHONE, body="Quiero un presupuesto"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"
        # Con la superficie desactivada, el mensaje sigue el triaje comercial.
        db = SessionLocal()
        try:
            inbound = (
                db.query(SocialMessage)
                .filter(
                    SocialMessage.channel_id == channel_id,
                    SocialMessage.direction == "in",
                )
                .order_by(SocialMessage.created_at.desc())
                .first()
            )
            assert inbound is not None
            assert inbound.status == "triaged"
            triage = (
                db.query(SocialTriage)
                .filter(SocialTriage.message_id == inbound.id)
                .first()
            )
            assert triage is not None
            assert triage.intent != "command"
        finally:
            db.close()
    finally:
        _cleanup_channels([channel_id])
