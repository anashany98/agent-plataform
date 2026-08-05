from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import AuditLog, IdempotencyRecord, Pricelist
from app.security import Principal, get_current_principal
from app.services.chatwoot_adapter import ChatwootIntegrationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
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

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

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
        user_id="idempotency-contract-admin",
        username="idempotency-contract-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="idempotency-contract-jti",
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


def _chatwoot_payload(message_id: str) -> dict[str, Any]:
    return {
        "event": "message_created",
        "id": message_id,
        "message_type": "incoming",
        "content": "Necesito hablar con una persona",
        "private": False,
        "account": {"id": 77},
        "conversation": {"id": 9901},
        "sender": {"id": 501, "name": "Cliente contrato"},
    }


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


def _response_payload(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _idempotency_key(payload: dict[str, Any]) -> str:
    return f"chatwoot:{payload['account']['id']}:{payload['id']}"


def _set_first_mapped(record: IdempotencyRecord, aliases: tuple[str, ...], value: Any) -> None:
    mapped_columns = set(record.__table__.columns.keys())
    for alias in aliases:
        if alias in mapped_columns:
            setattr(record, alias, value)
            return


def _install_processing_claim(
    api: IsolatedApi,
    payload: dict[str, Any],
    *,
    age: dt.timedelta,
    owner: str | None,
    heartbeat_at: dt.datetime | None,
    lease_expires_at: dt.datetime | None,
    persist_payload: bool,
) -> None:
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    response_body: dict[str, Any] = {"status": "processing"}
    if owner:
        response_body["owner"] = owner
    if heartbeat_at:
        response_body["heartbeat_at"] = heartbeat_at.isoformat()
    if lease_expires_at:
        response_body["lease_expires_at"] = lease_expires_at.isoformat()
    if persist_payload:
        response_body["payload"] = payload

    with installation_scope(INSTALLATION_ID):
        with api.session_factory() as db:
            record = IdempotencyRecord(
                idempotency_key=_idempotency_key(payload),
                created_at=now - age,
                response_body=response_body,
                status_code=102,
            )
            _set_first_mapped(record, ("owner_id", "lease_owner", "claimed_by", "worker_id", "owner"), owner)
            _set_first_mapped(
                record,
                ("lease_expires_at", "lease_until", "locked_until"),
                lease_expires_at,
            )
            _set_first_mapped(
                record,
                ("heartbeat_at", "last_heartbeat_at", "lease_heartbeat_at"),
                heartbeat_at,
            )
            _set_first_mapped(record, ("payload", "request_body", "raw_body"), payload)
            _set_first_mapped(record, ("state", "status"), "processing")
            _set_first_mapped(record, ("attempt_count", "attempts", "retry_count"), 1)
            db.add(record)
            db.commit()


def _load_claim(api: IsolatedApi, key: str) -> IdempotencyRecord | None:
    with installation_scope(INSTALLATION_ID):
        with api.session_factory() as db:
            record = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
            if record is not None:
                db.expunge(record)
            return record


def _record_text(record: IdempotencyRecord | None) -> str:
    if record is None:
        return ""
    values = {
        column.name: getattr(record, column.name, None)
        for column in record.__table__.columns
    }
    return json.dumps(values, default=str, ensure_ascii=False, sort_keys=True).lower()


def _candidate_inbox_columns() -> set[str]:
    columns: set[str] = set()
    for table_name, table in Base.metadata.tables.items():
        normalized_name = table_name.lower()
        if any(token in normalized_name for token in ("idempot", "webhook", "inbox")):
            columns.update(column.name.lower() for column in table.columns)
    return columns


def _durable_operation_text(api: IsolatedApi, raw_key: str) -> str:
    serialized_rows: list[str] = []
    with api.engine.connect() as connection:
        for table_name, table in Base.metadata.tables.items():
            normalized_name = table_name.lower()
            if not any(token in normalized_name for token in ("idempot", "inbox", "outbox", "import_operation")):
                continue
            for row in connection.execute(select(table)).mappings():
                serialized = json.dumps(dict(row), default=str, ensure_ascii=False, sort_keys=True)
                if raw_key in serialized:
                    serialized_rows.append(serialized)
    return "\n".join(serialized_rows).lower()


def test_d035_durable_claim_requires_owner_lease_heartbeat_payload_and_failure_recovery():
    columns = _candidate_inbox_columns()
    requirements = {
        "owner": {"owner_id", "lease_owner", "claimed_by", "worker_id", "owner"},
        "lease": {"lease_expires_at", "lease_until", "locked_until"},
        "heartbeat": {"heartbeat_at", "last_heartbeat_at", "lease_heartbeat_at"},
        "payload": {"payload", "request_body", "raw_body", "event_payload"},
        "state": {"state", "status"},
        "attempts": {"attempt_count", "attempts", "retry_count"},
        "failure recovery": {"last_error", "next_attempt_at", "failed_at", "retry_at"},
    }
    missing = [name for name, aliases in requirements.items() if columns.isdisjoint(aliases)]

    assert not missing, (
        "D-035: el inbox/claim no puede distinguir propietario vivo, lease, heartbeat, payload y recuperación; "
        f"semánticas ausentes={missing}, columnas candidatas={sorted(columns)}"
    )


def test_d035_young_orphan_claim_is_not_acknowledged_as_terminal_duplicate(
    isolated_api: IsolatedApi,
    monkeypatch,
):
    payload = _chatwoot_payload(f"young-orphan-{uuid.uuid4().hex}")
    _install_processing_claim(
        isolated_api,
        payload,
        age=dt.timedelta(minutes=1),
        owner=None,
        heartbeat_at=None,
        lease_expires_at=None,
        persist_payload=False,
    )
    sent_replies: list[str] = []

    async def capture_reply(_account_id: int, _conversation_id: int, body: str):
        sent_replies.append(body)
        return {"id": "synthetic-reply"}

    async def no_op(*_args, **_kwargs):
        return {"status": "synthetic-no-op"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "send_reply", capture_reply)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "toggle_human_handoff", no_op)
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "add_private_note", no_op)

    response = _signed_chatwoot_request(isolated_api.client, payload)
    response_body = _response_payload(response)
    persisted = _load_claim(isolated_api, _idempotency_key(payload))
    persisted_text = _record_text(persisted)
    retryable_http = response.status_code in {408, 409, 423, 425, 429, 500, 502, 503, 504}
    completed_once = len(sent_replies) == 1
    durably_pending = (
        response.status_code in {200, 202}
        and isinstance(response_body, dict)
        and str(response_body.get("status") or "") in {"accepted", "pending", "processing", "retry_scheduled"}
        and str(payload["id"]).lower() in persisted_text
    )

    assert retryable_http or completed_once or durably_pending, (
        "D-035: un crash tras confirmar el claim y antes del efecto quedó reconocido como duplicado terminal; "
        f"http={response.status_code}, body={response_body}, replies={len(sent_replies)}, claim={persisted_text}"
    )


