"""Evals D-021: circuit breakers, outbox durable y dead-letter queue.

Hermetismo: ninguna prueba toca servicios externos. Las averías de proveedor
se simulan con inyección de fallos sobre los adaptadores; los relojes de los
breakers y los retardos de retry se controlan explícitamente.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
import pytest
from app import main as bridge_main
from app.config import settings
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import (
    AuditLog,
    IdempotencyRecord,
    OutboxMessage,
    Product,
    utcnow,
)
from app.security import Principal, get_current_principal
from app.services import ghl_adapter as ghl_module
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError
from app.services.outbox import (
    OutboxPermanentError,
    OutboxService,
    OutboxTransientError,
)
from app.services.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    get_breaker,
    guarded_request_with_retry,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "test-installation"


class _FakeClock:
    def __init__(self, start: dt.datetime) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


def _http_request() -> httpx.Request:
    return httpx.Request("POST", "https://provider.invalid/fault-injection")


def _response(status_code: int, payload: dict[str, Any] | None = None) -> httpx.Response:
    if payload is None:
        return httpx.Response(status_code, request=_http_request())
    return httpx.Response(status_code, request=_http_request(), json=payload)


# --------------------------------------------------------------------------
# Circuit breaker: máquina de estados
# --------------------------------------------------------------------------


def test_breaker_opens_after_threshold_and_fails_fast() -> None:
    clock = _FakeClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    breaker = CircuitBreaker("fault-threshold", failure_threshold=3, recovery_sec=30, clock=clock)

    for _ in range(2):
        breaker.record_failure()
    assert breaker.state() == "closed"
    assert breaker.allow_request()

    breaker.record_failure()
    assert breaker.state() == "open"
    assert not breaker.allow_request()
    assert 29.0 <= breaker.retry_after_seconds() <= 30.0


def test_breaker_half_open_success_closes_circuit() -> None:
    clock = _FakeClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    breaker = CircuitBreaker("fault-recovery", failure_threshold=1, recovery_sec=10, clock=clock)

    breaker.record_failure()
    assert breaker.state() == "open"

    clock.advance(11)
    assert breaker.state() == "half_open"
    assert breaker.allow_request()

    breaker.record_success()
    assert breaker.state() == "closed"
    assert breaker.to_dict()["consecutive_failures"] == 0


def test_breaker_half_open_failure_reopens_with_full_timer() -> None:
    clock = _FakeClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    breaker = CircuitBreaker("fault-reopen", failure_threshold=1, recovery_sec=10, clock=clock)

    breaker.record_failure()
    clock.advance(11)
    assert breaker.state() == "half_open"

    breaker.record_failure()
    assert breaker.state() == "open"
    assert breaker.retry_after_seconds() > 9.0


# --------------------------------------------------------------------------
# Circuit breaker integrado con retry HTTP
# --------------------------------------------------------------------------


def _zero_retry_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INTEGRATION_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "INTEGRATION_RETRY_BASE_DELAY_SEC", 0.0)
    monkeypatch.setattr(settings, "INTEGRATION_RETRY_MAX_DELAY_SEC", 0.0)


def test_guarded_retry_counts_failures_and_fails_fast_when_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _zero_retry_delays(monkeypatch)
    attempts: list[int] = []

    async def failing():
        attempts.append(1)
        raise httpx.ConnectError("provider down", request=_http_request())

    with pytest.raises(httpx.ConnectError):
        asyncio.run(guarded_request_with_retry("fault-guarded", failing))
    assert len(attempts) == 3
    breaker = get_breaker("fault-guarded")
    assert breaker.state() == "open"

    with pytest.raises(CircuitOpenError):
        asyncio.run(guarded_request_with_retry("fault-guarded", failing))
    assert len(attempts) == 3, "El circuito abierto debe fallar rápido sin tocar el proveedor"


def test_non_retryable_response_counts_as_provider_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    _zero_retry_delays(monkeypatch)
    breaker = get_breaker("fault-liveness")
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.to_dict()["consecutive_failures"] == 2

    async def not_found():
        return _response(404)

    response = asyncio.run(guarded_request_with_retry("fault-liveness", not_found))
    assert response.status_code == 404
    assert breaker.state() == "closed"
    assert breaker.to_dict()["consecutive_failures"] == 0


class _NetworkGuardClient:
    """Cliente httpx falso que falla si alguien intenta usarlo."""

    async def __aenter__(self) -> "_NetworkGuardClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def request(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("Un circuito abierto no debe llegar a la red")

    async def post(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("Un circuito abierto no debe llegar a la red")


def test_ghl_adapter_open_circuit_fails_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    breaker = get_breaker("ghl")
    for _ in range(int(settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD)):
        breaker.record_failure()
    assert breaker.state() == "open"

    monkeypatch.setattr(ghl_module.httpx, "AsyncClient", lambda *_a, **_k: _NetworkGuardClient())
    adapter = GHLAdapter()
    adapter.token = "fault-injection-token"
    adapter.location_id = "fault-injection-location"

    with pytest.raises(GHLIntegrationError) as excinfo:
        asyncio.run(adapter.upsert_contact(email="circuit@example.invalid", first_name="Circuit"))
    assert "Circuito" in str(excinfo.value)


# --------------------------------------------------------------------------
# Outbox: servicio durable con reintentos acotados y DLQ
# --------------------------------------------------------------------------


@pytest.fixture
def outbox_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with installation_scope(INSTALLATION_ID):
        db = factory()
        try:
            yield db
        finally:
            db.close()
    engine.dispose()


def test_outbox_enqueue_is_idempotent(outbox_db) -> None:
    service = OutboxService(outbox_db)
    first, created_first = service.enqueue(topic="t.test", idempotency_key="k1", payload={"v": 1})
    second, created_second = service.enqueue(topic="t.test", idempotency_key="k1", payload={"v": 2})
    third, created_third = service.enqueue(topic="t.test", idempotency_key="k2", payload={"v": 3})

    assert created_first is True
    assert created_second is False
    assert created_third is True
    assert first.id == second.id
    assert third.id != first.id
    assert service.counts()["pending"] == 2


def test_outbox_success_marks_sent_and_audits(outbox_db) -> None:
    service = OutboxService(outbox_db)
    message, _ = service.enqueue(topic="t.ok", idempotency_key="ok-1", payload={"v": 1})

    async def dispatcher(_message: OutboxMessage) -> dict[str, Any]:
        return {"external_id": "ext-1"}

    asyncio.run(service.deliver(message, dispatcher))
    assert message.state == "sent"
    assert message.response_body == {"external_id": "ext-1"}
    assert message.sent_at is not None
    sent_audits = [
        row
        for row in outbox_db.query(AuditLog).filter(AuditLog.event_type == "outbox_sent").all()
        if (row.details or {}).get("outbox_id") == message.id
    ]
    assert sent_audits, "El envío debe quedar auditado"

    async def explode(_message: OutboxMessage) -> dict[str, Any]:
        raise AssertionError("Un mensaje enviado no debe redespacharse")

    asyncio.run(service.deliver(message, explode))
    assert message.state == "sent"


def test_outbox_transient_failures_schedule_backoff_then_dlq(outbox_db) -> None:
    service = OutboxService(outbox_db)
    message, _ = service.enqueue(topic="t.flaky", idempotency_key="flaky-1", payload={})

    async def down(_message: OutboxMessage) -> dict[str, Any]:
        raise OutboxTransientError("provider unavailable")

    before = utcnow()
    asyncio.run(service.deliver(message, down))
    assert message.state == "pending"
    assert message.attempt_count == 1
    assert message.next_attempt_at > before

    summary_first = asyncio.run(
        service.process_due(dispatchers={"t.flaky": down}, now=utcnow() + dt.timedelta(seconds=60))
    )
    assert summary_first["retry_scheduled"] == 1
    assert message.attempt_count == 2

    summary_last = asyncio.run(
        service.process_due(dispatchers={"t.flaky": down}, now=utcnow() + dt.timedelta(seconds=120))
    )
    assert summary_last["dead"] == 1
    assert message.state == "dead"
    assert message.attempt_count == 3
    assert message.last_error["type"] == "OutboxTransientError"
    assert not message.last_error.get("permanent")
    assert service.counts()["dead"] == 1


def test_outbox_permanent_failure_goes_directly_to_dlq(outbox_db) -> None:
    service = OutboxService(outbox_db)
    message, _ = service.enqueue(topic="t.invalid", idempotency_key="invalid-1", payload={})

    async def invalid(_message: OutboxMessage) -> dict[str, Any]:
        raise OutboxPermanentError("invalid payload")

    asyncio.run(service.deliver(message, invalid))
    assert message.state == "dead"
    assert message.attempt_count == 0
    assert message.last_error["permanent"] is True
    dead_audits = [
        row
        for row in outbox_db.query(AuditLog).filter(AuditLog.event_type == "outbox_dead").all()
        if (row.details or {}).get("outbox_id") == message.id
    ]
    assert dead_audits and dead_audits[0].details["permanent"] is True


def test_outbox_retry_dead_requeues_and_redelivers(outbox_db) -> None:
    service = OutboxService(outbox_db)
    message, _ = service.enqueue(topic="t.retry", idempotency_key="retry-1", payload={})

    async def broken(_message: OutboxMessage) -> dict[str, Any]:
        raise OutboxPermanentError("boom")

    asyncio.run(service.deliver(message, broken))
    assert message.state == "dead"

    with pytest.raises(LookupError):
        service.retry_dead("missing-id")

    requeued = service.retry_dead(message.id)
    assert requeued.state == "pending"
    assert requeued.attempt_count == 0
    assert requeued.next_attempt_at <= utcnow()

    async def healthy(_message: OutboxMessage) -> dict[str, Any]:
        return {"ok": True}

    summary = asyncio.run(service.process_due(dispatchers={"t.retry": healthy}))
    assert summary["sent"] == 1
    assert message.state == "sent"

    with pytest.raises(ValueError):
        service.retry_dead(message.id)


def test_outbox_unknown_topic_is_skipped_not_lost(outbox_db) -> None:
    service = OutboxService(outbox_db)
    message, _ = service.enqueue(topic="t.unknown", idempotency_key="u-1", payload={})

    summary = asyncio.run(service.process_due(dispatchers={}))
    assert summary["skipped"] == 1
    assert summary["sent"] == 0
    assert message.state == "pending", "Un tema sin dispatcher no puede perderse ni marcarse muerto"


def test_outbox_backoff_is_deterministic_and_bounded() -> None:
    assert OutboxService.backoff_seconds(1) == pytest.approx(0.01)
    assert OutboxService.backoff_seconds(2) == pytest.approx(0.02)
    assert OutboxService.backoff_seconds(3) == pytest.approx(0.04)
    assert OutboxService.backoff_seconds(20) == pytest.approx(0.05)


# --------------------------------------------------------------------------
# Endpoints HTTP de outbox: roles y E2E de resiliencia del webhook
# --------------------------------------------------------------------------


@dataclass
class IsolatedApi:
    client: TestClient
    engine: Engine
    session_factory: sessionmaker


@pytest.fixture
def isolated_api() -> IsolatedApi:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def isolated_db():
        with installation_scope(INSTALLATION_ID):
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

    principal = Principal(
        user_id="resilience-admin",
        username="resilience-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="resilience-jti",
    )
    previous_db_override = app.dependency_overrides.get(get_db)
    previous_principal_override = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_principal] = lambda: principal
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield IsolatedApi(client=client, engine=engine, session_factory=session_factory)
    finally:
        client.close()
        if previous_db_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_db_override
        if previous_principal_override is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = previous_principal_override
        engine.dispose()


@contextmanager
def _isolated_session(api: IsolatedApi):
    with installation_scope(INSTALLATION_ID):
        db = api.session_factory()
        try:
            yield db
        finally:
            db.close()


def test_outbox_endpoints_are_role_gated(isolated_api: IsolatedApi) -> None:
    suffix = uuid.uuid4().hex[:10]
    with _isolated_session(isolated_api) as db:
        dead = OutboxMessage(
            topic=bridge_main.GHL_LEAD_OUTBOX_TOPIC,
            idempotency_key=f"dlq-{suffix}",
            payload={"email": f"dlq-{suffix}@example.invalid"},
            state="dead",
            attempt_count=3,
            max_attempts=3,
            last_error={"type": "OutboxTransientError", "message": "fault injection"},
        )
        db.add(dead)
        db.commit()
        dead_id = dead.id

    response = isolated_api.client.get("/outbox", params={"state": "dead"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(item["id"] == dead_id for item in body["items"])
    assert body["counts"]["dead"] >= 1

    response = isolated_api.client.post(f"/outbox/{dead_id}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "requeued"

    response = isolated_api.client.post(f"/outbox/{dead_id}/retry")
    assert response.status_code == 409, "Solo los mensajes de la DLQ pueden reencolarse"

    response = isolated_api.client.post("/outbox/does-not-exist/retry")
    assert response.status_code == 404

    response = isolated_api.client.get("/outbox", params={"state": "bogus"})
    assert response.status_code == 422

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    viewer = Principal(
        user_id="resilience-viewer",
        username="resilience-viewer",
        role="viewer",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="resilience-viewer-jti",
    )
    previous_principal_override = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_current_principal] = lambda: viewer
    try:
        assert isolated_api.client.get("/outbox").status_code == 403
        assert isolated_api.client.post("/outbox/process").status_code == 403
        assert isolated_api.client.post(f"/outbox/{dead_id}/retry").status_code == 403
    finally:
        if previous_principal_override is not None:
            app.dependency_overrides[get_current_principal] = previous_principal_override


def test_outbox_endpoints_require_authentication(client) -> None:
    assert client.get("/outbox").status_code == 401
    assert client.post("/outbox/process").status_code == 401
    assert client.post("/outbox/abc/retry").status_code == 401


def test_metrics_expose_outbox_and_circuit_breakers(isolated_api: IsolatedApi) -> None:
    response = isolated_api.client.get("/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["outbox"]) >= {"pending", "processing", "sent", "dead", "total"}
    assert isinstance(body["circuit_breakers"], dict)


def _signed_chatwoot_request(client: TestClient, payload: dict[str, Any]):
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(dt.datetime.now(dt.UTC).timestamp()))
    signature = hmac.new(
        bridge_main.settings.CHATWOOT_WEBHOOK_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/chatwoot",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )


def _seed_resilience_product(api: IsolatedApi) -> None:
    with _isolated_session(api) as db:
        db.add(
            Product(
                id="prod-resilience",
                external_id="prod-resilience",
                sku="SKU-RES-0001",
                name="Valvula Resiliencia",
                description="Fixture sintético para pruebas de resiliencia.",
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("85.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=50,
                reserved_stock=0,
            )
        )
        db.commit()


def _configure_ghl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_main.ghl_adapter, "token", "fault-injection-token")
    monkeypatch.setattr(bridge_main.ghl_adapter, "location_id", "fault-injection-location")


def _webhook_payload(suffix: str, email: str) -> dict[str, Any]:
    return {
        "event": "message_created",
        "id": f"res-{suffix}",
        "message_type": "incoming",
        "content": "Necesito 2 unidades de valvula resiliencia",
        "private": False,
        "account": {"id": 4242},
        "conversation": {"id": 5252},
        "sender": {"id": 9, "name": "Lead Resiliencia", "email": email},
    }


def test_webhook_ghl_outage_queues_lead_and_outbox_recovers(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resilience_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []

    async def capture_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_chatwoot)
    _configure_ghl(monkeypatch)

    async def ghl_down(**_kwargs: Any) -> dict[str, Any]:
        raise GHLIntegrationError("avería GHL inyectada")

    monkeypatch.setattr(bridge_main.ghl_adapter, "upsert_contact", ghl_down)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-res-{suffix[:10]}@example.com")

    response = _signed_chatwoot_request(isolated_api.client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "quote_created"
    assert body["lead"]["status"] == "queued_for_retry", (
        "Una avería de GHL debe encolar el lead en el outbox, nunca perderlo"
    )
    outbox_id = body["lead"]["outbox_id"]
    assert outbound and any("Presupuesto" in str(item[1].get("content") or "") for item in outbound), (
        "La respuesta comercial al cliente debe salir aunque GHL esté caído"
    )

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        assert message.state == "pending"
        assert message.attempt_count == 1
        assert message.topic == bridge_main.GHL_LEAD_OUTBOX_TOPIC
        queued_audits = db.query(AuditLog).filter(
            AuditLog.event_type == "ghl_lead",
            AuditLog.status == "queued_for_retry",
        ).all()
        assert any((row.details or {}).get("outbox_id") == outbox_id for row in queued_audits)
        claim = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == f"chatwoot:4242:{payload['id']}"
        ).one()
        assert claim.state == "completed", "El webhook debe cerrarse aunque el lead quede encolado"
        message.next_attempt_at = utcnow() - dt.timedelta(seconds=5)
        db.commit()

    calls = {"contact": 0, "opportunity": 0, "note": 0}

    async def upsert_ok(**_kwargs: Any) -> dict[str, Any]:
        calls["contact"] += 1
        return {"contact": {"id": "lead-contact-1"}}

    async def opportunity_ok(**_kwargs: Any) -> dict[str, Any]:
        calls["opportunity"] += 1
        return {"id": "opp-res-1"}

    async def note_ok(_contact_id: str, _note_body: str) -> dict[str, Any]:
        calls["note"] += 1
        return {"id": "note-res-1"}

    async def no_existing_opportunity(**_kwargs: Any) -> None:
        return None

    async def no_existing_note(_contact_id: str, _body: str) -> None:
        return None

    monkeypatch.setattr(bridge_main.ghl_adapter, "upsert_contact", upsert_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "create_opportunity", opportunity_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "add_note", note_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_opportunity_by_reference", no_existing_opportunity)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_note_by_body", no_existing_note)

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200, response.text
    assert response.json()["sent"] == 1

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        assert message.state == "sent"
        assert message.sent_at is not None
        checkpoint = (message.payload or {}).get("checkpoint") or {}
        assert checkpoint.get("contact_id") == "lead-contact-1"
        assert checkpoint.get("opportunity") == {"id": "opp-res-1"}
        assert checkpoint.get("note_completed") is True
        assert (message.response_body or {}).get("status") == "success"
        assert calls == {"contact": 1, "opportunity": 1, "note": 1}
        sent_audits = db.query(AuditLog).filter(AuditLog.event_type == "outbox_sent").all()
        assert any((row.details or {}).get("outbox_id") == outbox_id for row in sent_audits)

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200
    assert response.json()["evaluated"] == 0
    assert calls == {"contact": 1, "opportunity": 1, "note": 1}, (
        "Un segundo procesamiento no puede repetir efectos externos ya enviados"
    )


def test_outbox_checkpoint_prevents_duplicate_opportunity(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resilience_product(isolated_api)

    async def silent_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", silent_chatwoot)
    _configure_ghl(monkeypatch)

    opportunities: list[str] = []

    async def upsert_ok(**_kwargs: Any) -> dict[str, Any]:
        return {"contact": {"id": "contact-b"}}

    async def opportunity_ok(**kwargs: Any) -> dict[str, Any]:
        opportunities.append(str(kwargs.get("external_id")))
        return {"id": f"opp-b-{len(opportunities)}"}

    async def note_down(_contact_id: str, _note_body: str) -> dict[str, Any]:
        raise GHLIntegrationError("avería inyectada en la nota")

    async def no_existing_opportunity(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(bridge_main.ghl_adapter, "upsert_contact", upsert_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "create_opportunity", opportunity_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "add_note", note_down)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_opportunity_by_reference", no_existing_opportunity)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-chk-{suffix[:10]}@example.com")
    response = _signed_chatwoot_request(isolated_api.client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["lead"]["status"] == "queued_for_retry"
    outbox_id = response.json()["lead"]["outbox_id"]
    assert len(opportunities) == 1

    with _isolated_session(isolated_api) as db:
        message = db.query(OutboxMessage).filter(OutboxMessage.id == outbox_id).one()
        checkpoint = (message.payload or {}).get("checkpoint") or {}
        assert checkpoint.get("contact_id") == "contact-b"
        assert checkpoint.get("opportunity") == {"id": "opp-b-1"}, (
            "La oportunidad ya creada debe quedar checkpointada en el payload"
        )
        message.next_attempt_at = utcnow() - dt.timedelta(seconds=5)
        db.commit()

    notes: list[str] = []

    async def note_ok(contact_id: str, _note_body: str) -> dict[str, Any]:
        notes.append(contact_id)
        return {"id": "note-b"}

    async def no_existing_note(_contact_id: str, _body: str) -> None:
        return None

    monkeypatch.setattr(bridge_main.ghl_adapter, "add_note", note_ok)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_note_by_body", no_existing_note)

    response = isolated_api.client.post("/outbox/process")
    assert response.status_code == 200, response.text
    assert response.json()["sent"] == 1
    assert len(opportunities) == 1, (
        "El reintento no puede duplicar una oportunidad ya checkpointada"
    )
    assert notes == ["contact-b"]
