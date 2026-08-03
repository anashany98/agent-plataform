"""Evals D-035: crash ambiguo tras efectos externos del webhook.

El webhook checkpointa su resultado después de cada efecto externo visible
(respuesta en el canal). Si el proceso muere entre el efecto y el cierre de
idempotencia, la redelivery detecta el checkpoint y completa sin repetir el
efecto. Un fallo anterior a cualquier efecto se reintenta con normalidad.

Hermetismo: los crashes se inyectan con monkeypatches; ningún test contacta
servicios externos.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import AuditLog, IdempotencyRecord, Product, Quote
from app.security import Principal, get_current_principal
from app.services.chatwoot_adapter import ChatwootIntegrationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "test-installation"


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
        user_id="crash-recovery-admin",
        username="crash-recovery-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="crash-recovery-jti",
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


def _seed_product(api: IsolatedApi) -> None:
    with _isolated_session(api) as db:
        db.add(
            Product(
                id="prod-crash-recovery",
                external_id="prod-crash-recovery",
                sku="SKU-CRASH-0001",
                name="Sensor Recuperacion",
                description="Fixture sintético para pruebas de recuperación tras crash.",
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("60.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=40,
                reserved_stock=0,
            )
        )
        db.commit()


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


def _webhook_payload(suffix: str, email: str) -> dict[str, Any]:
    return {
        "event": "message_created",
        "id": f"crash-{suffix}",
        "message_type": "incoming",
        "content": "Necesito 1 unidad de sensor recuperacion",
        "private": False,
        "account": {"id": 6161},
        "conversation": {"id": 7272},
        "sender": {"id": 11, "name": "Lead Crash", "email": email},
    }


def _replies_sent(outbound: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        payload
        for path, payload in outbound
        if path.endswith("/messages")
        and not payload.get("private")
        and payload.get("message_type") == "outgoing"
    ]


def test_crash_after_effect_recovers_from_checkpoint_without_repeating_reply(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []

    async def capture_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_chatwoot)

    real_complete = bridge_main._complete_idempotency
    complete_calls = {"count": 0}

    def crash_once(db, key, owner_id, response, status_code=200, *, commit=True):
        complete_calls["count"] += 1
        if complete_calls["count"] == 1:
            raise RuntimeError("crash inyectado tras el efecto externo")
        return real_complete(db, key, owner_id, response, status_code, commit=commit)

    monkeypatch.setattr(bridge_main, "_complete_idempotency", crash_once)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-crash-{suffix[:10]}@example.com")
    idempotency_key = f"chatwoot:6161:{payload['id']}"

    first = _signed_chatwoot_request(isolated_api.client, payload)
    assert first.status_code == 500, "El crash tras el efecto debe surfaced como error, no como éxito falso"
    assert len(_replies_sent(outbound)) == 1, "El efecto externo llegó a ejecutarse una vez"

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "failed"
        checkpoint = record.response_body
        assert isinstance(checkpoint, dict) and checkpoint.get("status") == "success", (
            "El resultado debe quedar checkpointado aunque el cierre falle"
        )
        quotes_before = db.query(Quote).count()

    second = _signed_chatwoot_request(isolated_api.client, payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "resumed_from_checkpoint"
    assert body["original_response"]["action"] == "quote_created"
    assert len(_replies_sent(outbound)) == 1, (
        "La redelivery con checkpoint no puede repetir la respuesta al cliente"
    )

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed"
        assert record.response_body.get("status") == "success"
        assert db.query(Quote).count() == quotes_before
        resumes = db.query(AuditLog).filter(
            AuditLog.event_type == "webhook_checkpoint_resume"
        ).all()
        assert any(
            (row.details or {}).get("idempotency_key") == idempotency_key for row in resumes
        )

    third = _signed_chatwoot_request(isolated_api.client, payload)
    assert third.status_code == 200
    assert third.json()["status"] == "duplicate_ignored"
    assert len(_replies_sent(outbound)) == 1


def test_hard_crash_stuck_processing_recovers_via_expired_lease(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []

    async def capture_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_chatwoot)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-stuck-{suffix[:10]}@example.com")
    idempotency_key = f"chatwoot:6161:{payload['id']}"

    first = _signed_chatwoot_request(isolated_api.client, payload)
    assert first.status_code == 200, first.text
    assert first.json()["action"] == "quote_created"
    assert len(_replies_sent(outbound)) == 1

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        # Reconstrucción del estado tras un crash duro: el proceso murió con el
        # efecto ya hecho y el cierre sin confirmar; el lease queda caducado.
        record.state = "processing"
        record.status_code = 102
        record.owner_id = "dead-owner"
        record.lease_expires_at = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(seconds=30)
        record.attempt_count = 1
        db.commit()

    second = _signed_chatwoot_request(isolated_api.client, payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "resumed_from_checkpoint"
    assert body["original_response"]["action"] == "quote_created"
    assert len(_replies_sent(outbound)) == 1, (
        "El takeover con lease caducado y checkpoint no puede repetir el efecto"
    )

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed"
        assert db.query(Quote).count() == 1


def test_failure_before_any_external_effect_retries_normally(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fallo en la respuesta al canal: sin checkpoint, el takeover reintenta.

    El primer intento crea el borrador interno del presupuesto y falla al
    enviar la respuesta (efecto externo). El reintento no tiene checkpoint de
    éxito, así que re-ejecuta el flujo; la deduplicación determinista por
    ``source_message_id`` evita duplicar el presupuesto y la acción se reporta
    como ``quote_already_exists``. El cliente recibe la respuesta una sola vez.
    """
    _seed_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []
    post_calls = {"count": 0}

    async def flaky_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        post_calls["count"] += 1
        if post_calls["count"] == 1:
            raise ChatwootIntegrationError("avería inyectada antes del efecto")
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", flaky_chatwoot)

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-flaky-{suffix[:10]}@example.com")
    idempotency_key = f"chatwoot:6161:{payload['id']}"

    first = _signed_chatwoot_request(isolated_api.client, payload)
    assert first.status_code == 502, first.text
    assert _replies_sent(outbound) == []

    second = _signed_chatwoot_request(isolated_api.client, payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "success", (
        "Sin checkpoint previo el takeover debe reintentar el flujo completo"
    )
    assert body["action"] == "quote_already_exists", (
        "El borrador del primer intento se deduplica por source_message_id"
    )
    assert len(_replies_sent(outbound)) == 1

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed"
        assert record.attempt_count == 2
        assert db.query(Quote).count() == 1, "El reintento no puede duplicar el presupuesto"
