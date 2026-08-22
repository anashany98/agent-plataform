"""SS-07: alertas durables con entrega externa.

Cubre: encolado con deduplicaciÃ³n por ventana, entrega webhook firmada
(HMAC + anti-replay) vÃ­a transporte inyectado, degradaciÃ³n a email,
reintentos con backoff hasta dead y evaluaciÃ³n autÃ³noma del worker.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json

import httpx
from app.database import SessionLocal


def _clear_alerts(db) -> None:
    """La BD es compartida por toda la sesiÃ³n: parte limpia cada test."""

    from app.models.models import AlertDelivery

    db.query(AlertDelivery).delete()
    db.commit()


def _fire(db, rule_id="test_rule", **kwargs):
    from app.services.alert_delivery import enqueue_alert

    return enqueue_alert(
        db,
        rule_id=rule_id,
        summary="Alerta de prueba SS-07",
        severity="critical",
        details={"k": "v"},
        **kwargs,
    )


def test_enqueue_dedupes_within_window():
    db = SessionLocal()
    try:
        first = _fire(db)
        assert first is not None
        second = _fire(db)
        assert second is None  # duplicada en la misma ventana
    finally:
        db.close()


def test_webhook_delivery_signed_and_delivered(monkeypatch):
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    from app import config as config_module
    from app.services.alert_delivery import deliver_pending

    secret = "secreto-de-test-de-alertas-32-chars"
    monkeypatch.setattr(config_module.settings, "ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    monkeypatch.setattr(config_module.settings, "ALERT_EMAIL_TO", "")
    monkeypatch.setattr(config_module.settings, "ALERT_WEBHOOK_SECRET", secret)

    db = SessionLocal()
    try:
        _clear_alerts(db)
        row = _fire(db, rule_id="webhook_rule")
        assert row is not None
        summary = deliver_pending(db, transport=httpx.MockTransport(handler))
        assert summary["delivered"] == 1, summary
        assert len(received) == 1
        payload = json.loads(received[0].content)
        assert payload["rule_id"] == "webhook_rule"
        timestamp = received[0].headers["X-Bridge-Alert-Timestamp"]
        signature = received[0].headers["X-Bridge-Alert-Signature"]
        expected = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + received[0].content,
            hashlib.sha256,
        ).hexdigest()
        assert signature == expected
        refreshed = db.query(type(row)).filter_by(id=row.id).one()
        assert refreshed.status == "delivered"
    finally:
        db.close()


def test_webhook_failure_email_spool_still_delivers(monkeypatch):
    """El webhook cae pero el spool local (degradaciÃ³n auditada) entrega."""

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    from app import config as config_module
    from app.services.alert_delivery import deliver_pending

    monkeypatch.setattr(config_module.settings, "ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    monkeypatch.setattr(config_module.settings, "ALERT_EMAIL_TO", "guardia@example.invalid")

    db = SessionLocal()
    try:
        _clear_alerts(db)
        row = _fire(db, rule_id="fallback_rule")
        assert row is not None
        summary = deliver_pending(db, transport=httpx.MockTransport(failing_handler))
        assert summary["delivered"] == 1, summary
        assert summary["webhook_errors"], "el fallo del webhook debe quedar registrado"
        refreshed = db.query(type(row)).filter_by(id=row.id).one()
        assert refreshed.status == "delivered"
        assert refreshed.last_error  # evidencia del canal caÃ­do
    finally:
        db.close()


def test_all_channels_down_retries_then_dead(monkeypatch):
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    from app import config as config_module
    from app.services import alert_delivery

    monkeypatch.setattr(config_module.settings, "ALERT_WEBHOOK_URL", "http://alerts.test/hook")
    monkeypatch.setattr(config_module.settings, "ALERT_EMAIL_TO", "guardia@example.invalid")
    monkeypatch.setattr(
        alert_delivery,
        "_deliver_email",
        lambda db, r: (_ for _ in ()).throw(RuntimeError("smtp_down")),
    )

    db = SessionLocal()
    try:
        _clear_alerts(db)
        row = _fire(db, rule_id="dead_rule")
        assert row is not None
        row.max_attempts = 2
        db.commit()

        transport = httpx.MockTransport(failing_handler)
        first = alert_delivery.deliver_pending(db, transport=transport)
        assert first["delivered"] == 0 and first["retried"] == 1, first

        # Simula que el backoff venciÃ³ para el segundo intento.
        db.expire_all()
        pending = db.query(type(row)).filter_by(id=row.id).one()
        pending.next_attempt_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        db.commit()
        second = alert_delivery.deliver_pending(db, transport=transport)
        assert second["dead"] == 1, second
        refreshed = db.query(type(row)).filter_by(id=row.id).one()
        assert refreshed.status == "dead"
    finally:
        db.close()


def test_worker_evaluates_open_breaker_and_dedupes(monkeypatch):
    from app import config as config_module
    from app.services import resilience
    from app.services.alert_delivery_worker import DurableAlertDeliveryWorker

    resilience.reset_all_breakers()
    monkeypatch.setattr(config_module.settings, "ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(config_module.settings, "ALERT_EMAIL_TO", "")

    breaker = resilience.get_breaker("openai")
    for _ in range(10):
        try:
            breaker.record_failure()
        except Exception:  # noqa: BLE001 - abrir puede lanzar CircuitOpenError
            break

    db = SessionLocal()
    try:
        worker = DurableAlertDeliveryWorker(session_factory=lambda: db)
        result = worker.evaluate_and_enqueue(db)
        assert result["fired"] >= 1
        assert result["enqueued"] >= 1
        again = worker.evaluate_and_enqueue(db)
        assert again["duplicates"] >= 1  # dedup dentro de la ventana
    finally:
        db.close()
        resilience.reset_all_breakers()
