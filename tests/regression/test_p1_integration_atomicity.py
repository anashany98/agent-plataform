import asyncio
import hashlib
import hmac
import json
import threading
import time
import uuid
from typing import Any

import httpx
from app import main as bridge_main
from app.database import Base, SessionLocal
from app.main import ApprovalDecision, approve_request, reject_request
from app.models.models import ApprovalRequest, AuditLog, IdempotencyRecord
from app.security import Principal
from app.services import activepieces_adapter as activepieces_module
from app.services import chatwoot_adapter as chatwoot_module
from app.services import ghl_adapter as ghl_module
from app.services.activepieces_adapter import (
    ActivepiecesAdapter,
    ActivepiecesIntegrationError,
)
from app.services.chatwoot_adapter import ChatwootAdapter, ChatwootIntegrationError
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def _clean_bridge_records(*, idempotency_key: str, external_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == idempotency_key).delete()
        if external_id:
            for log in db.query(AuditLog).filter(AuditLog.event_type == "ghl_lead").all():
                if str((log.details or {}).get("external_id") or "") == external_id:
                    db.delete(log)
        db.commit()
    finally:
        db.close()


def _signed_chatwoot_request(client, payload: dict[str, Any], delivery_id: str):
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"test-chatwoot-secret",
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/chatwoot",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
            "X-Chatwoot-Delivery": delivery_id,
        },
    )


def test_ghl_failure_after_opportunity_does_not_repeat_external_side_effect(
    client,
    auth_headers,
    monkeypatch,
):
    external_id = f"p1-ghl-{uuid.uuid4().hex}"
    idempotency_key = f"ghl-lead:{external_id}"
    opportunity_calls: list[str] = []

    async def upsert_contact(**_kwargs):
        return {"contact": {"id": "fault-injection-contact"}}

    async def create_opportunity(**kwargs):
        opportunity_calls.append(str(kwargs["external_id"]))
        return {"id": f"fault-injection-opportunity-{len(opportunity_calls)}"}

    async def fail_after_opportunity(_contact_id: str, _body: str):
        raise GHLIntegrationError("fallo inyectado después de crear la oportunidad")

    async def no_existing_opportunity(**_kwargs) -> None:
        return None

    async def no_existing_note(_contact_id: str, _body: str) -> None:
        return None

    monkeypatch.setattr(bridge_main.ghl_adapter, "upsert_contact", upsert_contact)
    monkeypatch.setattr(bridge_main.ghl_adapter, "create_opportunity", create_opportunity)
    monkeypatch.setattr(bridge_main.ghl_adapter, "add_note", fail_after_opportunity)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_opportunity_by_reference", no_existing_opportunity)
    monkeypatch.setattr(bridge_main.ghl_adapter, "find_note_by_body", no_existing_note)
    payload = {
        "email": f"fault-injection-{uuid.uuid4().hex[:12]}@example.com",
        "first_name": "Fault",
        "opportunity_name": "Prueba de atomicidad",
        "monetary_value": 100,
        "external_id": external_id,
        "note": "Provoca el fallo después del efecto externo",
    }

    try:
        client.post("/integrations/ghl/leads", headers=auth_headers, json=payload)
        client.post("/integrations/ghl/leads", headers=auth_headers, json=payload)

        assert opportunity_calls == [external_id], (
            "Un retry de la misma operación no puede repetir una oportunidad ya creada "
            "aunque falle un efecto externo posterior"
        )
    finally:
        _clean_bridge_records(idempotency_key=idempotency_key, external_id=external_id)


