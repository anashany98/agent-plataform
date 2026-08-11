"""Evals D-035: crash ambiguo tras efectos externos del webhook.

El webhook checkpointa su resultado después de cada efecto externo visible
(respuesta en el canal). Si el proceso muere entre el efecto y el cierre de
idempotencia, la redelivery detecta el checkpoint y completa sin repetir el
efecto. Un fallo anterior a cualquier efecto se reintenta con normalidad.

También cubre T-021: la matriz de ramas de éxito del webhook. Cada rama debe
dejarse en ``completed`` (no en ``processing``) para que un replay inmediato
devuelva 200 con el resultado cacheado y nunca 202 ``processing``.

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
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

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
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

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


# ---------------------------------------------------------------------------
# T-021: matriz de ramas de éxito — el replay inmediato devuelve el resultado
# completado (200, ``duplicate_ignored``) y nunca 202 ``processing``.
# ---------------------------------------------------------------------------


WEBHOOK_SUCCESS_BRANCHES = [
    # (etiqueta, payload, action esperada en la primera respuesta)
    (
        "event_no_message_created",
        {
            "event": "conversation_created",
            "id": "branch-evt-1",
            "account": {"id": 6161},
            "conversation": {"id": 7272},
        },
        None,  # action no aplica; status esperado: received
        "received",
    ),
    (
        "outgoing_message",
        {
            "event": "message_created",
            "id": "branch-out-1",
            "message_type": "outgoing",
            "content": "hola",
            "account": {"id": 6161},
            "conversation": {"id": 7272},
            "sender": {"id": 1, "name": "Asistente", "email": "bot@example.invalid"},
        },
        None,
        "processed",
    ),
    (
        "greeting",
        {
            "event": "message_created",
            "id": "branch-greet-1",
            "message_type": "incoming",
            "content": "hola",
            "account": {"id": 6161},
            "conversation": {"id": 7272},
            "sender": {"id": 1, "name": "Cliente", "email": "cliente-branch@example.invalid"},
        },
        "greeting",
        "success",
    ),
    (
        "human_handoff",
        {
            "event": "message_created",
            "id": "branch-human-1",
            "message_type": "incoming",
            "content": "quiero hablar con un humano",
            "account": {"id": 6161},
            "conversation": {"id": 7272},
            "sender": {"id": 1, "name": "Cliente", "email": "cliente-handoff@example.invalid"},
        },
        "human_handoff",
        "success",
    ),
]


@pytest.mark.parametrize(
    "label,payload,expected_action,expected_status",
    WEBHOOK_SUCCESS_BRANCHES,
    ids=[row[0] for row in WEBHOOK_SUCCESS_BRANCHES],
)
def test_success_branch_replay_returns_cached_result_not_processing(
    isolated_api: IsolatedApi,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    payload: dict[str, Any],
    expected_action: str | None,
    expected_status: str,
) -> None:
    """T-021: cada rama de éxito debe terminar en ``completed``.

    El replay inmediato del mismo ``message_id`` debe devolver 200 con el
    resultado cacheado (``duplicate_ignored``), no 202 ``processing``.
    """
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "")

    idempotency_key = f"chatwoot:6161:{payload['id']}"

    first = _signed_chatwoot_request(isolated_api.client, payload)
    assert first.status_code == 200, (
        f"[{label}] primer envío: status={first.status_code}, text={first.text}"
    )
    first_body = first.json()
    assert first_body.get("status") == expected_status, (
        f"[{label}] status inesperado en el primer envío: {first_body}"
    )
    if expected_action is not None:
        assert first_body.get("action") == expected_action, (
            f"[{label}] action inesperada: {first_body}"
        )

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed", (
            f"[{label}] la rama de éxito dejó el registro en "
            f"'{record.state}' en lugar de 'completed'"
        )

    # Replay inmediato: debe devolver 200 con el resultado cacheado, nunca
    # 202 ``processing``.
    second = _signed_chatwoot_request(isolated_api.client, payload)
    assert second.status_code == 200, (
        f"[{label}] el replay devolvió {second.status_code} en lugar de 200; "
        "el estado quedó en 'processing' por una rama temprana sin completar"
    )
    second_body = second.json()
    assert second_body.get("status") == "duplicate_ignored", (
        f"[{label}] el replay devolvió {second_body.get('status')}; se esperaba "
        "'duplicate_ignored' con el resultado cacheado"
    )
    cached = second_body.get("original_response") or second_body
    assert cached == first_body, (
        f"[{label}] el replay debería devolver el body cacheado del primer envío; "
        f"first={first_body}, cached={cached}"
    )

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed"
        assert record.attempt_count == 1, (
            f"[{label}] el replay no debe re-ejecutar el flujo"
        )


def test_success_branch_with_effects_replay_does_not_repeat_effects(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-021: la rama con efectos externos (quote) termina completada y el
    replay no repite ni la respuesta ni el efecto comercial.
    """
    _seed_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []

    async def capture_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_chatwoot)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-matrix-{suffix[:10]}@example.com")
    idempotency_key = f"chatwoot:6161:{payload['id']}"

    first = _signed_chatwoot_request(isolated_api.client, payload)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body.get("action") == "quote_created", first_body
    assert len(_replies_sent(outbound)) == 1

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed", (
            f"la rama quote_created dejó '{record.state}' en lugar de 'completed'"
        )

    # Replay inmediato: 200 con el resultado cacheado y sin repetir efectos.
    second = _signed_chatwoot_request(isolated_api.client, payload)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body.get("status") == "duplicate_ignored", second_body
    cached = second_body.get("original_response") or second_body
    assert cached == first_body
    assert len(_replies_sent(outbound)) == 1, (
        "El replay no puede repetir la respuesta al cliente"
    )

    with _isolated_session(isolated_api) as db:
        assert db.query(Quote).count() == 1, "El replay no puede duplicar el presupuesto"
        assert db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one().state == "completed"


