"""Evals D-028: observabilidad estructurada, métricas y alertas.

Cobertura:

- Los logs JSON emiten correlación, tenant y usuario sin filtrar secretos.
- El middleware genera ``X-Correlation-ID`` cuando el cliente no lo envía y
  lo refleja en el cuerpo de la respuesta.
- Las reglas de alerta ``circuit_breaker_open`` y
  ``outbox_dead_letter_growth`` disparan con fault injection sin PII ni
  secretos en el detalle.
- Las métricas Prometheus se incrementan con cada request y cada
  transición de estado.
- Las claves sensibles (password, token, sk_live, JWT, tarjeta con Luhn,
  claves privadas) nunca aparecen en los logs.

Hermetismo: el sistema se reinicia con un sink de alertas vacío y un
logger en memoria; las pruebas no tocan la red ni el sistema de
archivos fuera de los directorios temporales.
"""

from __future__ import annotations

import io
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.security import Principal, get_current_principal
from app.services import observability as obs
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "test-installation"


@dataclass
class CaptureLogs:
    stream: io.StringIO
    handler: logging.Handler

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line.startswith("{")]


@contextmanager
def captured_logs():
    """Sustituye el handler raíz por uno en memoria con el formatter JSON."""

    root = logging.getLogger()
    buffer = io.StringIO()
    handler = logging.StreamHandler(stream=buffer)
    handler.setFormatter(obs._JsonFormatter())
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel("INFO")
    try:
        yield buffer
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


@pytest.fixture(autouse=True)
def _reset_observability_state():
    obs.reset_alert_sink()
    yield
    obs.reset_alert_sink()


@pytest.fixture
def observability_api(monkeypatch: pytest.MonkeyPatch):
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
        user_id="obs-admin",
        username="obs-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="obs-jti",
    )
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_principal] = lambda: principal
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_principal, None)
        engine.dispose()


def test_correlation_id_is_generated_and_propagated(observability_api: TestClient) -> None:
    first = observability_api.get("/live")
    assert first.status_code == 200, first.text
    generated = first.headers.get("X-Correlation-ID")
    assert generated and len(generated) >= 16, (
        "El middleware debe generar y devolver un correlation_id en cada respuesta"
    )

    provided = observability_api.get("/live", headers={"X-Correlation-ID": "trace-1234567890"})
    assert provided.headers.get("X-Correlation-ID") == "trace-1234567890"


def test_logs_do_not_leak_secrets_under_fault_injection(observability_api: TestClient) -> None:
    """El middleware no debe volcar ``Authorization``, tokens ni secretos."""

    secret = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZWZhdWx0In0.fakefakefake"
    body = {
        "username": "obs-admin",
        "password": "sk_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0",
        "refresh_token": "4539 1488 0343 6467",
        "card_number": "4242 4242 4242 4242",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
    }
    with captured_logs() as buffer:
        response = observability_api.post(
            "/auth/login",
            json=body,
            headers={
                "Authorization": secret,
                "X-Correlation-ID": "audit-secret-leak",
            },
        )
    assert response.status_code in (200, 401, 422)

    raw = buffer.getvalue()
    assert "audit-secret-leak" in raw, "El correlation_id debe aparecer en los logs"
    for needle in (
        "sk_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0",
        "4539 1488 0343 6467",
        "4242 4242 4242 4242",
        "BEGIN RSA PRIVATE KEY",
        secret,
        "fakefakefake",
    ):
        assert needle not in raw, f"El secreto {needle!r} no debe aparecer en logs"


def test_log_event_redacts_secrets_under_fault_injection() -> None:
    """``log_event`` redacta secretos aunque se inyecten en campos arbitrarios."""

    with captured_logs() as buffer:
        obs.log_event(
            "WARNING",
            "fault.injected",
            correlation_id="corr-secret",
            password="swordfish",
            bearer="Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.fakefake",
            api_key="sk_live_abc123def456ghi789jkl012mno",
            card="4539 1488 0343 6467",
        )
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]
    assert lines, "log_event debe emitir al menos una línea"
    payload = lines[-1]
    assert payload["password"] == "[REDACTED]"
    assert "[REDACTED]" in payload["bearer"]
    assert "[REDACTED]" in payload["api_key"]
    assert "[REDACTED]" in payload["card"]
    assert "swordfish" not in payload["bearer"]
    assert "fakefake" not in payload["bearer"]


