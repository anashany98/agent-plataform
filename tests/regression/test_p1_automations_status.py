"""Evals T-085: estado del motor de automatizaciones en lenguaje llano.

``GET /automations/status`` devuelve la última actividad de cada
automatización del motor del Bridge (recordatorios de presupuesto, cobros
vencidos, alerta de stock y carrito abandonado), el tamaño de la cola de
envíos pendientes/fallidos y el número de tareas programadas activas — sin
jerga técnica, para que el panel del portal lo muestre tal cual.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.models.models import InvoiceDraft, OutboxMessage, Quote


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_engine_data() -> tuple[str, str]:
    """Presupuesto que caduca pronto + factura vencida para el sweep."""

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    quote_id = _unique("quote-status")
    invoice_id = _unique("inv-status")
    db = SessionLocal()
    try:
        db.add(
            Quote(
                id=quote_id,
                customer_id="cust-004",  # fixture sintético del conftest
                confirmation_token="tok",
                confirmation_payload_hash="hash",
                confirmation_expires_at=now + dt.timedelta(days=2),
                items=[{"sku": "SKU-1", "quantity": 1}],
                subtotal=Decimal("100.00"),
                tax_total=Decimal("21.00"),
                shipping_total=Decimal("0.00"),
                grand_total=Decimal("121.00"),
                currency="EUR",
                status="draft",
            )
        )
        db.add(
            InvoiceDraft(
                id=invoice_id,
                invoice_number=f"INV-{uuid.uuid4().hex[:6]}",
                order_id="order-status",
                customer_id="cust-004",
                items=[{"sku": "SKU-1", "quantity": 1}],
                total_amount=Decimal("121.00"),
                tax_amount=Decimal("21.00"),
                currency="EUR",
                status="sent",
            )
        )
        db.commit()
        invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_id).one()
        invoice.created_at = now - dt.timedelta(days=40)
        db.commit()
        return quote_id, invoice_id
    finally:
        db.close()


def _cleanup(quote_id: str, invoice_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Quote).filter(Quote.id == quote_id).delete()
        db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_id).delete()
        db.commit()
    finally:
        db.close()


def test_automations_status_after_sweep(client, auth_headers) -> None:
    quote_id, invoice_id = _seed_engine_data()
    try:
        # El sweep real genera actividad en el motor (quote expiry + dunning).
        sweep = client.post("/automations/sweep", headers=auth_headers)
        assert sweep.status_code == 200, sweep.text

        status = client.get("/automations/status", headers=auth_headers)
        assert status.status_code == 200, status.text
        data = status.json()
        engine = data["engine"]
        assert set(engine) == {"quote_expiry", "dunning", "low_stock", "cart_abandonment"}

        quote = engine["quote_expiry"]
        assert quote["last_run_at"], "La última actividad del recordatorio se registra"
        # El resumen es en lenguaje llano; en la BD compartida de la suite
        # puede apuntar al presupuesto de este test o a uno anterior, pero
        # nunca debe estar vacío ni ser jerga.
        assert quote["last_summary"] and "Presupuesto" in quote["last_summary"]

        dunning = engine["dunning"]
        assert dunning["last_run_at"]
        assert dunning["last_summary"] and "paso" in dunning["last_summary"]

        # Con/sin actividad previa: las filas respetan el contrato (nunca
        # inventan contenido) — el resto lo cubre el test de forma estable.

        # Cola y tareas: forma estable para el panel.
        assert set(data["queue"]) == {"pending", "dead"}
        assert data["queue"]["pending"] >= 0
        assert data["queue"]["dead"] >= 0
        assert set(data["scheduled_tasks"]) == {"active", "paused"}
    finally:
        _cleanup(quote_id, invoice_id)


def test_automations_status_shape_is_stable(client, auth_headers) -> None:
    """El estado siempre devuelve la forma estable para el panel (con o sin
    actividad previa de otros tests en la BD compartida)."""

    status = client.get("/automations/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    data = status.json()
    assert set(data["engine"]) == {"quote_expiry", "dunning", "low_stock", "cart_abandonment"}
    assert set(data["queue"]) == {"pending", "dead"}
    assert set(data["scheduled_tasks"]) == {"active", "paused"}
    # Sin actividad no inventa resúmenes: cada entrada es null o tiene el
    # contrato completo.
    for entry in data["engine"].values():
        if entry is not None:
            assert set(entry) == {"last_run_at", "last_status", "last_summary"}


def test_automations_status_requires_authentication(client) -> None:
    response = client.get("/automations/status")
    assert response.status_code in (401, 403)


def _create_viewer(client, auth_headers, username: str) -> str:
    created = client.post(
        "/users",
        json={
            "username": username,
            "password": "Portal-Test-123!",
            "role": "viewer",
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/auth/login",
        json={"username": username, "password": "Portal-Test-123!"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _seed_dead_messages() -> list[str]:
    db = SessionLocal()
    try:
        transient = OutboxMessage(
            id=_unique("dlq-transient"),
            topic="campaign.deliver",
            idempotency_key=_unique("idem-transient"),
            payload={"campaign_id": "c-1", "lead_id": "l-1"},
            state="dead",
            attempt_count=3,
            max_attempts=3,
            last_error={
                "type": "RuntimeError",
                "message": "GHL caído a mitad del envío",
                "permanent": False,
            },
        )
        permanent = OutboxMessage(
            id=_unique("dlq-permanent"),
            topic="ghl.lead_capture",
            idempotency_key=_unique("idem-permanent"),
            payload={"email": "cliente@example.com"},
            state="dead",
            attempt_count=1,
            max_attempts=3,
            last_error={
                "type": "RuntimeError",
                "message": "GHL sin configurar",
                "permanent": True,
            },
        )
        db.add_all([transient, permanent])
        db.commit()
        return [transient.id, permanent.id]
    finally:
        db.close()


def _delete_messages(ids: list[str]) -> None:
    if not ids:
        return
    db = SessionLocal()
    try:
        db.query(OutboxMessage).filter(OutboxMessage.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()


def test_automations_status_dlq_en_lenguaje_llano(client, auth_headers) -> None:
    """La DLQ expone cada mensaje muerto con motivo en lenguaje llano."""

    ids = _seed_dead_messages()
    try:
        status = client.get("/automations/status", headers=auth_headers)
        assert status.status_code == 200, status.text
        data = status.json()
        assert data["dead_letter"] is not None
        by_id = {entry["id"]: entry for entry in data["dead_letter"]}

        transient = by_id[ids[0]]
        assert transient["topic_label"] == "Envío de una campaña a un destinatario"
        assert "problema temporal de conexión" in transient["reason"]
        assert transient["permanent"] is False
        assert transient["attempt_count"] == 3
        assert transient["max_attempts"] == 3

        circuit_db = SessionLocal()
        try:
            circuit = OutboxMessage(
                id=_unique("dlq-circuit"),
                topic="crm.webhook",
                idempotency_key=_unique("idem-circuit"),
                payload={"url": "https://crm.example/webhook"},
                state="dead",
                attempt_count=8,
                max_attempts=8,
                last_error={
                    "type": "CircuitOpenError",
                    "message": "Circuito 'webhook' abierto; reintento permitido en 29.7s",
                    "permanent": False,
                },
            )
            circuit_db.add(circuit)
            circuit_db.commit()
            ids.append(circuit.id)
        finally:
            circuit_db.close()

        refreshed = client.get("/automations/status", headers=auth_headers)
        assert refreshed.status_code == 200, refreshed.text
        refreshed_by_id = {
            entry["id"]: entry for entry in refreshed.json()["dead_letter"]
        }
        circuit_row = refreshed_by_id[circuit.id]
        assert circuit_row["topic_label"] == "Webhook saliente al CRM"
        assert "circuito abierto" in circuit_row["reason"]

        permanent = by_id[ids[1]]
        assert permanent["topic_label"] == "Captura de oportunidad en GoHighLevel"
        assert "no está configurada" in permanent["reason"]
        assert permanent["permanent"] is True
    finally:
        _delete_messages(ids)


def test_automations_status_dlq_reintenta_por_api(client, auth_headers) -> None:
    """POST /outbox/{id}/retry reencola el mensaje y lo saca de la DLQ."""

    db = SessionLocal()
    message = None
    try:
        message = OutboxMessage(
            id=_unique("dlq-retry"),
            topic="campaign.deliver",
            idempotency_key=_unique("idem-retry"),
            payload={"campaign_id": "c-1", "lead_id": "l-1"},
            state="dead",
            attempt_count=3,
            max_attempts=3,
            last_error={
                "type": "RuntimeError",
                "message": "La plantilla de email ya no existe",
                "permanent": False,
            },
        )
        db.add(message)
        db.commit()

        retry = client.post(f"/outbox/{message.id}/retry", headers=auth_headers)
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "requeued"

        status = client.get("/automations/status", headers=auth_headers)
        assert status.status_code == 200, status.text
        assert all(entry["id"] != message.id for entry in status.json()["dead_letter"])
    finally:
        if message is not None:
            db.query(OutboxMessage).filter(OutboxMessage.id == message.id).delete()
            db.commit()
        db.close()


def test_automations_status_dlq_oculta_a_viewer(client, auth_headers) -> None:
    """El viewer no recibe la DLQ (RBAC): admin-only."""

    token = _create_viewer(client, auth_headers, _unique("dlq-viewer"))
    response = client.get(
        "/automations/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["dead_letter"] is None