def test_approve_and_reject_use_compare_and_set_under_concurrency(tmp_path):
    database_path = tmp_path / "approval-cas.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(bind=connection)

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    approval_id = f"p1-approval-{uuid.uuid4().hex}"
    with session_factory() as db:
        db.add(
            ApprovalRequest(
                id=approval_id,
                action_type="fault_injection_action",
                target_key=f"target-{uuid.uuid4().hex}",
                payload={},
                status="pending",
            )
        )
        db.commit()

    start_barrier = threading.Barrier(2, timeout=5)
    read_barrier = threading.Barrier(2, timeout=5)

    def synchronize_pending_reads(_conn, _cursor, statement, _params, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM approval_requests" in statement:
            read_barrier.wait()

    event.listen(engine, "after_cursor_execute", synchronize_pending_reads)
    results: list[dict[str, Any]] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()
    principals = (
        Principal(
            user_id="approver-a",
            username="approver-a",
            role="provider_admin",
            installation_id="test-installation",
            token_version=0,
            jti="approval-a",
        ),
        Principal(
            user_id="approver-b",
            username="approver-b",
            role="provider_admin",
            installation_id="test-installation",
            token_version=0,
            jti="approval-b",
        ),
    )

    def decide(function, decision: ApprovalDecision, principal: Principal) -> None:
        db = session_factory()
        try:
            start_barrier.wait()
            result = function(approval_id, decision, principal, db)
            with result_lock:
                results.append(result)
        except Exception as exc:  # La aserción posterior clasifica el conflicto esperado.
            with result_lock:
                errors.append(exc)
        finally:
            db.close()

    threads = (
        threading.Thread(
            target=decide,
            args=(approve_request, ApprovalDecision(), principals[0]),
            daemon=True,
        ),
        threading.Thread(
            target=decide,
            args=(reject_request, ApprovalDecision(rejection_reason="rechazo concurrente"), principals[1]),
            daemon=True,
        ),
    )
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not any(thread.is_alive() for thread in threads), "La carrera controlada no terminó"
        conflicts = [error for error in errors if isinstance(error, HTTPException) and error.status_code == 409]
        assert len(results) == 1 and len(conflicts) == 1, (
            "Approve/reject concurrentes deben producir una sola decisión y un conflicto; "
            f"resultados={results!r}, errores={errors!r}"
        )
    finally:
        event.remove(engine, "after_cursor_execute", synchronize_pending_reads)
        engine.dispose()


def test_handoff_assigns_a_chatwoot_team_or_agent(client, monkeypatch):
    message_id = f"p1-handoff-{uuid.uuid4().hex}"
    delivery_id = f"delivery-{uuid.uuid4().hex}"
    idempotency_key = f"chatwoot:{delivery_id}"
    outbound_calls: list[tuple[str, dict[str, Any]]] = []

    async def capture_outbound(path: str, payload: dict[str, Any]):
        outbound_calls.append((path, payload))
        return {"status": "fault-injection-capture"}

    monkeypatch.setattr(bridge_main.chatwoot_adapter, "_post", capture_outbound)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_ENABLED", True)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "test-chatwoot-token")
    payload = {
        "event": "message_created",
        "id": message_id,
        "message_type": "incoming",
        "content": "Necesito hablar con una persona",
        "conversation": {"id": 91234},
        "account": {"id": 1},
        "sender": {"id": 77, "name": "Cliente"},
    }

    try:
        response = _signed_chatwoot_request(client, payload, delivery_id)
        assert response.status_code == 200, response.text
        assignment_calls = [
            (path, body)
            for path, body in outbound_calls
            if "assign" in path.lower() or {"assignee_id", "team_id"}.intersection(body)
        ]
        assert assignment_calls, (
            "Abrir la conversación no es un handoff: debe existir una llamada que asigne equipo o agente"
        )
    finally:
        _clean_bridge_records(idempotency_key=idempotency_key)


class _FaultSequenceClient:
    def __init__(self, outcomes: list[Any], attempts: list[str]):
        self.outcomes = outcomes
        self.attempts = attempts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def _next(self, method: str, url: str):
        self.attempts.append(f"{method} {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def request(self, method: str, url: str, **_kwargs):
        return self._next(method, url)

    async def post(self, url: str, **_kwargs):
        return self._next("POST", url)


def _response(status_code: int, *, payload: dict[str, Any] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://provider.invalid/fault-injection")
    if payload is None:
        return httpx.Response(status_code, request=request, headers={"Retry-After": "0"})
    return httpx.Response(status_code, request=request, json=payload, headers={"Retry-After": "0"})


def test_ghl_retries_rate_limit_before_failing(monkeypatch):
    attempts: list[str] = []
    outcomes: list[Any] = [
        _response(429),
        _response(200, payload={"contact": {"id": "after-retry"}}),
    ]
    monkeypatch.setattr(
        ghl_module.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: _FaultSequenceClient(outcomes, attempts),
    )
    adapter = GHLAdapter()
    adapter.base_url = "https://provider.invalid"
    adapter.token = "fault-injection-token"
    adapter.location_id = "fault-injection-location"

    try:
        asyncio.run(adapter.upsert_contact(email="retry@example.invalid", first_name="Retry"))
    except GHLIntegrationError:
        pass

    assert len(attempts) >= 2, "Una respuesta 429 recuperable no debe terminar tras un único intento"


def test_chatwoot_retries_server_error_before_failing(monkeypatch):
    attempts: list[str] = []
    outcomes: list[Any] = [
        _response(503),
        _response(200, payload={"id": "after-retry"}),
    ]
    monkeypatch.setattr(
        chatwoot_module.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: _FaultSequenceClient(outcomes, attempts),
    )
    adapter = ChatwootAdapter()
    adapter.base_url = "https://provider.invalid"
    adapter.api_token = "fault-injection-token"

    try:
        asyncio.run(adapter.send_reply(1, 2, "fault injection"))
    except ChatwootIntegrationError:
        pass

    assert len(attempts) >= 2, "Un 5xx transitorio no debe terminar tras un único intento"


def test_activepieces_retries_timeout_before_failing(monkeypatch):
    attempts: list[str] = []
    request = httpx.Request("POST", "https://provider.invalid/fault-injection")
    outcomes: list[Any] = [
        httpx.ReadTimeout("timeout inyectado", request=request),
        _response(202, payload={"executionId": "after-retry"}),
    ]
    monkeypatch.setattr(
        activepieces_module.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: _FaultSequenceClient(outcomes, attempts),
    )
    adapter = ActivepiecesAdapter()
    adapter.base_url = "https://provider.invalid"

    try:
        asyncio.run(adapter.trigger_webhook("fault-injection", {"event": "test"}))
    except ActivepiecesIntegrationError:
        pass

    assert len(attempts) >= 2, "Un timeout transitorio no debe terminar tras un único intento"