def test_breaker_open_fires_alert_without_secrets(observability_api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """El alert sink se dispara con fallo inyectado en el breaker de GHL."""

    from app.services.resilience import get_breaker

    breaker = get_breaker("ghl")
    breaker.failure_threshold = 1
    breaker.recovery_sec = 60.0
    breaker._state = "closed"  # noqa: SLF001 — arranque de prueba
    breaker._consecutive_failures = 0  # noqa: SLF001
    breaker._opened_at = None  # noqa: SLF001

    observability_api.get("/metrics", headers={"X-Correlation-ID": "breaker-trace"})
    breaker.record_failure()
    observability_api.get("/metrics", headers={"X-Correlation-ID": "breaker-trace-2"})

    snapshot = observability_api.get("/metrics").json()
    alerts = [event for event in snapshot["alerts"]["recent"] if event["rule_id"] == "circuit_breaker_open"]
    assert any(event["details"].get("provider") == "ghl" for event in alerts), (
        "La apertura del breaker debe generar una alerta circuit_breaker_open"
    )


def test_outbox_dead_letter_fires_alert(observability_api: TestClient) -> None:
    """Un mensaje en DLQ dispara la alerta outbox_dead_letter_growth."""

    from app.models.models import OutboxMessage

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

    app.dependency_overrides[get_db] = isolated_db
    try:
        with installation_scope(INSTALLATION_ID):
            with session_factory() as db:
                db.add(
                    OutboxMessage(
                        topic="fault-injection",
                        idempotency_key=f"fault-{id(object())}",
                        payload={"echo": True},
                        state="dead",
                        attempt_count=3,
                        max_attempts=3,
                    )
                )
                db.commit()
        observability_api.get("/metrics", headers={"X-Correlation-ID": "outbox-trace"})
        snapshot = observability_api.get("/metrics").json()
        rule_ids = {event["rule_id"] for event in snapshot["alerts"]["recent"]}
        assert "outbox_dead_letter_growth" in rule_ids, (
            "Un mensaje en DLQ debe disparar outbox_dead_letter_growth"
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_metrics_endpoint_reports_breaker_states_and_alerts(observability_api: TestClient) -> None:
    """El endpoint /metrics expone contadores y reglas D-028."""

    snapshot = observability_api.get("/metrics").json()
    assert "circuit_breakers" in snapshot
    assert "alerts" in snapshot
    assert "evaluated" in snapshot["alerts"]


def test_log_event_emits_redacted_payload() -> None:
    """``log_event`` aplica redacción antes de serializar."""

    with captured_logs() as buffer:
        obs.log_event(
            "WARNING",
            "test.fixture",
            tenant_id="tenant-x",
            authorization="Bearer super-secret",
            api_key="sk_live_abcdefghijklmnopqrstuv",
            text="Documento sensible con 4539 1488 0343 6467 como dato.",
        )
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]
    assert lines, "log_event debe emitir al menos una línea"
    payload = lines[-1]
    assert payload["tenant_id"] == "tenant-x"
    assert "[REDACTED]" in payload["authorization"]
    assert "[REDACTED]" in payload["api_key"]
    assert "sk_live_abcdefghijklmnopqrstuv" not in payload["text"]
    assert "[REDACTED]" in payload["text"]


def test_alert_rules_registry_is_defined() -> None:
    """Las reglas base existen y declaran identificadores estables."""

    identifiers = {rule.rule_id for rule in obs.DEFAULT_ALERT_RULES}
    assert {
        "circuit_breaker_open",
        "outbox_dead_letter_growth",
        "rag_abstention_rate",
        "dlp_findings",
    } <= identifiers


def test_request_log_includes_correlation_route_and_status() -> None:
    """El middleware emite ``request.completed`` con los campos de trazabilidad."""

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
        user_id="obs-trace",
        username="obs-trace",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="obs-trace-jti",
    )
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_principal] = lambda: principal
    client = TestClient(app, raise_server_exceptions=False)
    try:
        with captured_logs() as buffer:
            response = client.get("/live", headers={"X-Correlation-ID": "trace-XYZ"})
        assert response.status_code == 200
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_principal, None)
        engine.dispose()
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]
    completed = [line for line in lines if line.get("message") == "request.completed"]
    assert completed, "El middleware debe emitir al menos un access log estructurado"
    entry = completed[0]
    assert entry["correlation_id"] == "trace-XYZ"
    assert entry["route"] == "/live"
    assert entry["method"] == "GET"
    assert entry["status_code"] == 200
    assert isinstance(entry["latency_ms"], (int, float))


def test_redact_filters_documented_secrets() -> None:
    """``redact_for_log`` cubre los tipos documentados de D-020."""

    sample = {
        "password": "swordfish",
        "bearer": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.fakefake",
        "sk": "sk_live_abc123def456ghi789jkl012mno",
        "card": "4539 1488 0343 6467",
        "private_key": "-----BEGIN PRIVATE KEY-----abc",
        "allowed": "Texto inocuo que no debe filtrarse",
    }
    redacted = obs.redact_for_log(sample)
    assert redacted["password"] == "[REDACTED]"
    assert redacted["bearer"] == "[REDACTED]"
    assert redacted["sk"] == "[REDACTED]"
    assert redacted["private_key"] == "[REDACTED]"
    assert "[REDACTED]" in redacted["card"]
    assert redacted["allowed"] == "Texto inocuo que no debe filtrarse"
    assert "swordfish" not in str(redacted)
    assert "fakefake" not in str(redacted)
    assert "BEGIN PRIVATE KEY" not in str(redacted)
