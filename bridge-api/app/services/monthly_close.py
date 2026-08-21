"""Cierra el mes (T-070): primer proceso completo en piloto automático.

Un agente coordinador (``finance_agent``) ejecuta la secuencia mensual del
dueño en un solo disparo, con **política de riesgo por paso**:

1. **Reconciliar ventas** — política ``read`` (solo lectura, siempre se
   ejecuta): pedidos confirmados del periodo, importe facturado vs pedido,
   pedidos sin factura (discrepancias) y facturas pendientes de aprobación.
2. **Emitir facturas** — política ``financial``: por cada pedido confirmado
   del periodo sin factura se crea el ``InvoiceDraft`` y un
   ``ApprovalRequest`` ``issue_invoice`` con ``value_eur``. La configuración
   de autonomía del ``finance_agent`` (T-068) decide: si ``mode=autonomous``
   y el importe está bajo el umbral, se emite y envía al instante (queda
   registrada como ``AgentDecision``); si no, queda pendiente de aprobación
   humana en el panel — los agentes proponen, el humano decide.
3. **Disparar dunning** — política ``communication``: recordatorios de
   facturas vencidas (no mutan importes). Solo se envían en modo autónomo;
   en modo manual se informan como diferidas al humano.
4. **Generar el reporte** — política ``read``: agrega el resultado del cierre
   y, si el dueño tiene correo configurado (``OWNER_COMMAND_EMAIL``), se lo
   envía por el router de email (SMTP real o spool con degradación auditada).

Reglas (deny-by-default, deterministas, sin LLM/red):

- ``dry_run=True`` no muta nada: solo reconcilia y proyecta lo que haría
  cada paso, sin crear facturas, aprobaciones, correos ni decisiones.
- Cada factura emite una única propuesta ``issue_invoice`` (dedupe por
  pedido: un pedido sin factura solo se propone una vez).
- Todo queda auditado: ``monthly_close.run`` por paso con sus conteos y la
  ``AgentDecision`` + ``agent_decision.auto_executed`` por cada factura
  auto-emitida.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from app.config import settings
from app.models.models import (
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    Customer,
    InvoiceDraft,
    Order,
)
from app.services.automations import (
    dunning_processor,
    generate_invoice_pdf,
    send_email,
)
from app.services.autonomy import effective_config, evaluate_auto_execution
from sqlalchemy.orm import Session

FINANCE_AGENT_ID = "finance_agent"
_FINANCE_AGENT_KEY = f"agent:{FINANCE_AGENT_ID}"
_DUNNING_OVERDUE_STATUSES = ("draft", "sent", "overdue")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _month_bounds(period: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Límites [inicio, fin) del periodo ``YYYY-MM`` (UTC naive)."""

    try:
        start = datetime.datetime.strptime(period, "%Y-%m")
    except ValueError as exc:
        raise ValueError(
            "El periodo debe tener formato YYYY-MM, p. ej. 2026-07"
        ) from exc
    if start.month == 12:
        end = datetime.datetime(start.year + 1, 1, 1)
    else:
        end = datetime.datetime(start.year, start.month + 1, 1)
    return start, end


def _period_label(period: str | None) -> str:
    return period or _utcnow().strftime("%Y-%m")


def _invoice_customer_email(db: Session, invoice: InvoiceDraft) -> str | None:
    customer = (
        db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    )
    return customer.email if customer else None


