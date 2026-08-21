"""Evals T-056: agente de escucha social (Fase 1, P2).

Cubre el módulo de escucha social del plan CRM:

- Adaptadores puros: genérico (JSON+HMAC) y WhatsApp Cloud API (challenge
  por GET, ``X-Hub-Signature-256``, payload ``entry[].changes[]``); canal
  desconocido → fail-closed.
- Triaje determinista: intención (lead/queja/consulta/spam/otra), idioma,
  registro, sentimiento, urgencia, entidades y ``score_social``; misma
  entrada → mismo veredicto (sin red ni LLM).
- Pipeline E2E por API: webhook firmado → mensaje persistido → triaje en el
  outbox durable → lead (dedupe email/teléfono/handle) → actividad follow-up
  con SLA (queja 15 min) → timeline → evento saliente ``social.message_triaged``.
- RBAC y auditoría: canales solo admin (con ``Idempotency-Key``); inbox,
  dismiss y stats operador+; viewer bloqueado.
- Dedupe de reintentos: el mismo ``source_message_id`` nunca duplica mensaje
  ni lead.
- Fusión del score: la señal ``social`` aparece en el scoring del lead.

Hermeticidad D-032: sin red (spool local), SQLite de test y limpieza en
``finally``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    Activity,
    AuditLog,
    Lead,
    SocialChannel,
    SocialMessage,
    SocialTriage,
    User,
)

PORTAL_TEST_PASSWORD = "Portal-Test-123!"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_user(client, auth_headers, username: str, role: str) -> None:
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": PORTAL_TEST_PASSWORD,
            "role": role,
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text


def _login(client, username: str) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"soc-{uuid.uuid4().hex}"}


def _hmac(raw: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()


@pytest.fixture()
def social_env(client, auth_headers):
    """Usuarios de prueba (comercial, viewer, admin) con limpieza."""
    commercial = _unique("comercial-soc")
    viewer = _unique("viewer-soc")
    admin = _unique("admin-soc")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    _create_user(client, auth_headers, admin, "client_admin")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "admin_token": _login(client, admin)["access_token"],
        "commercial_token": _login(client, commercial)["access_token"],
        "viewer_token": _login(client, viewer)["access_token"],
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(
                User.username.in_([commercial, viewer, admin])
            ).delete()
            db.commit()
        finally:
            db.close()


def _seed_channel(
    client, env, *, name: str | None = None, channel: str = "generic"
) -> dict:
    """Crea un canal vía API y devuelve el objeto de respuesta + id."""
    response = client.post(
        "/social/channels",
        json={
            "name": name or _unique("canal-soc"),
            "channel": channel,
            "webhook_secret": "test-secret-social-123",
            "verify_token": "verify-me",
        },
        headers={**env["auth_headers"], **_idem()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _channel_row(channel_id: str):
    db = SessionLocal()
    try:
        return db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Adaptadores (puros, sin red)
# ---------------------------------------------------------------------------


def test_generic_adapter_challenge_and_signature(social_env):
    from app.services.social_adapters import GenericSocialAdapter

    adapter = GenericSocialAdapter()
    channel = type(
        "Channel",
        (),
        {"verify_token": "verify-me", "webhook_secret": "s3cret-key"},
    )()

    # Challenge correcto e incorrecto.
    assert adapter.verify_get(channel, {"verify_token": "verify-me", "challenge": "abc"}) == "abc"
    assert adapter.verify_get(channel, {"verify_token": "mal", "challenge": "abc"}) is None

    raw = b'{"source_message_id": "m1", "body": "hola"}'
    good = {"x-bridge-signature": _hmac(raw, "s3cret-key")}
    assert adapter.verify_post(channel, raw, good) is True
    assert adapter.verify_post(channel, raw, {"x-bridge-signature": "deadbeef"}) is False
    assert adapter.verify_post(channel, raw, {}) is False


def test_whatsapp_adapter_challenge_signature_and_parse(social_env):
    from app.services.social_adapters import WhatsAppSocialAdapter

    adapter = WhatsAppSocialAdapter()
    channel = type(
        "Channel",
        (),
        {"verify_token": "meta-token", "webhook_secret": "meta-secret"},
    )()

    assert (
        adapter.verify_get(
            channel,
            {"hub.mode": "subscribe", "hub.verify_token": "meta-token", "hub.challenge": "xyz"},
        )
        == "xyz"
    )
    assert adapter.verify_get(channel, {"hub.mode": "subscribe", "hub.verify_token": "nope"}) is None

    raw = b'{"object": "whatsapp_business_account"}'
    good = {"x-hub-signature-256": f"sha256={_hmac(raw, 'meta-secret')}"}
    assert adapter.verify_post(channel, raw, good) is True
    assert adapter.verify_post(channel, raw, {"x-hub-signature-256": "sha256=bad"}) is False
    assert adapter.verify_post(channel, raw, {}) is False

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
                            "contacts": [{"profile": {"name": "Ana García"}}],
                            "messages": [
                                {
                                    "from": "34600111222",
                                    "id": "wamid.ABC123",
                                    "type": "text",
                                    "text": {"body": "Hola, quiero un presupuesto por favor"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    envelope = adapter.parse(payload)
    assert envelope.source_message_id == "wamid.ABC123"
    assert envelope.sender_name == "Ana García"
    assert envelope.phone == "34600111222"
    assert "presupuesto" in envelope.body

    # Tipos no-texto se descartan (fail-closed).
    no_text = json.loads(json.dumps(payload))
    no_text["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "image"
    with pytest.raises(ValueError):
        adapter.parse(no_text)


def test_unknown_channel_fails_closed(social_env):
    from app.services.social_adapters import get_adapter

    with pytest.raises(ValueError):
        get_adapter("linkedin")


# ---------------------------------------------------------------------------
# Triaje determinista
# ---------------------------------------------------------------------------


def _triage(body: str, **kwargs):
    from app.services.social_adapters import SocialEnvelope
    from app.services.social_triage import triage_social_message

    envelope = SocialEnvelope(source_message_id="m", body=body, **kwargs)
    return triage_social_message(envelope, channel="whatsapp")


def test_triage_intents_are_deterministic_and_explainable(social_env):
    verdict = _triage("Hola, me gustaría un presupuesto para su catálogo, ¿pueden contactarme?")
    assert verdict["intent"] == "lead"
    assert verdict["decided_by"] == "deterministic"
    assert 40 <= verdict["score_social"] <= 100
    assert verdict["summary"]
    # Determinismo estricto: misma entrada, mismo veredicto.
    assert verdict == _triage("Hola, me gustaría un presupuesto para su catálogo, ¿pueden contactarme?")


def test_triage_complaint_gets_high_urgency(social_env):
    verdict = _triage("Estoy muy enfadado, el pedido llegó roto y NO funciona. Urgente, devolución ya.")
    assert verdict["intent"] == "queja"
    assert verdict["urgency"] >= 40
    assert verdict["sentiment"] < 0


def test_triage_spam_scores_zero(social_env):
    verdict = _triage("GANA un premio gratis ahora!! pincha aquí: http://spam.example")
    assert verdict["intent"] == "spam"
    assert verdict["score_social"] == 0


def test_triage_language_and_register(social_env):
    es = _triage("Hola buenos días, quisiera saber el precio de envío, gracias")
    assert es["language"] == "es"
    assert es["register"] == "formal"
    en = _triage("Hi, I want to know the price and shipping cost please")
    assert en["language"] == "en"
    tut = _triage("Oye, me puedes mandar el presupuesto ya?")
    assert tut["register"] == "tuteo"


def test_triage_extracts_entities(social_env):
    verdict = _triage(
        "Presupuesto por favor, mi correo es ana@empresa.com y el teléfono +34 600 111 222. SKU-1234"
    )
    assert verdict["entities"]["email"] == "ana@empresa.com"
    assert verdict["entities"]["phone"]
    assert "SKU-1234" in verdict["entities"]["skus"]


# ---------------------------------------------------------------------------
# Pipeline E2E por API (canal genérico + WhatsApp simulado)
# ---------------------------------------------------------------------------


def test_channel_crud_rbac_and_idempotency(social_env):
    client = social_env["client"]
    # viewer y commercial no pueden crear canales.
    assert (
        client.post(
            "/social/channels",
            json={"name": _unique("nope"), "channel": "generic", "webhook_secret": "12345678"},
            headers=_auth(social_env["viewer_token"]),
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/social/channels",
            json={"name": _unique("nope"), "channel": "generic", "webhook_secret": "12345678"},
            headers=_auth(social_env["commercial_token"]),
        ).status_code
        == 403
    )
    # Admin crea (201), replay con la misma key devuelve el mismo canal.
    payload = {
        "name": _unique("canal-rbac"),
        "channel": "generic",
        "webhook_secret": "test-secret-social-123",
        "verify_token": "verify-me",
    }
    key = _idem()
    first = client.post(
        "/social/channels", json=payload, headers={**social_env["auth_headers"], **key}
    )
    assert first.status_code == 201, first.text
    channel_id = first.json()["id"]
    replay = client.post(
        "/social/channels", json=payload, headers={**social_env["auth_headers"], **key}
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == channel_id
    # Duplicado con otra key → 409.
    dup = client.post(
        "/social/channels", json=payload, headers={**social_env["auth_headers"], **_idem()}
    )
    assert dup.status_code == 409
    # El secreto NUNCA se expone.
    listed = client.get("/social/channels", headers=social_env["auth_headers"])
    assert listed.status_code == 200
    channel_row = next(item for item in listed.json()["items"] if item["id"] == channel_id)
    assert channel_row["secret_set"] is True
    assert "webhook_secret" not in channel_row
    assert "verify_token" not in channel_row
    # Patch y delete (sin mensajes → borrado duro).
    patched = client.patch(
        f"/social/channels/{channel_id}",
        json={"is_active": False},
        headers=social_env["auth_headers"],
    )
    assert patched.status_code == 200 and patched.json()["is_active"] is False
    deleted = client.delete(
        f"/social/channels/{channel_id}", headers=social_env["auth_headers"]
    )
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True


def _generic_webhook_payload(
    *, body: str, source_id: str | None = None, **extra
) -> bytes:
    payload = {
        "source_message_id": source_id or f"m-{uuid.uuid4().hex}",
        "body": body,
        **extra,
    }
    return json.dumps(payload).encode("utf-8")


def test_webhook_pipeline_generic_full_cycle(social_env):
    client = social_env["client"]
    channel = _seed_channel(client, social_env)
    channel_id = channel["id"]
    raw = _generic_webhook_payload(
        body="Hola, me interesa su catálogo, ¿pueden enviarme un presupuesto?",
        email="cliente.social@example.com",
    )
    response = client.post(
        f"/social/webhook/{channel_id}",
        content=raw,
        headers={"Content-Type": "application/json", "X-Bridge-Signature": _hmac(raw, "test-secret-social-123")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"

    db = SessionLocal()
    try:
        message = (
            db.query(SocialMessage)
            .filter(SocialMessage.channel_id == channel_id)
            .first()
        )
        assert message is not None
        assert message.status == "triaged"
        triage = (
            db.query(SocialTriage)
            .filter(SocialTriage.message_id == message.id)
            .first()
        )
        assert triage is not None and triage.intent == "lead"
        lead = db.query(Lead).filter(Lead.id == message.lead_id).first()
        assert lead is not None
        assert lead.source == "social"
        assert lead.email == "cliente.social@example.com"
        activity = (
            db.query(Activity)
            .filter(Activity.lead_id == lead.id, Activity.created_by == "system:social")
            .first()
        )
        assert activity is not None
        assert activity.kind == "follow_up" and activity.status == "pending"
        assert activity.due_at is not None
        # Timeline: el mensaje social aparece.
        lead_audit = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "social.message_triaged")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert lead_audit is not None
        assert lead_audit.details.get("lead_id") == lead.id
        # Dedupe de reintentos: mismo source_message_id → duplicate, sin lead extra.
        replay = client.post(
            f"/social/webhook/{channel_id}",
            content=raw,
            headers={"Content-Type": "application/json", "X-Bridge-Signature": _hmac(raw, "test-secret-social-123")},
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "duplicate"
        assert db.query(Lead).filter(Lead.email == "cliente.social@example.com").count() == 1
    finally:
        db.close()


def test_webhook_requires_valid_hmac(social_env):
    client = social_env["client"]
    channel = _seed_channel(client, social_env)
    raw = _generic_webhook_payload(body="Hola")
    bad = client.post(
        f"/social/webhook/{channel['id']}",
        content=raw,
        headers={"X-Bridge-Signature": "deadbeef"},
    )
    assert bad.status_code == 401
    no_sig = client.post(
        f"/social/webhook/{channel['id']}",
        content=raw,
        headers={},
    )
    assert no_sig.status_code == 401
    # Nada se persiste con firma inválida.
    db = SessionLocal()
    try:
        assert (
            db.query(SocialMessage)
            .filter(SocialMessage.channel_id == channel["id"])
            .count()
            == 0
        )
    finally:
        db.close()


def test_whatsapp_webhook_pipeline(social_env):
    client = social_env["client"]
    channel = _seed_channel(client, social_env, channel="whatsapp")
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "999",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "456"},
                            "contacts": [{"profile": {"name": "Carlos Ruiz"}}],
                            "messages": [
                                {
                                    "from": "34600111222",
                                    "id": "wamid.E2E001",
                                    "type": "text",
                                    "text": {"body": "Estoy muy enfadado, el pedido llegó roto. Urgente."},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    response = client.post(
        f"/social/webhook/{channel['id']}",
        content=raw,
        headers={"X-Hub-Signature-256": f"sha256={_hmac(raw, 'test-secret-social-123')}"},
    )
    assert response.status_code == 200, response.text
    db = SessionLocal()
    try:
        message = (
            db.query(SocialMessage)
            .filter(SocialMessage.source_message_id == "wamid.E2E001")
            .first()
        )
        assert message is not None and message.status == "triaged"
        triage = (
            db.query(SocialTriage)
            .filter(SocialTriage.message_id == message.id)
            .first()
        )
        assert triage is not None and triage.intent == "queja"
        assert triage.language == "es"
        # SLA de queja: 15 minutos.
        lead = db.query(Lead).filter(Lead.id == message.lead_id).first()
        activity = (
            db.query(Activity)
            .filter(Activity.lead_id == lead.id, Activity.created_by == "system:social")
            .order_by(Activity.created_at.desc())
            .first()
        )
        assert activity is not None and activity.due_at is not None
        delta = (activity.due_at - activity.created_at).total_seconds()
        assert 14 * 60 <= delta <= 16 * 60
    finally:
        db.close()


def test_inbox_dismiss_and_stats_rbac(social_env):
    client = social_env["client"]
    channel = _seed_channel(client, social_env)
    raw = _generic_webhook_payload(body="Hola, quiero comprar ya por favor")
    client.post(
        f"/social/webhook/{channel['id']}",
        content=raw,
        headers={"X-Bridge-Signature": _hmac(raw, "test-secret-social-123")},
    )
    db = SessionLocal()
    try:
        message = (
            db.query(SocialMessage)
            .filter(SocialMessage.channel_id == channel["id"])
            .first()
        )
        message_id = message.id
    finally:
        db.close()

    # viewer no puede ver el inbox ni descartar.
    assert client.get("/social/inbox", headers=_auth(social_env["viewer_token"])).status_code == 403
    assert (
        client.post(
            f"/social/messages/{message_id}/dismiss", headers=_auth(social_env["viewer_token"])
        ).status_code
        == 403
    )
    # comercial (operador) sí.
    inbox = client.get("/social/inbox", headers=_auth(social_env["commercial_token"]))
    assert inbox.status_code == 200
    items = inbox.json()["items"]
    assert any(item["id"] == message_id for item in items)
    detail = next(item for item in items if item["id"] == message_id)
    assert detail["triage"] is not None and detail["triage"]["intent"] == "lead"
    # Filtro por intent.
    only_leads = client.get(
        "/social/inbox?intent=lead", headers=_auth(social_env["commercial_token"])
    )
    assert any(item["id"] == message_id for item in only_leads.json()["items"])
    only_spam = client.get(
        "/social/inbox?intent=spam", headers=_auth(social_env["commercial_token"])
    )
    assert not any(item["id"] == message_id for item in only_spam.json()["items"])
    # Dismiss auditado.
    dismissed = client.post(
        f"/social/messages/{message_id}/dismiss", headers=_auth(social_env["commercial_token"])
    )
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    stats = client.get("/social/stats", headers=_auth(social_env["commercial_token"]))
    assert stats.status_code == 200
    assert stats.json()["by_status"].get("dismissed") == 1


def test_social_score_fuses_into_lead_score(social_env):
    client = social_env["client"]
    channel = _seed_channel(client, social_env)
    raw = _generic_webhook_payload(
        body="Hola, quiero comprar su catálogo, mi email es lead.score@example.com",
    )
    client.post(
        f"/social/webhook/{channel['id']}",
        content=raw,
        headers={"X-Bridge-Signature": _hmac(raw, "test-secret-social-123")},
    )
    db = SessionLocal()
    try:
        lead = (
            db.query(Lead).filter(Lead.email == "lead.score@example.com").first()
        )
        assert lead is not None
    finally:
        db.close()
    scored = client.get(f"/leads/{lead.id}/score", headers=social_env["auth_headers"])
    assert scored.status_code == 200, scored.text
    signals = scored.json()["signals"]
    assert any(signal["kind"] == "social" for signal in signals)
