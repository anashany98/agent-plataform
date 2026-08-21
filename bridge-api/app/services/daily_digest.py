"""Digest diario por email (T-074).

Cada día (tarea programada ``daily_digest``) el dueño recibe un resumen de:

- **Decisiones de los agentes** (autonomía por excepción, T-068): qué agente
  ejecutó qué acción hoy, si se desvió del plan y el estado del revert. Cada
  decisión no revertida incluye la instrucción ``REVERTIR <id>``.
- **Propuestas pendientes de aprobación** (``ApprovalRequest`` ``pending``):
  cuántas y las primeras, para que el dueño no pierda de vista la cola.
- **Métricas clave del día**: ventas (oportunidades, ticket medio, pedidos),
  pipeline, cola de aprobaciones, agentes activos y stock bajo.

**Revertir desde el propio correo**: el webhook de email del mando del dueño
(``command_surface.handle_owner_email``) reconoce el comando
``REVERTIR <decision_id>`` y revierte la decisión con la misma trazabilidad
que el portal (``autonomy.revert_decision``), respondiendo la confirmación
por el spool/SMTP.

El envío reutiliza ``automations.send_email``: SMTP real si está configurado
o spool local con degradación auditada (nunca pérdida silenciosa). Sin
``OWNER_COMMAND_EMAIL`` configurado el digest se omite de forma auditada.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from app.config import settings
from app.models.models import (
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    ScheduledTask,
)
from sqlalchemy.orm import Session

# Comando para revertir una decisión respondiendo al correo del digest.
REVERT_COMMAND_PATTERN = re.compile(
    r"(?i)^\s*(?:revertir|revocar|undo)\s+([a-z0-9][a-z0-9-]{7,})\b",
)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _installation_id(db: Session) -> str:
    from app.installation_context import get_current_installation_id

    return get_current_installation_id() or "unknown"


def _audit_digest(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            installation_id=_installation_id(db),
            agent_id="finance_agent",
            user_id=None,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )


def _since(now: datetime.datetime) -> datetime.datetime:
    """Ventana del digest: últimas 24 horas (día anterior al envío)."""
    return now - datetime.timedelta(days=1)


def build_digest(
    db: Session,
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Construye el contenido del digest con datos reales (solo lectura)."""
    now = now or _utcnow()
    since = _since(now)

    decisions_rows = (
        db.query(AgentDecision)
        .filter(AgentDecision.executed_at >= since)
        .order_by(AgentDecision.executed_at.desc())
        .limit(50)
        .all()
    )
    # Labels en lenguaje llano (mismos que el chat del CEO): el dueño no
    # reconoce ``agent_proposal:create_follow_up`` ni UUIDs, sí «crear un
    # seguimiento» y el nombre del lead.
    from app.services import ceo_agent

    decisions = [
        {
            "id": d.id,
            "agent_id": d.agent_id,
            "agent_label": ceo_agent._plain_requester(d.agent_id),
            "action_type": d.action_type,
            "action_label": ceo_agent._plain_proposal_label(d.action_type),
            "target_key": d.target_key,
            "target_kind": (_tgt := ceo_agent._resolve_target(
                db,
                {
                    "action_type": d.action_type,
                    "target_key": d.target_key,
                    "payload": d.payload,
                },
            ))[0],
            "target_focus_id": _tgt[1],
            "target_label": _tgt[2],
            "executed_at": d.executed_at.isoformat(),
            "deviation": bool(d.deviation),
            "reverted": d.reverted_at is not None,
            "summary": (d.payload or {}).get("summary")
            or (d.payload or {}).get("rationale")
            or d.action_type,
        }
        for d in decisions_rows
    ]

    pending_count = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == "pending")
        .count()
    )
    pending_rows = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.created_at.asc())
        .limit(8)
        .all()
    )
    pending = [
        {
            "id": p.id,
            "action_type": p.action_type,
            "action_label": ceo_agent._plain_proposal_label(p.action_type),
            "target_key": p.target_key,
            "target_kind": (_ptgt := ceo_agent._resolve_target(
                db,
                {
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "payload": p.payload,
                },
            ))[0],
            "target_focus_id": _ptgt[1],
            "target_label": _ptgt[2],
            "requested_by": p.requested_by,
            "requested_by_label": ceo_agent._plain_requester(p.requested_by or ""),
            "created_at": p.created_at.isoformat(),
            "summary": (p.payload or {}).get("rationale")
            or (p.payload or {}).get("name")
            or p.action_type,
        }
        for p in pending_rows
    ]

    # Métricas clave reutilizando los gatherers del CEO agent (misma fuente
    # de verdad que el chat universal).
    sales = ceo_agent._gather_sales(db)
    pipeline = ceo_agent._gather_pipeline(db)
    approvals = ceo_agent._gather_approvals(db)
    agents = ceo_agent._gather_agents(db)
    stock = ceo_agent._gather_stock(db)
    agents_active = sum(
        1 for item in agents.get("items", []) if item.get("status") == "active"
    )

    return {
        "generated_at": now.isoformat(),
        "window": {"since": since.isoformat(), "until": now.isoformat()},
        "decisions": decisions,
        "decisions_total": len(decisions),
        "decisions_deviated": sum(1 for d in decisions if d["deviation"]),
        "decisions_reverted": sum(1 for d in decisions if d["reverted"]),
        "pending": pending,
        "pending_total": pending_count,
        "metrics": {
            "sales": sales,
            "pipeline_open_total": pipeline.get("open_total", 0.0),
            "approvals_pending": approvals.get("pending", 0),
            "agents_active": agents_active,
            "agents_total": agents.get("total", 0),
            "low_stock_count": stock.get("low_count", 0),
        },
    }