def test_d035_live_worker_past_creation_ttl_keeps_lease_and_blocks_duplicate(
    isolated_api: IsolatedApi,
    monkeypatch,
):
    payload = _chatwoot_payload(f"live-worker-{uuid.uuid4().hex}")
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    _install_processing_claim(
        isolated_api,
        payload,
        age=dt.timedelta(minutes=6),
        owner="worker-a",
        heartbeat_at=now,
        lease_expires_at=now + dt.timedelta(minutes=2),
        persist_payload=True,
    )
    sent_replies: list[str] = []

    async def capture_reply(_account_id: int, _conversation_id: int, body: str):
        sent_replies.append(body)
        return {"id": "duplicate-side-effect"}

    async def no_op(*_args, **_kwargs):
        return {"status": "synthetic-no-op"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "send_reply", capture_reply)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "toggle_human_handoff", no_op)
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "add_private_note", no_op)

    response = _signed_chatwoot_request(isolated_api.client, payload)
    response_body = _response_payload(response)
    persisted = _load_claim(isolated_api, _idempotency_key(payload))
    persisted_text = _record_text(persisted)
    owner_preserved = "worker-a" in persisted_text
    still_non_terminal = persisted is not None and persisted.status_code != 200

    assert sent_replies == [] and owner_preserved and still_non_terminal, (
        "D-035: el TTL de created_at robó un claim cuyo worker seguía vivo y admitió un segundo efecto; "
        f"http={response.status_code}, body={response_body}, replies={sent_replies}, claim={persisted_text}"
    )


def test_d035_processing_failure_remains_durable_and_retryable(
    isolated_api: IsolatedApi,
    monkeypatch,
):
    payload = _chatwoot_payload(f"failed-worker-{uuid.uuid4().hex}")

    async def no_op(*_args, **_kwargs):
        return {"status": "synthetic-no-op"}

    async def fail_reply(*_args, **_kwargs):
        raise ChatwootIntegrationError("synthetic crash after claim")

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "toggle_human_handoff", no_op)
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "add_private_note", no_op)
    monkeypatch.setattr(bridge_main.chatwoot_adapter, "send_reply", fail_reply)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")

    response = _signed_chatwoot_request(isolated_api.client, payload)
    response_body = _response_payload(response)
    persisted = _load_claim(isolated_api, _idempotency_key(payload))
    persisted_text = _record_text(persisted)
    payload_is_durable = str(payload["id"]).lower() in persisted_text
    recoverable_state = any(
        marker in persisted_text
        for marker in ("failed", "retry", "pending", "processing", "synthetic crash")
    )
    not_falsely_completed = persisted is not None and persisted.status_code != 200

    assert payload_is_durable and recoverable_state and not_falsely_completed, (
        "D-035: el fallo elimina el único claim en vez de conservar payload, error e intento recuperable; "
        f"http={response.status_code}, body={response_body}, claim={persisted_text}"
    )