def _audit(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: dict[str, Any],
    actor: str | None = None,
) -> None:
    db.add(
        AuditLog(
            correlation_id=f"monthly-close-{uuid.uuid4().hex[:12]}",
            agent_id=FINANCE_AGENT_ID,
            user_id=actor,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )


# ---------------------------------------------------------------------------
# Paso 1 — Reconciliar ventas (política: read)
# ---------------------------------------------------------------------------


def _reconcile(
    db: Session,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> dict[str, Any]:
    orders = (
        db.query(Order)
        .filter(
            Order.created_at >= start,
            Order.created_at < end,
            Order.status == "confirmed",
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    total_orders_value = Decimal("0.00")
    invoiced_value = Decimal("0.00")
    un_invoiced: list[dict[str, Any]] = []
    for order in orders:
        total_orders_value += Decimal(order.grand_total or 0)
        invoice = (
            db.query(InvoiceDraft)
            .filter(InvoiceDraft.order_id == order.id)
            .first()
        )
        if invoice is None:
            un_invoiced.append(
                {
                    "order_id": order.id,
                    "amount": float(order.grand_total),
                    "currency": order.currency,
                    "customer_id": order.customer_id,
                }
            )
        else:
            invoiced_value += Decimal(invoice.total_amount or 0)
    pending_approvals = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.action_type == "issue_invoice",
            ApprovalRequest.status == "pending",
        )
        .count()
    )
    return {
        "policy": "read",
        "orders": len(orders),
        "orders_value": float(total_orders_value),
        "invoiced_value": float(invoiced_value),
        "un_invoiced_orders": len(un_invoiced),
        "un_invoiced": un_invoiced[:50],
        "pending_invoice_approvals": pending_approvals,
        "currency": orders[0].currency if orders else "EUR",
    }


# ---------------------------------------------------------------------------
# Paso 2 — Emitir facturas (política: financial)
# ---------------------------------------------------------------------------


def _create_invoice_approval(
    db: Session,
    order: Order,
    *,
    period: str,
    now: datetime.datetime,
) -> tuple[InvoiceDraft, ApprovalRequest]:
    invoice = InvoiceDraft(
        id=f"inv-{uuid.uuid4().hex[:12]}",
        invoice_number=f"{settings.INVOICE_SERIES}{uuid.uuid4().hex[:8].upper()}",
        order_id=order.id,
        customer_id=order.customer_id,
        items=order.items,
        total_amount=order.grand_total,
        tax_amount=order.tax_total,
        currency=order.currency,
        status="pending_approval" if settings.PILOT_MODE else "draft",
    )
    db.add(invoice)
    db.flush()
    approval = ApprovalRequest(
        id=f"appr-{uuid.uuid4().hex[:12]}",
        action_type="issue_invoice",
        target_key=invoice.id,
        payload={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "order_id": order.id,
            "amount": float(invoice.total_amount),
            "currency": invoice.currency,
            "value_eur": float(invoice.total_amount),
            "rationale": (
                f"Factura del pedido {order.id} confirmado en {period} "
                "(cierre mensual)"
            ),
        },
        requested_by=FINANCE_AGENT_ID,
        status="pending",
    )
    db.add(approval)
    db.flush()
    return invoice, approval


def _auto_execute_invoice(
    db: Session,
    approval: ApprovalRequest,
    invoice: InvoiceDraft,
    *,
    actor: str,
) -> dict[str, Any]:
    """Emite y envía la factura en el mismo disparo (política financiera
    autorizada por la configuración de autonomía del ``finance_agent``)."""

    now = _utcnow()
    agent_key = f"agent:{approval.requested_by}"
    approval.status = "approved"
    approval.reviewed_at = now
    approval.reviewed_by = agent_key
    invoice.status = "approved"

    delivery_status: str | None = None
    email = _invoice_customer_email(db, invoice)
    if email:
        pdf = generate_invoice_pdf(invoice, db=db)
        delivery = send_email(
            db,
            to=email,
            subject=f"Factura {invoice.invoice_number}",
            body=(
                f"Adjuntamos la factura {invoice.invoice_number} por "
                f"{invoice.total_amount} {invoice.currency} "
                f"correspondiente al pedido {invoice.order_id}."
            ),
            attachments=[
                {
                    "filename": f"{invoice.invoice_number}.pdf",
                    "content": pdf,
                    "mime_type": "application/pdf",
                }
            ],
            actor=actor,
        )
        delivery_status = delivery.status if delivery else "recipient_unavailable"

    applied = {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "order_id": invoice.order_id,
        "amount": float(invoice.total_amount),
        "currency": invoice.currency,
        "delivery_status": delivery_status,
    }
    decision = AgentDecision(
        installation_id=approval.installation_id,
        agent_id=str(approval.requested_by or ""),
        action_type="issue_invoice",
        target_key=invoice.id,
        executed_at=now,
        executed_by=agent_key,
        approval_id=approval.id,
        payload={
            "applied": applied,
            "rationale": (approval.payload or {}).get("rationale"),
        },
        deviation=False,
    )
    db.add(decision)
    db.flush()
    db.add(
        AuditLog(
            installation_id=approval.installation_id,
            agent_id=str(approval.requested_by or ""),
            user_id=None,
            event_type="agent_decision.auto_executed",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={
                "decision_id": decision.id,
                "approval_id": approval.id,
                "action_type": approval.action_type,
                "target_key": approval.target_key,
                "deviation": False,
                **applied,
            },
        )
    )
    return applied


def _invoice_step(
    db: Session,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
    period: str,
    dry_run: bool,
    actor: str,
) -> dict[str, Any]:
    now = _utcnow()
    orders = (
        db.query(Order)
        .filter(
            Order.created_at >= start,
            Order.created_at < end,
            Order.status == "confirmed",
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    # Simplificación determinista: por cada pedido sin factura consultamos
    # directamente (los volúmenes mensuales son pequeños y la consulta por
    # pedido es indexada).
    candidates: list[Order] = []
    for order in orders:
        invoice = (
            db.query(InvoiceDraft)
            .filter(InvoiceDraft.order_id == order.id)
            .first()
        )
        if invoice is None:
            candidates.append(order)

    created = 0
    auto_executed: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    if dry_run:
        return {
            "policy": "financial",
            "dry_run": True,
            "orders_without_invoice": len(candidates),
            "approvals_created": 0,
            "would_create_approvals": len(candidates),
            "auto_executed": [],
            "deferred": [],
        }

    for order in candidates:
        invoice, approval = _create_invoice_approval(
            db, order, period=period, now=now
        )
        created += 1
        ok, reason = evaluate_auto_execution(db, approval)
        if ok:
            applied = _auto_execute_invoice(
                db, approval, invoice, actor=actor
            )
            auto_executed.append(applied)
        else:
            deferred.append(
                {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "order_id": order.id,
                    "amount": float(invoice.total_amount),
                    "currency": invoice.currency,
                    "reason": reason,
                }
            )
    return {
        "policy": "financial",
        "dry_run": False,
        "orders_without_invoice": len(candidates),
        "approvals_created": created,
        "auto_executed": auto_executed,
        "deferred": deferred,
        "deferred_value": sum(
            float(d["amount"]) for d in deferred
        ),
    }


# ---------------------------------------------------------------------------
# Paso 3 — Disparar dunning (política: communication)
# ---------------------------------------------------------------------------


def _dunning_step(
    db: Session,
    *,
    dry_run: bool,
    actor: str,
) -> dict[str, Any]:
    config = effective_config(db, agent_id=FINANCE_AGENT_ID)
    threshold = _utcnow() - datetime.timedelta(
        days=settings.AUTOMATION_DUNNING_OVERDUE_DAYS
    )
    overdue = (
        db.query(InvoiceDraft)
        .filter(
            InvoiceDraft.created_at <= threshold,
            InvoiceDraft.status.in_(_DUNNING_OVERDUE_STATUSES),
        )
        .count()
    )
    if config["mode"] != "autonomous" or dry_run:
        return {
            "policy": "communication",
            "mode": config["mode"],
            "dry_run": dry_run,
            "overdue_invoices": overdue,
            "processed": 0,
            "deferred_to_human": overdue,
        }
    result = dunning_processor(db, actor=actor)
    return {
        "policy": "communication",
        "mode": config["mode"],
        "dry_run": False,
        "overdue_invoices": overdue,
        "processed": result["processed"],
        "delivered": result["delivered"],
        "queued_for_manual_delivery": result["queued_for_manual_delivery"],
        "failed": result["failed"],
        "deferred_to_human": 0,
    }


# ---------------------------------------------------------------------------
# Paso 4 — Generar el reporte (política: read)
# ---------------------------------------------------------------------------


def _report_step(
    db: Session,
    *,
    period: str,
    reconcile: dict[str, Any],
    invoice: dict[str, Any],
    dunning: dict[str, Any],
    dry_run: bool,
    actor: str,
) -> dict[str, Any]:
    deferred_value = invoice.get("deferred_value", 0.0)
    auto_value = sum(float(a.get("amount", 0)) for a in invoice.get("auto_executed", []))
    lines = [
        f"Cierre mensual {period} — Agentes IA (finance_agent)",
        "=" * 60,
        "",
        f"Pedidos confirmados:      {reconcile['orders']}",
        f"Importe pedido:           {reconcile['orders_value']} {reconcile['currency']}",
        f"Importe facturado:        {reconcile['invoiced_value']} {reconcile['currency']}",
        f"Pedidos sin facturar:     {reconcile['un_invoiced_orders']}",
        f"Aprobaciones de factura pendientes (previas): {reconcile['pending_invoice_approvals']}",
        "",
        "Emisión de facturas:",
        f"  Propuestas creadas:     {invoice.get('approvals_created', 0)}",
        f"  Auto-emitidas (agente): {len(invoice.get('auto_executed', []))} ({auto_value} {reconcile['currency']})",
        f"  Pendientes de humano:   {len(invoice.get('deferred', []))} ({deferred_value} {reconcile['currency']})",
        "",
        "Dunning:",
        f"  Facturas vencidas:      {dunning['overdue_invoices']}",
        f"  Recordatorios enviados: {dunning.get('processed', 0)}",
        f"  Diferidos al humano:    {dunning.get('deferred_to_human', 0)}",
    ]
    report_text = "\n".join(lines)

    delivery_status: str | None = None
    owner_email = settings.OWNER_COMMAND_EMAIL
    if owner_email and not dry_run:
        delivery = send_email(
            db,
            to=owner_email,
            subject=f"Reporte de cierre mensual {period}",
            body=report_text,
            actor=actor,
        )
        delivery_status = delivery.status if delivery else "failed"
        _audit(
            db,
            event_type="monthly_close.report_sent",
            status_value=(
                "success"
                if delivery and delivery.accepted
                else (
                    "pending"
                    if delivery and delivery.status == "queued_for_manual_delivery"
                    else "error"
                )
            ),
            details={
                "period": period,
                "to": owner_email,
                "delivery_status": delivery_status,
            },
            actor=actor,
        )
    else:
        delivery_status = "not_sent" if dry_run else "no_owner_email"

    return {
        "policy": "read",
        "dry_run": dry_run,
        "owner_email": owner_email or None,
        "delivery_status": delivery_status,
        "text": report_text,
    }


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def run_monthly_close(
    db: Session,
    *,
    period: str | None = None,
    dry_run: bool = False,
    actor: str | None = None,
) -> dict[str, Any]:
    """Ejecuta la secuencia completa «cierra el mes» con política de riesgo
    por paso; devuelve el resultado estructurado y lo audita."""

    actor = actor or _FINANCE_AGENT_KEY
    label = _period_label(period)
    start, end = _month_bounds(label)

    reconcile = _reconcile(db, start=start, end=end)
    invoice = _invoice_step(
        db,
        start=start,
        end=end,
        period=label,
        dry_run=dry_run,
        actor=actor,
    )
    dunning = _dunning_step(db, dry_run=dry_run, actor=actor)
    report = _report_step(
        db,
        period=label,
        reconcile=reconcile,
        invoice=invoice,
        dunning=dunning,
        dry_run=dry_run,
        actor=actor,
    )
    _audit(
        db,
        event_type="monthly_close.run",
        status_value="dry_run" if dry_run else "success",
        details={
            "period": label,
            "dry_run": dry_run,
            "orders": reconcile["orders"],
            "orders_value": reconcile["orders_value"],
            "un_invoiced_orders": reconcile["un_invoiced_orders"],
            "approvals_created": invoice.get("approvals_created", 0),
            "auto_executed": len(invoice.get("auto_executed", [])),
            "deferred_to_human": len(invoice.get("deferred", [])),
            "dunning_processed": dunning.get("processed", 0),
            "dunning_deferred": dunning.get("deferred_to_human", 0),
            "report_delivery_status": report["delivery_status"],
        },
        actor=actor,
    )
    db.commit()
    return {
        "period": label,
        "dry_run": dry_run,
        "steps": {
            "reconcile": reconcile,
            "invoice": invoice,
            "dunning": dunning,
            "report": report,
        },
        "summary": {
            "orders": reconcile["orders"],
            "orders_value": reconcile["orders_value"],
            "invoiced_value": reconcile["invoiced_value"],
            "un_invoiced_orders": reconcile["un_invoiced_orders"],
            "approvals_created": invoice.get("approvals_created", 0),
            "invoices_auto_emitted": len(invoice.get("auto_executed", [])),
            "invoices_deferred_to_human": len(invoice.get("deferred", [])),
            "dunning_sent": dunning.get("processed", 0),
            "dunning_deferred": dunning.get("deferred_to_human", 0),
        },
    }