def _fmt_eur(value: float) -> str:
    return f"{float(value):,.2f} €".replace(",", " ")


_TARGET_MODULE_HINTS: dict[str, str] = {
    "lead": " (en Clientes)",
    "opportunity": " (en Clientes)",
    "contact": " (en Clientes)",
    "social_message": " (en Clientes)",
    "task": " (en Clientes)",
    "campaign": " (en Clientes)",
    "invoice": " (en Ventas)",
    "product": " (en Catálogo)",
    "automation": " (en Automatizaciones)",
}


def _target_module_hint(kind: str | None) -> str:
    return _TARGET_MODULE_HINTS.get(kind or "", "")


def render_digest_text(digest: dict[str, Any]) -> str:
    """Texto plano legible (también se usa como cuerpo del correo)."""
    lines: list[str] = []
    lines.append("RESUMEN DIARIO DE TU EMPRESA")
    lines.append("=" * 34)
    lines.append("")
    generated = digest["generated_at"]
    lines.append(f"Generado: {generated[:16].replace('T', ' ')}")
    lines.append("")

    lines.append("1) DECISIONES DE LOS AGENTES (autonomía)")
    lines.append("-" * 36)
    decisions = digest["decisions"]
    if not decisions:
        lines.append("Ningún agente ejecutó acciones automáticas en las últimas 24 h.")
    else:
        for d in decisions:
            state = "REVERTIDA" if d["reverted"] else "en vigor"
            deviation = " · DESVIACIÓN" if d["deviation"] else ""
            lines.append(
                f"- {d.get('agent_label') or d['agent_id']} · "
                f"{d.get('action_label') or d['action_type']} · "
                f"{d.get('target_label') or d['target_key']}"
                f"{_target_module_hint(d.get('target_kind'))}"
            )
            lines.append(f"    {d['summary']}")
            lines.append(f"    Estado: {state}{deviation} · {d['executed_at'][:16].replace('T', ' ')}")
            if not d["reverted"]:
                lines.append(f"    Para anularla, responde a este correo: REVERTIR {d['id']}")
        lines.append("")
        lines.append(
            f"Total: {digest['decisions_total']} · desviaciones: {digest['decisions_deviated']}"
            f" · revertidas: {digest['decisions_reverted']}"
        )
    lines.append("")

    lines.append("2) PROPUESTAS PENDIENTES DE APROBACIÓN")
    lines.append("-" * 36)
    pending = digest["pending"]
    if not pending:
        lines.append("No hay propuestas pendientes. ¡Cola al día!")
    else:
        for p in pending:
            requester = p.get("requested_by_label") or p.get("requested_by") or "sistema"
            lines.append(
                f"- [{p.get('action_label') or p['action_type']}] "
                f"{p.get('target_label') or p['target_key']}"
                f"{_target_module_hint(p.get('target_kind'))} · solicitada por {requester}"
            )
            lines.append(f"    {p['summary']}")
            lines.append(f"    Pendiente desde {p['created_at'][:16].replace('T', ' ')}")
        lines.append("")
        lines.append(
            f"Total pendientes: {digest['pending_total']}. Aprueba desde el portal en Aprobaciones."
        )
    lines.append("")

    lines.append("3) MÉTRICAS CLAVE")
    lines.append("-" * 36)
    m = digest["metrics"]
    sales = m["sales"]
    lines.append(f"- Ventas: {sales['open_count']} oportunidades abiertas "
                 f"({_fmt_eur(sales['open_value'])}) · ticket medio {_fmt_eur(sales['ticket_medio'])}")
    lines.append(f"- Pipeline: {_fmt_eur(m['pipeline_open_total'])} en curso · "
                 f"pedidos: {sales['orders_count']} · win-rate: {sales['win_rate']}%")
    lines.append(
        f"- Aprobaciones pendientes: {m['approvals_pending']} · "
        f"stock bajo: {m['low_stock_count']}"
    )
    lines.append(f"- Agentes activos: {m['agents_active']} de {m['agents_total']}")
    lines.append("")
    lines.append("Puedes preguntar cualquier cosa respondiendo a este correo "
                 "o escribir REVERTIR <id> para anular una decisión.")
    return "\n".join(lines)


