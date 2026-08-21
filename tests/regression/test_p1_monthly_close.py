"""Evals T-070: «cierra el mes» — primer proceso completo en piloto automático.

El ``finance_agent`` coordina la secuencia mensual con política de riesgo por
paso (T-068): reconciliar ventas (solo lectura), emitir facturas (financiero:
cada una es un ``ApprovalRequest`` ``issue_invoice`` con su ``value_eur`` que
la autonomía puede auto-ejecutar bajo el umbral), disparar dunning
(comunicación: solo en modo autónomo) y generar el reporte al dueño.

Cubre:

- Reconciliación: lee pedidos confirmados del periodo y detecta los que no
  tienen factura (dry-run no muta nada).
- Modo manual (deny-by-default): las facturas se proponen y quedan pendientes
  de aprobación humana; sin ``AgentDecision``, sin emails, dunning diferido.
- Modo autónomo bajo umbral: la factura se emite y envía al instante
  (``AgentDecision`` + auditoría ``agent_decision.auto_executed``, email al
  spool local).
- Sobre umbral: se difiere al humano con motivo ``over_threshold``.
- Dedupe: re-ejecutar el cierre no vuelve a proponer la misma factura.
- Registro del ``finance_agent`` con módulo ``finance`` y tools read-only.
- RBAC: requiere rol operador (viewer → 403).

Hermeticidad D-032: la BD del corpus es compartida, así que el cierre se
ejecuta SIEMPRE sobre un periodo histórico fijo (2020-06) sembrado por el
propio test con ids únicos — los pedidos del resto del corpus (fecha actual)
nunca colisionan — y todo se limpia en ``finally``, incluida la fila de
autonomía del ``finance_agent`` y la auditoría del cierre.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from app.config import settings
from app.database import SessionLocal
from app.models.models import (
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    Customer,
    InvoiceDraft,
    Order,
    Quote,
    User,
)
from app.services.autonomy import get_config

PORTAL_TEST_PASSWORD = "Portal-Test-123!"
PERIOD = "2020-06"
_PERIOD_START = datetime.datetime(2020, 6, 1, tzinfo=datetime.UTC).replace(tzinfo=None)
_PERIOD_MID = datetime.datetime(2020, 6, 15, tzinfo=datetime.UTC).replace(tzinfo=None)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_order(db, *, total: Decimal = Decimal("121.00")) -> dict[str, str]:
    """Siembra cliente + quote + pedido confirmado en 2020-06 (ids únicos)."""

    uid = _unique("mc")
    cust = f"cust-{uid}"
    quote = f"quote-{uid}"
    order = f"order-{uid}"
    db.add(
        Customer(
            id=cust,
            name=f"Cliente {uid}",
            email=f"{uid}@example.invalid",
        )
    )
    db.add(
        Quote(
            id=quote,
            customer_id=cust,
            confirmation_token=f"tok-{uid}",
            confirmation_payload_hash=f"hash-{uid}",
            confirmation_expires_at=_PERIOD_MID + datetime.timedelta(days=2),
            items=[{"sku": f"SKU-{uid}", "quantity": 1}],
            subtotal=total,
            tax_total=Decimal("0.00"),
            shipping_total=Decimal("0.00"),
            grand_total=total,
            currency="EUR",
            status="confirmed",
        )
    )
    db.add(
        Order(
            id=order,
            customer_id=cust,
            quote_id=quote,
            idempotency_key=f"idem-{uid}",
            items=[{"sku": f"SKU-{uid}", "quantity": 1}],
            subtotal=total,
            tax_total=Decimal("0.00"),
            shipping_total=Decimal("0.00"),
            grand_total=total,
            currency="EUR",
            status="confirmed",
            created_at=_PERIOD_MID,
        )
    )
    return {"customer": cust, "quote": quote, "order": order}


def _set_autonomy(*, mode: str, threshold: Decimal = Decimal(0)) -> None:
    db = SessionLocal()
    try:
        config = get_config(db, agent_id="finance_agent")
        config.mode = mode
        config.max_value_threshold = threshold
        db.commit()
    finally:
        db.close()


def _cleanup_autonomy() -> None:
    db = SessionLocal()
    try:
        db.query(AgentDecision).filter(AgentDecision.agent_id == "finance_agent").delete()
        db.query(ApprovalRequest).filter(ApprovalRequest.requested_by == "finance_agent").delete()
        db.query(InvoiceDraft).filter(
            InvoiceDraft.id.like("inv-%"),
            InvoiceDraft.order_id.like("order-mc-%"),
        ).delete()
        db.query(Order).filter(Order.id.like("order-mc-%")).delete()
        db.query(Quote).filter(Quote.id.like("quote-mc-%")).delete()
        db.query(Customer).filter(Customer.id.like("cust-mc-%")).delete()
        db.query(AuditLog).filter(
            AuditLog.correlation_id.like("monthly-close-%")
        ).delete()
        # Restaura el modo manual por defecto (deny-by-default) y elimina la
        # fila de autonomía del finance_agent para no contaminar otros módulos.
        config = get_config(db, agent_id="finance_agent")
        db.delete(config)
        db.commit()
    finally:
        db.close()


def _monthly_close(client, token: str, *, dry_run: bool = False):
    return client.post(
        "/finance/monthly-close",
        params={"period": PERIOD, "dry_run": dry_run},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_monthly_close_dry_run_reconciles_without_mutating(
    client, auth_headers
) -> None:
    token = auth_headers["Authorization"].split()[-1]
    db = SessionLocal()
    try:
        ids = _seed_order(db, total=Decimal("250.00"))
        db.commit()
    finally:
        db.close()
    try:
        response = _monthly_close(client, token, dry_run=True)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["dry_run"] is True
        reconcile = data["steps"]["reconcile"]
        assert reconcile["orders"] == 1
        assert reconcile["orders_value"] == 250.0
        assert reconcile["un_invoiced_orders"] == 1
        invoice = data["steps"]["invoice"]
        assert invoice["dry_run"] is True
        assert invoice["orders_without_invoice"] == 1
        assert invoice["approvals_created"] == 0
        assert invoice["auto_executed"] == []
        dunning = data["steps"]["dunning"]
        assert dunning["dry_run"] is True
        report = data["steps"]["report"]
        assert "Cierre mensual 2020-06" in report["text"]

        # Dry-run NO muta: ni factura, ni propuesta, ni decisión, ni email.
        db = SessionLocal()
        try:
            assert (
                db.query(InvoiceDraft)
                .filter(InvoiceDraft.order_id == ids["order"])
                .first()
                is None
            )
            assert (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "finance_agent")
                .count()
                == 0
            )
            assert (
                db.query(AgentDecision)
                .filter(AgentDecision.agent_id == "finance_agent")
                .count()
                == 0
            )
        finally:
            db.close()
    finally:
        _cleanup_autonomy()


def test_monthly_close_manual_mode_proposes_invoices_and_defers_dunning(
    client, auth_headers
) -> None:
    token = auth_headers["Authorization"].split()[-1]
    _set_autonomy(mode="manual")
    db = SessionLocal()
    try:
        _seed_order(db, total=Decimal("121.00"))
        db.commit()
    finally:
        db.close()
    try:
        response = _monthly_close(client, token)
        assert response.status_code == 200, response.text
        data = response.json()
        invoice = data["steps"]["invoice"]
        assert invoice["approvals_created"] == 1
        assert invoice["auto_executed"] == []
        assert len(invoice["deferred"]) == 1
        assert invoice["deferred"][0]["reason"] == "manual"
        dunning = data["steps"]["dunning"]
        assert dunning["mode"] == "manual"
        assert dunning["processed"] == 0
        assert dunning["deferred_to_human"] == dunning["overdue_invoices"]

        # La propuesta queda pendiente de aprobación humana y la factura en
        # pending_approval/draft: NO se ha emitido ni enviado.
        db = SessionLocal()
        try:
            approval = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.requested_by == "finance_agent",
                    ApprovalRequest.action_type == "issue_invoice",
                )
                .first()
            )
            assert approval is not None
            assert approval.status == "pending"
            invoice_row = (
                db.query(InvoiceDraft)
                .filter(InvoiceDraft.id == approval.target_key)
                .first()
            )
            assert invoice_row is not None
            assert invoice_row.status == "pending_approval"
            assert (
                db.query(AgentDecision)
                .filter(AgentDecision.agent_id == "finance_agent")
                .count()
                == 0
            )
        finally:
            db.close()
    finally:
        _cleanup_autonomy()


def test_monthly_close_autonomous_under_threshold_emits_and_sends(
    client, auth_headers, monkeypatch
) -> None:
    token = auth_headers["Authorization"].split()[-1]
    # Ninguna factura del corpus es vencida con este umbral → dunning no toca
    # datos de otros tests.
    monkeypatch.setattr(settings, "AUTOMATION_DUNNING_OVERDUE_DAYS", 9999)
    _set_autonomy(mode="autonomous", threshold=Decimal(1000))
    db = SessionLocal()
    try:
        ids = _seed_order(db, total=Decimal("121.00"))
        db.commit()
    finally:
        db.close()
    try:
        response = _monthly_close(client, token)
        assert response.status_code == 200, response.text
        data = response.json()
        invoice = data["steps"]["invoice"]
        assert invoice["approvals_created"] == 1
        assert len(invoice["auto_executed"]) == 1
        applied = invoice["auto_executed"][0]
        assert applied["amount"] == 121.0
        assert applied["delivery_status"] == "queued_for_manual_delivery"
        assert invoice["deferred"] == []
        dunning = data["steps"]["dunning"]
        assert dunning["mode"] == "autonomous"
        assert dunning["processed"] == 0  # sin vencidas bajo el umbral 9999

        db = SessionLocal()
        try:
            invoice_row = (
                db.query(InvoiceDraft)
                .filter(InvoiceDraft.order_id == ids["order"])
                .first()
            )
            assert invoice_row is not None
            assert invoice_row.status == "approved"
            approval = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.target_key == invoice_row.id)
                .first()
            )
            assert approval is not None
            assert approval.status == "approved"
            assert approval.reviewed_by == "agent:finance_agent"
            decision = (
                db.query(AgentDecision)
                .filter(
                    AgentDecision.agent_id == "finance_agent",
                    AgentDecision.target_key == invoice_row.id,
                )
                .first()
            )
            assert decision is not None
            assert decision.action_type == "issue_invoice"
            assert decision.deviation is False
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.event_type == "agent_decision.auto_executed")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            assert audit is not None
            assert audit.details.get("invoice_id") == invoice_row.id
        finally:
            db.close()
    finally:
        _cleanup_autonomy()


def test_monthly_close_over_threshold_defers_to_human(
    client, auth_headers
) -> None:
    token = auth_headers["Authorization"].split()[-1]
    _set_autonomy(mode="autonomous", threshold=Decimal(100))
    db = SessionLocal()
    try:
        _seed_order(db, total=Decimal("121.00"))  # 121 > 100
        db.commit()
    finally:
        db.close()
    try:
        response = _monthly_close(client, token)
        assert response.status_code == 200, response.text
        invoice = response.json()["steps"]["invoice"]
        assert invoice["auto_executed"] == []
        assert len(invoice["deferred"]) == 1
        assert invoice["deferred"][0]["reason"] == "over_threshold"
        assert invoice["deferred_value"] == 121.0

        db = SessionLocal()
        try:
            assert (
                db.query(AgentDecision)
                .filter(AgentDecision.agent_id == "finance_agent")
                .count()
                == 0
            )
            approval = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.requested_by == "finance_agent")
                .first()
            )
            assert approval is not None and approval.status == "pending"
        finally:
            db.close()
    finally:
        _cleanup_autonomy()


def test_monthly_close_dedupe_does_not_repropose_same_order(
    client, auth_headers
) -> None:
    token = auth_headers["Authorization"].split()[-1]
    _set_autonomy(mode="manual")
    db = SessionLocal()
    try:
        _seed_order(db, total=Decimal("121.00"))
        db.commit()
    finally:
        db.close()
    try:
        first = _monthly_close(client, token)
        assert first.status_code == 200, first.text
        assert first.json()["steps"]["invoice"]["approvals_created"] == 1

        # Segunda ejecución: el pedido ya tiene factura → no se re-propone.
        second = _monthly_close(client, token)
        assert second.status_code == 200, second.text
        invoice2 = second.json()["steps"]["invoice"]
        assert invoice2["approvals_created"] == 0
        assert invoice2["orders_without_invoice"] == 0
        assert invoice2["auto_executed"] == []

        db = SessionLocal()
        try:
            assert (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.requested_by == "finance_agent",
                    ApprovalRequest.action_type == "issue_invoice",
                )
                .count()
                == 1
            )
        finally:
            db.close()
    finally:
        _cleanup_autonomy()


def test_finance_agent_registered_with_module_and_read_tools() -> None:
    from app.main import AGENT_REGISTRY
    from app.services.tool_policy import TOOL_SPECS, authorized_tools_for

    agent = AGENT_REGISTRY.get("finance_agent")
    assert agent is not None, "El finance_agent debe estar registrado"
    assert agent["module"] == "finance"
    assert agent["module_label"] == "Finanzas (cierre mensual)"
    assert agent["autonomy_level"] == "L1_Autonomia_Por_Excepcion"
    assert agent["status"] == "active"
    authorized = authorized_tools_for(agent)
    assert authorized, "Debe autorizar tools de lectura"
    for tool in authorized:
        assert TOOL_SPECS[tool]["kind"] == "read", f"{tool} debe ser read-only"


def test_monthly_close_requires_operator_role(client, auth_headers) -> None:
    username = _unique("viewer-mc")
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": PORTAL_TEST_PASSWORD,
            "role": "viewer",
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    viewer_token = login.json()["access_token"]
    try:
        response = _monthly_close(client, viewer_token, dry_run=True)
        assert response.status_code == 403, response.text
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()