def test_d036_lost_import_response_replay_with_same_key_creates_one_pricelist(
    isolated_api: IsolatedApi,
):
    raw_key = f"import-replay-{uuid.uuid4().hex}"
    pricelist_name = f"VIP replay {uuid.uuid4().hex}"
    request_body = {
        "dry_run": False,
        "items": [{"name": pricelist_name, "discount_percentage": "12.50"}],
    }
    headers = {"Idempotency-Key": raw_key}

    # The first response is intentionally treated as lost by the caller.
    first = isolated_api.client.post(
        "/api/bridge/import/pricelists",
        headers=headers,
        json=request_body,
    )
    second = isolated_api.client.post(
        "/api/bridge/import/pricelists",
        headers=headers,
        json=request_body,
    )
    first_body = _response_payload(first)
    second_body = _response_payload(second)

    with installation_scope(INSTALLATION_ID):
        with isolated_api.session_factory() as db:
            rows = db.query(Pricelist).filter(Pricelist.name == pricelist_name).all()
    durable_text = _durable_operation_text(isolated_api, raw_key)

    assert (
        first.status_code == 200
        and isinstance(first_body, dict)
        and first_body.get("status") == "success"
        and second.status_code == 200
        and isinstance(second_body, dict)
        and second_body.get("status") == "success"
        and len(rows) == 1
        and raw_key.lower() in durable_text
    ), (
        "D-036: perder la respuesta y repetir Idempotency-Key duplicó o no dejó resultado durable; "
        f"first={first.status_code}/{first_body}, second={second.status_code}/{second_body}, "
        f"rows={[row.id for row in rows]}, durable={durable_text}"
    )


def test_d036_audit_failure_is_atomic_or_replay_recovers_committed_import(
    isolated_api: IsolatedApi,
    monkeypatch,
):
    raw_key = f"import-audit-failure-{uuid.uuid4().hex}"
    pricelist_id = f"vip-audit-{uuid.uuid4().hex}"
    request_body = {
        "dry_run": False,
        "items": [
            {
                "id": pricelist_id,
                "name": "VIP audit fault injection",
                "discount_percentage": "15.00",
            }
        ],
    }
    headers = {"Idempotency-Key": raw_key}
    original_audit = bridge_main._audit

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("synthetic audit failure after import")

    monkeypatch.setattr(bridge_main, "_audit", fail_audit)
    first = isolated_api.client.post(
        "/api/bridge/import/pricelists",
        headers=headers,
        json=request_body,
    )

    with installation_scope(INSTALLATION_ID):
        with isolated_api.session_factory() as db:
            count_after_failure = db.query(Pricelist).filter(Pricelist.id == pricelist_id).count()
    durable_after_failure = _durable_operation_text(isolated_api, raw_key)
    recoverable_after_failure = (
        raw_key.lower() in durable_after_failure
        and any(marker in durable_after_failure for marker in ("success", "completed", "recover", "pending"))
    )
    partial_state_is_safe = count_after_failure == 0 or recoverable_after_failure

    monkeypatch.setattr(bridge_main, "_audit", original_audit)
    second = isolated_api.client.post(
        "/api/bridge/import/pricelists",
        headers=headers,
        json=request_body,
    )
    first_body = _response_payload(first)
    second_body = _response_payload(second)

    with installation_scope(INSTALLATION_ID):
        with isolated_api.session_factory() as db:
            final_count = db.query(Pricelist).filter(Pricelist.id == pricelist_id).count()
            audit_count = db.query(AuditLog).filter(AuditLog.event_type == "data_import").count()
    durable_after_replay = _durable_operation_text(isolated_api, raw_key)
    replay_is_recoverable = (
        second.status_code == 200
        and isinstance(second_body, dict)
        and second_body.get("status") == "success"
        and final_count == 1
        and (
            audit_count == 1
            or (
                raw_key.lower() in durable_after_replay
                and any(marker in durable_after_replay for marker in ("success", "completed", "pending"))
            )
        )
    )

    assert partial_state_is_safe and replay_is_recoverable, (
        "D-036: el dato se confirmó antes del audit sin outcome recuperable y el replay no pudo reconstruir éxito; "
        f"first={first.status_code}/{first_body}, count_after_failure={count_after_failure}, "
        f"durable_after_failure={durable_after_failure}, second={second.status_code}/{second_body}, "
        f"final_count={final_count}, audit_count={audit_count}, durable_after_replay={durable_after_replay}"
    )
