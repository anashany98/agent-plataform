"""Evals P2-f: webhooks salientes de eventos CRM (T-044).

Cubre el módulo de suscripciones a webhooks salientes:

- ``GET /webhooks/subscriptions`` lista las suscripciones con el secreto
  oculto (solo ``secret_set``/``secret_prefix``) y el catálogo de eventos.
- ``POST /webhooks/subscriptions`` crea (solo admin, auditado, idempotente):
  valida eventos contra el catálogo y rechaza URLs de redes privadas/
  loopback (sin DNS en CRUD — la resolución real ocurre en el dispatcher).
- ``PATCH/DELETE /webhooks/subscriptions/{id}`` edita/elimina (solo admin,
  auditado); ``secret`` vacío en PATCH conserva el existente.
- ``POST /webhooks/subscriptions/{id}/test`` encola un ``webhook.test`` por
  el outbox durable sin tocar red en el request.
- Al producirse eventos CRM (``lead.created``, ``lead.assigned``,
  ``pipeline.stage_changed``, ``quote.confirmed``) se encola un mensaje del
  outbox por suscripción activa en la MISMA transacción que la mutación
  (transactional outbox): un fallo de la mutación descarta el mensaje.
- El dispatcher (unit, sin red real): firma HMAC-SHA256 con el secreto DE LA
  SUSCRIPCIÓN, omita suscripciones inactivas/eliminadas de forma auditable y
  trata el bloqueo SSRF como error permanente (dead-letter), no reintento.

Hermeticidad D-032: sin red (``guarded_request_with_retry`` y
``httpx.AsyncClient`` se simulan en el test del dispatcher; el worker del
outbox está deshabilitado en tests, los mensajes quedan ``pending``), con
usuarios y filas únicos por ejecución y limpieza en ``finally``.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.installation_context import installation_scope
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    InvoiceDraft,
    Lead,
    Opportunity,
    Order,
    OutboxMessage,
    Quote,
    StockReservation,
    User,
    WebhookSubscription,
)
from app.services.crm_webhooks import CRM_WEBHOOK_TOPIC, dispatch_crm_webhook
from app.services.outbox import OutboxPermanentError, OutboxService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "test-installation"
PORTAL_TEST_PASSWORD = "Portal-Test-123!"
TEST_WEBHOOK_URL = "https://public.test/hook"
TEST_SECRET = "subscription-secret-16ch"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


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


def _seed_lead() -> str:
    db = SessionLocal()
    try:
        lead = Lead(
            id=f"lead-{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:10]}@example.invalid",
            first_name="Cliente Webhook",
            source="local",
            status="new",
        )
        db.add(lead)
        db.commit()
        return lead.id
    finally:
        db.close()


def _seed_opportunity(lead_id: str, *, stage: str = "new") -> str:
    db = SessionLocal()
    try:
        opportunity = Opportunity(
            id=f"opp-{uuid.uuid4().hex[:8]}",
            lead_id=lead_id,
            external_reference=f"quote-{uuid.uuid4().hex[:6]}",
            name="Oportunidad Webhook",
            monetary_value=Decimal("250.00"),
            currency="EUR",
            pipeline="default",
            stage=stage,
            status="open",
        )
        db.add(opportunity)
        db.commit()
        return opportunity.id
    finally:
        db.close()


def _cleanup_subscription(subscription_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(WebhookSubscription).filter(
            WebhookSubscription.id == subscription_id
        ).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_lead(*, lead_id: str | None = None, opp_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        if opp_id:
            db.query(Opportunity).filter(Opportunity.id == opp_id).delete()
        if lead_id:
            db.query(Lead).filter(Lead.id == lead_id).delete()
        db.commit()
    finally:
        db.close()


def _cleanup_commerce(*, quote_id: str | None = None, order_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        if order_id:
            db.query(StockReservation).filter(
                StockReservation.order_id == order_id
            ).delete(synchronize_session=False)
            invoice = (
                db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).first()
            )
            if invoice:
                db.query(ApprovalRequest).filter(
                    ApprovalRequest.target_key == invoice.id
                ).delete(synchronize_session=False)
                db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice.id).delete(
                    synchronize_session=False
                )
            db.query(Order).filter(Order.id == order_id).delete(synchronize_session=False)
        if quote_id:
            db.query(Quote).filter(Quote.id == quote_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _outbox_messages(event_type: str | None = None) -> list[OutboxMessage]:
    db = SessionLocal()
    try:
        rows = (
            db.query(OutboxMessage)
            .filter(OutboxMessage.topic == CRM_WEBHOOK_TOPIC)
            .order_by(OutboxMessage.created_at.asc())
            .all()
        )
        if event_type is None:
            return rows
        return [
            row for row in rows if (row.payload or {}).get("event_type") == event_type
        ]
    finally:
        db.close()


def _audit_events(event_type: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == event_type)
            .order_by(AuditLog.timestamp.desc())
            .all()
        )
        return [row.details or {} for row in rows]
    finally:
        db.close()


@pytest.fixture()
def webhook_env(client, auth_headers):
    """Crea un comercial de prueba y expone tokens (el admin es el fixture)."""

    commercial = _unique("comercial")
    viewer = _unique("viewer")
    _create_user(client, auth_headers, commercial, "commercial")
    _create_user(client, auth_headers, viewer, "viewer")
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "admin_token": auth_headers["Authorization"].split()[1],
        "commercial_token": _login(client, commercial)["access_token"],
        "viewer_token": _login(client, viewer)["access_token"],
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username.in_([commercial, viewer])).delete()
            db.commit()
        finally:
            db.close()


def _create_subscription(client, token, **overrides) -> dict:
    payload = {
        "name": _unique("hook"),
        "url": TEST_WEBHOOK_URL,
        "secret": TEST_SECRET,
        "events": ["lead.created"],
        "is_active": True,
    }
    payload.update(overrides)
    response = client.post(
        "/webhooks/subscriptions",
        json=payload,
        headers={**_auth(token), **_idem()},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# CRUD de suscripciones
# ---------------------------------------------------------------------------


def test_webhook_subscription_crud_admin_audited(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    subscription = _create_subscription(
        client, token, events=["lead.created", "quote.confirmed"]
    )
    try:
        # El secreto nunca se devuelve; solo marcadores.
        assert "secret" not in subscription
        assert subscription["secret_set"] is True
        assert subscription["secret_prefix"] == TEST_SECRET[:4]
        assert set(subscription["events"]) == {"lead.created", "quote.confirmed"}
        assert subscription["is_active"] is True
        assert any(
            event.get("subscription_id") == subscription["id"]
            for event in _audit_events("webhook_subscription.created")
        )

        listed = client.get("/webhooks/subscriptions", headers=_auth(token)).json()
        row = next(item for item in listed["items"] if item["id"] == subscription["id"])
        assert row["secret_set"] is True
        assert "secret" not in row
        catalog_keys = {event["key"] for event in listed["event_catalog"]}
        assert {"lead.created", "lead.assigned", "pipeline.stage_changed", "quote.confirmed"} <= catalog_keys

        # Un viewer puede leer (lectura), un comercial no muta.
        viewer_list = client.get(
            "/webhooks/subscriptions", headers=_auth(webhook_env["viewer_token"])
        )
        assert viewer_list.status_code == 200

        # PATCH: renombrar, cambiar eventos y desactivar; secret vacío lo conserva.
        updated = client.patch(
            f"/webhooks/subscriptions/{subscription['id']}",
            json={"name": "Hook renombrado", "events": ["pipeline.stage_changed"], "secret": ""},
            headers=_auth(token),
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["name"] == "Hook renombrado"
        assert body["events"] == ["pipeline.stage_changed"]
        assert body["secret_set"] is True  # el vacío no sobreescribe
        assert any(
            event.get("subscription_id") == subscription["id"]
            and "name" in event.get("changed", [])
            for event in _audit_events("webhook_subscription.updated")
        )

        deactivated = client.patch(
            f"/webhooks/subscriptions/{subscription['id']}",
            json={"is_active": False},
            headers=_auth(token),
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False

        deleted = client.delete(
            f"/webhooks/subscriptions/{subscription['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted"] is True
        remaining = client.get("/webhooks/subscriptions", headers=_auth(token)).json()
        assert all(item["id"] != subscription["id"] for item in remaining["items"])
        assert any(
            event.get("subscription_id") == subscription["id"]
            for event in _audit_events("webhook_subscription.deleted")
        )
    finally:
        _cleanup_subscription(subscription["id"])


def test_webhook_subscription_requires_admin_and_idempotency(webhook_env) -> None:
    client = webhook_env["client"]
    payload = {
        "name": _unique("solo_admin"),
        "url": TEST_WEBHOOK_URL,
        "secret": TEST_SECRET,
        "events": ["lead.created"],
    }
    forbidden = client.post(
        "/webhooks/subscriptions",
        json=payload,
        headers=_auth(webhook_env["commercial_token"]),
    )
    assert forbidden.status_code == 403
    missing_key = client.post(
        "/webhooks/subscriptions",
        json=payload,
        headers=_auth(webhook_env["admin_token"]),
    )
    assert missing_key.status_code == 428


def test_webhook_subscription_duplicate_name_conflict(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    first = _create_subscription(client, token, name=_unique("dup"))
    try:
        response = client.post(
            "/webhooks/subscriptions",
            json={
                "name": first["name"],
                "url": TEST_WEBHOOK_URL,
                "secret": TEST_SECRET,
                "events": ["lead.created"],
            },
            headers={**_auth(token), **_idem()},
        )
        assert response.status_code == 409
    finally:
        _cleanup_subscription(first["id"])


def test_webhook_subscription_invalid_events_and_private_url(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    bad_event = client.post(
        "/webhooks/subscriptions",
        json={
            "name": _unique("evento"),
            "url": TEST_WEBHOOK_URL,
            "secret": TEST_SECRET,
            "events": ["lead.teleported"],
        },
        headers={**_auth(token), **_idem()},
    )
    assert bad_event.status_code == 422
    assert "lead.teleported" in bad_event.json()["detail"]
    for blocked in ("http://127.0.0.1:9000/hook", "http://10.0.0.5/hook", "ftp://public.test/x"):
        rejected = client.post(
            "/webhooks/subscriptions",
            json={
                "name": _unique("red"),
                "url": blocked,
                "secret": TEST_SECRET,
                "events": ["lead.created"],
            },
            headers={**_auth(token), **_idem()},
        )
        assert rejected.status_code == 422, (blocked, rejected.text)


def test_webhook_subscription_test_ping_enqueues(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    subscription = _create_subscription(client, token)
    try:
        response = client.post(
            f"/webhooks/subscriptions/{subscription['id']}/test",
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["outbox_id"]
        queued = _outbox_messages(event_type="webhook.test")
        assert any(
            message.id == body["outbox_id"]
            and message.payload["subscription_id"] == subscription["id"]
            for message in queued
        )
        assert any(
            event.get("subscription_id") == subscription["id"]
            for event in _audit_events("webhook_subscription.test")
        )
    finally:
        _cleanup_subscription(subscription["id"])


# ---------------------------------------------------------------------------
# Enqueue atómico al producirse eventos CRM
# ---------------------------------------------------------------------------


def test_lead_created_enqueues_webhook(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    lead_sub = _create_subscription(client, token, events=["lead.created"])
    other_sub = _create_subscription(client, token, events=["quote.confirmed"])
    try:
        email = f"{uuid.uuid4().hex[:10]}@example.invalid"
        response = client.post(
            "/leads",
            json={"email": email, "first_name": "Lead Hook"},
            headers={**_auth(token), **_idem()},
        )
        assert response.status_code == 200, response.text
        lead_id = response.json()["id"]

        messages = _outbox_messages(event_type="lead.created")
        matching = [
            message
            for message in messages
            if message.payload.get("data", {}).get("lead_id") == lead_id
        ]
        assert len(matching) == 1
        assert matching[0].payload["subscription_id"] == lead_sub["id"]
        assert matching[0].payload["data"]["email"] == email
        assert matching[0].idempotency_key.endswith(f"lead.created:{lead_id}")
        # La otra suscripción (otro evento) no encoló nada para este lead.
        assert all(
            message.payload["subscription_id"] != other_sub["id"]
            for message in messages
        )
        db = SessionLocal()
        try:
            db.query(Lead).filter(Lead.id == lead_id).delete()
            db.commit()
        finally:
            db.close()
    finally:
        _cleanup_subscription(lead_sub["id"])
        _cleanup_subscription(other_sub["id"])


def test_stage_changed_enqueues_webhook(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    subscription = _create_subscription(client, token, events=["pipeline.stage_changed"])
    lead_id = _seed_lead()
    opp_id = _seed_opportunity(lead_id, stage="new")
    try:
        response = client.patch(
            f"/opportunities/{opp_id}",
            json={"stage": "won"},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["changed"] is True

        messages = _outbox_messages(event_type="pipeline.stage_changed")
        matching = [
            message
            for message in messages
            if message.payload.get("data", {}).get("opportunity_id") == opp_id
        ]
        assert len(matching) == 1
        data = matching[0].payload["data"]
        assert data["stage_from"] == "new"
        assert data["stage_to"] == "won"
        assert data["lead_id"] == lead_id
        assert matching[0].payload["subscription_id"] == subscription["id"]
    finally:
        _cleanup_lead(lead_id=lead_id, opp_id=opp_id)
        _cleanup_subscription(subscription["id"])


def test_lead_assigned_enqueues_webhook(webhook_env) -> None:
    client = webhook_env["client"]
    token = webhook_env["admin_token"]
    subscription = _create_subscription(client, token, events=["lead.assigned"])
    lead_id = _seed_lead()

    # El comercial del fixture es el único usuario ``comercial-*`` de la BD.
    db = SessionLocal()
    try:
        commercial_user = (
            db.query(User)
            .filter(User.username.like("comercial-%"))
            .order_by(User.created_at.desc())
            .first()
        )
        assert commercial_user is not None
        assignee_id = commercial_user.id
    finally:
        db.close()

    try:
        response = client.patch(
            f"/leads/{lead_id}/assign",
            json={"user_id": assignee_id},
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        messages = _outbox_messages(event_type="lead.assigned")
        matching = [
            message
            for message in messages
            if message.payload.get("data", {}).get("lead_id") == lead_id
        ]
        assert len(matching) == 1
        data = matching[0].payload["data"]
        assert data["to_user"] == commercial_user.username
        assert data["from_user"] is None
        assert matching[0].payload["subscription_id"] == subscription["id"]
    finally:
        _cleanup_lead(lead_id=lead_id)
        _cleanup_subscription(subscription["id"])


def test_quote_confirmed_enqueues_webhook(client, auth_headers, webhook_env) -> None:
    """Confirma un presupuesto por API y verifica el mensaje ``quote.confirmed``."""

    token = webhook_env["admin_token"]
    subscription = _create_subscription(webhook_env["client"], token, events=["quote.confirmed"])
    try:
        quote_headers = {**auth_headers, "Idempotency-Key": _idem()["Idempotency-Key"]}
        quote = client.post(
            "/quotes",
            headers=quote_headers,
            json={
                "customer_id": "cust-004",
                "items": [{"product_id": "fixture-industrial-1", "qty": 1}],
            },
        )
        assert quote.status_code == 201, quote.text
        quote_id = quote.json()["quote_id"]

        confirm = client.post(
            f"/quotes/{quote_id}/confirm",
            headers={**auth_headers, "Idempotency-Key": _idem()["Idempotency-Key"]},
            json={"confirmation_token": quote.json()["confirmation_token"]},
        )
        assert confirm.status_code == 200, confirm.text
        order_id = confirm.json()["order_id"]

        messages = _outbox_messages(event_type="quote.confirmed")
        matching = [
            message
            for message in messages
            if message.payload.get("data", {}).get("quote_id") == quote_id
        ]
        assert len(matching) == 1
        data = matching[0].payload["data"]
        assert data["order_id"] == order_id
        assert data["customer_id"] == "cust-004"
        assert data["customer_email"] == "customer-004@example.invalid"
        assert float(data["total_amount"]) > 0
        assert matching[0].payload["subscription_id"] == subscription["id"]
        _cleanup_commerce(quote_id=quote_id, order_id=order_id)
    finally:
        _cleanup_subscription(subscription["id"])


# ---------------------------------------------------------------------------
# Dispatcher (unit, sin red real)
# ---------------------------------------------------------------------------


@pytest.fixture()
def webhook_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.models.models import Base as ModelsBase

    ModelsBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with installation_scope(INSTALLATION_ID):
        db = factory()
        try:
            yield db
        finally:
            db.close()
    engine.dispose()


def _seed_subscription_in(db, **overrides) -> WebhookSubscription:
    subscription = WebhookSubscription(
        id=f"sub-{uuid.uuid4().hex[:8]}",
        name=_unique("hook"),
        url=TEST_WEBHOOK_URL,
        secret=TEST_SECRET,
        events=["lead.created"],
        is_active=True,
    )
    for key, value in overrides.items():
        setattr(subscription, key, value)
    db.add(subscription)
    db.commit()
    return subscription


def test_dispatch_sends_signed_payload(webhook_db, monkeypatch) -> None:
    """Firma HMAC-SHA256 con el secreto de la SUSCRIPCIÓN y envía por HTTP."""

    from app.services import crm_webhooks
    from app.services.automations import sign_webhook_payload

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def request(self, method, url, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

    async def fake_guarded(breaker_name, operation):
        captured["breaker"] = breaker_name
        return await operation()

    monkeypatch.setattr(crm_webhooks, "guarded_request_with_retry", fake_guarded)
    monkeypatch.setattr(
        crm_webhooks.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient()
    )
    # Allowlist para que el validador SSRF no resuelva DNS en el test.
    monkeypatch.setattr(
        crm_webhooks.settings,
        "WEBHOOK_OUTBOUND_ALLOWED_HOSTS",
        "public.test",
        raising=False,
    )

    subscription = _seed_subscription_in(webhook_db, secret="sub-secret-16chars!!")
    message, _ = OutboxService(webhook_db).enqueue(
        topic=CRM_WEBHOOK_TOPIC,
        idempotency_key="wh-dispatch-1",
        payload={
            "subscription_id": subscription.id,
            "event_type": "lead.created",
            "entity_id": "L1",
            "occurrence_id": "L1",
            "data": {"email": "cliente@example.invalid", "first_name": "Cliente"},
        },
    )
    result = asyncio.run(dispatch_crm_webhook(message))
    assert result["status"] == "sent", result
    assert result["accepted"] is True
    assert captured["breaker"] == "webhook"
    assert captured["url"] == subscription.url
    expected = "sha256=" + sign_webhook_payload(captured["content"], subscription.secret)
    assert captured["headers"]["X-Bridge-Webhook-Signature"] == expected
    assert captured["headers"]["X-Bridge-Webhook-Id"] == message.idempotency_key
    assert captured["headers"]["X-Bridge-Webhook-Key-Id"] == "subscription"


def test_dispatch_skips_inactive_and_deleted(webhook_db) -> None:
    inactive = _seed_subscription_in(webhook_db, is_active=False)
    gone = _seed_subscription_in(webhook_db, is_active=True)

    message_inactive, _ = OutboxService(webhook_db).enqueue(
        topic=CRM_WEBHOOK_TOPIC,
        idempotency_key="wh-inactive-1",
        payload={
            "subscription_id": inactive.id,
            "event_type": "lead.created",
            "entity_id": "L1",
            "occurrence_id": "L1",
            "data": {},
        },
    )
    result = asyncio.run(dispatch_crm_webhook(message_inactive))
    assert result["status"] == "skipped"
    assert result["reason"] == "subscription_inactive"

    # Eliminada tras encolar: los mensajes pendientes se omiten, no se envían.
    webhook_db.delete(gone)
    webhook_db.commit()
    message_gone, _ = OutboxService(webhook_db).enqueue(
        topic=CRM_WEBHOOK_TOPIC,
        idempotency_key="wh-gone-1",
        payload={
            "subscription_id": gone.id,
            "event_type": "lead.created",
            "entity_id": "L1",
            "occurrence_id": "L1",
            "data": {},
        },
    )
    result_gone = asyncio.run(dispatch_crm_webhook(message_gone))
    assert result_gone["status"] == "skipped"
    assert result_gone["reason"] == "subscription_gone"


def test_dispatch_ssrf_rejection_is_permanent(webhook_db) -> None:
    """Una URL de red privada se rechaza en el dispatcher como error permanente."""

    subscription = _seed_subscription_in(webhook_db, url="http://127.0.0.1:9/hook")
    message, _ = OutboxService(webhook_db).enqueue(
        topic=CRM_WEBHOOK_TOPIC,
        idempotency_key="wh-ssrf-1",
        payload={
            "subscription_id": subscription.id,
            "event_type": "lead.created",
            "entity_id": "L1",
            "occurrence_id": "L1",
            "data": {},
        },
    )
    with pytest.raises(OutboxPermanentError):
        asyncio.run(dispatch_crm_webhook(message))