def send_daily_digest(
    db: Session,
    *,
    dry_run: bool = False,
    now: datetime.datetime | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Construye y envía el digest al dueño (SMTP real o spool degradado)."""
    owner = (settings.OWNER_COMMAND_EMAIL or "").strip().lower()
    if not owner:
        _audit_digest(
            db,
            event_type="daily_digest.skipped",
            status_value="skipped",
            details={"reason": "no_owner_email", "dry_run": dry_run},
        )
        db.commit()
        return {
            "status": "skipped",
            "reason": "no_owner_email",
            "detail": "Configura OWNER_COMMAND_EMAIL para recibir el digest.",
        }

    digest = build_digest(db, now=now)
    body = render_digest_text(digest)
    subject = (
        f"Resumen diario · {digest['generated_at'][:10]} · "
        f"{digest['decisions_total']} decisiones, "
        f"{digest['pending_total']} propuestas"
    )
    if dry_run:
        return {
            "status": "dry_run",
            "to": owner,
            "subject": subject,
            "body": body,
            "digest": digest,
        }

    from app.services import automations

    result = automations.send_email(
        db,
        to=owner,
        subject=subject[:200],
        body=body,
        actor=actor or "agent:finance_agent",
    )
    _audit_digest(
        db,
        event_type="daily_digest.sent",
        status_value="success" if result.accepted else "degraded",
        details={
            "to": owner,
            "subject": subject[:200],
            "decisions_total": digest["decisions_total"],
            "pending_total": digest["pending_total"],
            "reference": result.reference,
            "accepted": bool(result.accepted),
            "provider": result.provider,
        },
    )
    db.commit()
    return {
        "status": "sent" if result.accepted else "degraded_to_spool",
        "to": owner,
        "subject": subject,
        "reference": result.reference,
        "accepted": bool(result.accepted),
        "provider": result.provider,
        "digest": digest,
    }


def ensure_daily_digest_task(db: Session) -> dict[str, Any]:
    """Garantiza la tarea programada diaria (dedupe por tipo). No reactiva
    una tarea pausada manualmente: el humano manda."""
    existing = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.task_type == "daily_digest")
        .first()
    )
    if existing is not None:
        return {"task_id": existing.id, "status": existing.status, "created": False}
    owner = (settings.OWNER_COMMAND_EMAIL or "").strip().lower()
    task = ScheduledTask(
        id=f"task-{__import__('uuid').uuid4().hex[:12]}",
        name="Digest diario al dueño",
        task_type="daily_digest",
        payload={"to": owner or "", "subject_prefix": "Resumen diario"},
        interval_seconds=86_400,
        status="active",
        version=1,
        next_run_at=_utcnow() + datetime.timedelta(days=1),
        created_by="system",
        updated_by="system",
    )
    db.add(task)
    db.commit()
    return {"task_id": task.id, "status": task.status, "created": True}


def parse_revert_command(message: str) -> str | None:
    """Extrae el id de decisión del comando REVERTIR (o None)."""
    match = REVERT_COMMAND_PATTERN.search(message or "")
    return match.group(1) if match else None


def revert_from_email(
    db: Session,
    *,
    decision_id: str,
    sender: str,
) -> dict[str, Any]:
    """Revierte una decisión citada en el correo del digest (trazabilidad).

    Devuelve el resultado para que el mando del dueño responda por el spool
    con la confirmación o el motivo del fallo. Nunca borra evidencia.
    """
    from app.services import autonomy

    decision = (
        db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
    )
    if decision is None:
        _audit_digest(
            db,
            event_type="daily_digest.revert.not_found",
            status_value="not_found",
            details={"decision_id": decision_id, "sender": sender},
        )
        db.commit()
        return {
            "status": "not_found",
            "message": f"No encontré la decisión {decision_id}. Revisa el id en el correo del digest.",
        }
    if decision.reverted_at is not None:
        _audit_digest(
            db,
            event_type="daily_digest.revert.already_reverted",
            status_value="skipped",
            details={"decision_id": decision_id, "sender": sender},
        )
        db.commit()
        return {
            "status": "already_reverted",
            "message": f"La decisión {decision_id} ya estaba revertida.",
        }
    autonomy.revert_decision(
        db,
        decision,
        reverted_by=sender,
        reason="Revertida desde el correo del digest por el dueño",
    )
    _audit_digest(
        db,
        event_type="daily_digest.revert",
        status_value="success",
        details={
            "decision_id": decision.id,
            "action_type": decision.action_type,
            "target_key": decision.target_key,
            "sender": sender,
        },
    )
    db.commit()
    return {
        "status": "reverted",
        "decision_id": decision.id,
        "message": (
            f"Decisión {decision.id} revertida ({decision.action_type} · "
            f"{decision.target_key}). La evidencia queda auditada."
        ),
    }