def test_concurrent_delivery_with_live_lease_returns_202_and_takeover_after_expiry(
    isolated_api: IsolatedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-021: la ventana concurrente no duplica efectos.

    Mientras un worker (A) mantiene el lease vivo, una segunda entrega (B)
    del mismo ``message_id`` debe devolver 202 ``processing`` SIN ejecutar
    ningún efecto. Cuando el lease de A caduca, B hace takeover y ejecuta el
    flujo exactamente una vez; el replay posterior devuelve 200 cacheado.
    """
    _seed_product(isolated_api)
    outbound: list[tuple[str, dict[str, Any]]] = []

    async def capture_chatwoot(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        outbound.append((path, payload))
        return {"status": "captured"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_chatwoot)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

    suffix = uuid.uuid4().hex
    payload = _webhook_payload(suffix, f"lead-conc-{suffix[:10]}@example.com")
    idempotency_key = f"chatwoot:6161:{payload['id']}"

    # Worker A claima el mensaje y se queda procesando (lease vivo).
    with _isolated_session(isolated_api) as db:
        now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        db.add(
            IdempotencyRecord(
                installation_id=INSTALLATION_ID,
                idempotency_key=idempotency_key,
                state="processing",
                status_code=102,
                owner_id="worker-a",
                lease_expires_at=now + dt.timedelta(seconds=300),
                heartbeat_at=now,
                event_payload=payload,
                request_fingerprint=bridge_main._idempotency_fingerprint(payload),
                attempt_count=1,
                response_body={"status": "processing"},
            )
        )
        db.commit()

    # Entrega concurrente de B con lease vivo: 202, sin efectos.
    while_b = _signed_chatwoot_request(isolated_api.client, payload)
    assert while_b.status_code == 202, (
        f"Con lease vivo la entrega concurrente debe devolver 202, no "
        f"{while_b.status_code} ({while_b.text})"
    )
    assert while_b.json().get("status") == "processing"
    assert len(_replies_sent(outbound)) == 0, (
        "Un worker concurrente con lease vivo no puede ejecutar efectos"
    )
    with _isolated_session(isolated_api) as db:
        assert db.query(Quote).count() == 0

    # El lease de A caduca: B hace takeover y ejecuta exactamente una vez.
    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        record.lease_expires_at = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(seconds=30)
        db.commit()

    takeover = _signed_chatwoot_request(isolated_api.client, payload)
    assert takeover.status_code == 200, takeover.text
    takeover_body = takeover.json()
    assert takeover_body.get("status") == "success", takeover_body
    assert takeover_body.get("action") == "quote_created", takeover_body
    assert len(_replies_sent(outbound)) == 1, "El takeover ejecuta el flujo una sola vez"

    with _isolated_session(isolated_api) as db:
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).one()
        assert record.state == "completed"
        assert record.attempt_count == 2
        assert db.query(Quote).count() == 1

    # Replay final: 200 cacheado, sin efectos nuevos.
    final = _signed_chatwoot_request(isolated_api.client, payload)
    assert final.status_code == 200
    assert final.json().get("status") == "duplicate_ignored"
    assert len(_replies_sent(outbound)) == 1
    with _isolated_session(isolated_api) as db:
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
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

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
