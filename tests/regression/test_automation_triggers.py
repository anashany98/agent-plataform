"""Evals del catálogo de triggers de automatización (tareas + webhooks).

Cobertura:

- ``/scheduled-tasks`` acepta los tipos nuevos del catálogo
  (``low_stock_alert``, ``cart_abandonment``, ``prestashop_sync``) con su
  validación de payload (422 si falta ``recipients`` o el tipo no existe).
- ``/scheduled-tasks/run-due`` ejecuta una tarea aprobada del tipo nuevo y
  lo audita (``scheduled_task_executed``).
- ``POST /automations/triggers/{tipo}``: 409 sin tarea activa aprobada,
  200 con tarea activa (bearer admin), firma HMAC alternativa, 422 para
  tipos desconocidos y auditoría ``automation_trigger_executed``.

Hermeticidad: la tarea y los productos sembrados se limpian al terminar;
``AUTOMATION_EMAIL_DIR`` apunta a un directorio temporal.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal

import pytest
from app.config import settings
from app.database import SessionLocal
from app.models.models import AuditLog, Product, ScheduledTask


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def email_tmp_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    target = str(tmp_path / "emails")
    monkeypatch.setattr(settings, "AUTOMATION_EMAIL_DIR", target)
    return target


@pytest.fixture
def low_stock_task(client, auth_headers, email_tmp_dir) -> str:
    """Crea, solicita y aprueba una tarea ``low_stock_alert``; la limpia al final."""
    created = client.post(
        "/scheduled-tasks",
        json={
            "name": _unique("tarea-lowstock"),
            "task_type": "low_stock_alert",
            "payload": {"recipients": "ops@example.invalid", "threshold": 5},
            "interval_seconds": 3600,
        },
        headers={**auth_headers, "Idempotency-Key": _unique("idem-lowstock")},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    requested = client.post(
        f"/scheduled-tasks/{task_id}/request-activation",
        headers={**auth_headers, "If-Match": str(created.json()["version"])},
    )
    assert requested.status_code == 200, requested.text
    approved = client.post(
        f"/approvals/{requested.json()['approval_id']}/approve",
        json={},
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    yield task_id
    db = SessionLocal()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == task_id).delete()
        db.query(Product).filter(Product.sku.like("SKU-LST-%")).delete()
        db.commit()
    finally:
        db.close()


def _seed_low_stock_product() -> None:
    db = SessionLocal()
    try:
        sku = f"SKU-LST-{uuid.uuid4().hex[:8].upper()}"
        db.add(
            Product(
                id=f"prod-lst-{uuid.uuid4().hex[:8]}",
                sku=sku,
                name="Rodamiento bajo stock API",
                source="prestashop",
                base_price=Decimal("5.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=1,
                reserved_stock=0,
            )
        )
        db.commit()
    finally:
        db.close()


def _force_task_due(task_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == task_id).update(
            {
                ScheduledTask.next_run_at: (
                    dt.datetime.now(dt.UTC).replace(tzinfo=None)
                    - dt.timedelta(minutes=1)
                )
            }
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# /scheduled-tasks: tipos del catálogo y validación de payload
# ---------------------------------------------------------------------------


def test_scheduled_task_accepts_catalog_types(client, auth_headers, email_tmp_dir) -> None:
    created: list[str] = []
    try:
        for task_type, payload in (
            ("low_stock_alert", {"recipients": "ops@example.invalid", "threshold": 3}),
            ("cart_abandonment", {"abandoned_days": 2}),
            ("prestashop_sync", {}),
            ("automation_sweep", {}),
            ("agents_round", {}),
        ):
            response = client.post(
                "/scheduled-tasks",
                json={
                    "name": _unique(f"tarea-{task_type}"),
                    "task_type": task_type,
                    "payload": payload,
                    "interval_seconds": 86400,
                },
                headers={**auth_headers, "Idempotency-Key": _unique(f"idem-{task_type}")},
            )
            assert response.status_code == 201, (task_type, response.text)
            created.append(response.json()["id"])

        unknown = client.post(
            "/scheduled-tasks",
            json={
                "name": _unique("tarea-nope"),
                "task_type": "noexiste",
                "payload": {},
                "interval_seconds": 3600,
            },
            headers={**auth_headers, "Idempotency-Key": _unique("idem-nope")},
        )
        assert unknown.status_code == 422, unknown.text

        missing_recipients = client.post(
            "/scheduled-tasks",
            json={
                "name": _unique("tarea-sin-recipients"),
                "task_type": "low_stock_alert",
                "payload": {"threshold": 3},
                "interval_seconds": 3600,
            },
            headers={**auth_headers, "Idempotency-Key": _unique("idem-norecip")},
        )
        assert missing_recipients.status_code == 422, missing_recipients.text
        assert "recipients" in missing_recipients.text
    finally:
        db = SessionLocal()
        try:
            if created:
                db.query(ScheduledTask).filter(ScheduledTask.id.in_(created)).delete()
                db.commit()
        finally:
            db.close()


def test_run_due_executes_low_stock_task(client, auth_headers, low_stock_task) -> None:
    _seed_low_stock_product()
    _force_task_due(low_stock_task)
    response = client.post("/scheduled-tasks/run-due", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    executed = [item for item in body["items"] if item["task_id"] == low_stock_task]
    assert len(executed) == 1
    # En el corpus completo la BD de sesión acumula productos con stock bajo
    # de otros tests, así que solo exigimos que el nuestro esté incluido.
    assert executed[0]["result"]["alerted"] >= 1

    db = SessionLocal()
    try:
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.event_type == "scheduled_task_executed",
                AuditLog.details["scheduled_task_id"].as_string() == low_stock_task,
            )
            .count()
        )
        assert audits >= 1
        task = db.query(ScheduledTask).filter(ScheduledTask.id == low_stock_task).one()
        assert task.last_run_at is not None, "La tarea ejecutada debe registrar last_run_at"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /automations/triggers/{tipo}: gate de aprobación, bearer y HMAC
# ---------------------------------------------------------------------------


def test_webhook_trigger_requires_active_task(client, auth_headers) -> None:
    response = client.post(
        "/automations/triggers/low_stock_alert",
        json={"payload": {"threshold": 5}},
        headers=auth_headers,
    )
    assert response.status_code == 409, response.text
    assert "aprobada" in response.json()["detail"]


def test_webhook_trigger_executes_with_approved_task(
    client, auth_headers, low_stock_task
) -> None:
    _seed_low_stock_product()
    response = client.post(
        "/automations/triggers/low_stock_alert",
        json={"payload": {"threshold": 5}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["trigger"] == "low_stock_alert"
    assert body["result"]["alerted"] >= 1

    db = SessionLocal()
    try:
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.event_type == "automation_trigger_executed",
                AuditLog.details["auth"].as_string() == "bearer",
            )
            .all()
        )
        assert len(audits) >= 1
        assert audits[-1].details["trigger"] == "low_stock_alert"
        assert audits[-1].status == "success"
    finally:
        db.close()


def test_webhook_trigger_hmac_auth(client, low_stock_task, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "AUTOMATION_WEBHOOK_SECRET", "automation-webhook-secret-32-chars-min"
    )
    _seed_low_stock_product()
    raw_body = json.dumps({"payload": {"threshold": 5}}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signed = hmac.new(
        settings.AUTOMATION_WEBHOOK_SECRET.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    response = client.post(
        "/automations/triggers/low_stock_alert",
        content=raw_body,
        headers={
            "X-Automation-Webhook-Signature": f"sha256={signed}",
            "X-Automation-Webhook-Timestamp": timestamp,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["alerted"] >= 1

    db = SessionLocal()
    try:
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.event_type == "automation_trigger_executed",
                AuditLog.details["auth"].as_string() == "hmac",
            )
            .all()
        )
        assert len(audits) >= 1
    finally:
        db.close()

    # Firma inválida → 401 (misma convención que /webhooks/chatwoot).
    bad = client.post(
        "/automations/triggers/low_stock_alert",
        content=raw_body,
        headers={
            "X-Automation-Webhook-Signature": "sha256=0" * 64,
            "X-Automation-Webhook-Timestamp": timestamp,
        },
    )
    assert bad.status_code == 401, bad.text


def test_webhook_trigger_unknown_type_is_rejected(client, auth_headers) -> None:
    response = client.post(
        "/automations/triggers/noexiste", json={}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
