"""Autonomía por excepción (T-068).

Convierte la aprobación por caso en **supervisión por excepción**: cada
agente tiene una configuración por instalación (``AgentAutonomy``) con un
modo y un umbral; cuando una propuesta cae dentro de lo autorizado, el
agente la ejecuta al instante sin esperar al humano, y queda registrada en
``AgentDecision`` con su efecto, su bandera de desviación y la posibilidad
de revertirla desde el digest diario.

Reglas (deny-by-default, deterministas, sin LLM/red):

- ``mode=manual`` (default) → todo exige aprobación humana: es EXACTAMENTE
  el comportamiento anterior a esta feature. Nada cambia sin configuración.
- ``mode=autonomous`` → solo se auto-ejecutan los tipos de acción
  explícitamente habilitados (``allowed_actions``, con atajos legacy
  ``allow_follow_ups``/``allow_spam_dismissals``) o, para acciones con
  impacto financiero, por debajo de ``max_value_threshold`` EUR, y siempre
  dentro del tope diario ``max_actions_per_day`` por agente. Cualquier otra
  propuesta sigue pendiente de aprobación humana.
- Cada auto-ejecución: la propuesta se marca ``approved`` con
  ``reviewed_by=agent:<id>``, se aplica el efecto con la misma transacción
  que la aprobación humana (``apply_agent_proposal_approved``) y se crea
  la ``AgentDecision`` + auditoría ``agent_decision.auto_executed``.
- Digest diario: agrega las decisiones del periodo por agente, cuenta las
  propuestas que siguen esperando al humano y avisa solo de desviaciones
  si ``notify_on_deviation_only`` está activo.
- Revert: deshace el efecto con trazabilidad (nunca borra evidencia):
  actividades de follow-up → ``cancelled``; mensajes descartados →
  ``triaged`` de nuevo. Auditoría ``agent_decision.reverted``.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.models.models import (
    Activity,
    AgentAutonomy,
    AgentDecision,
    ApprovalRequest,
    AuditLog,
    SocialMessage,
)
from app.services.agent_proposals import (
    AUTOMATION_TOGGLE_ACTION,
    CEO_ADJUST_STOCK_ACTION,
    CEO_ASSIGN_LEAD_ACTION,
    CEO_CLOSE_OPPORTUNITY_ACTION,
    CEO_CREATE_LEAD_ACTION,
    CEO_CREATE_TASK_ACTION,
    CEO_FOLLOW_UP_ACTION,
    CEO_LAUNCH_CAMPAIGN_ACTION,
    CEO_MOVE_OPPORTUNITY_ACTION,
    DISMISS_ACTION,
    FOLLOW_UP_ACTION,
    GHL_CREATE_CONTACT_ACTION,
    GHL_SEND_MESSAGE_ACTION,
)
from sqlalchemy.orm import Session

FOLLOW_UP_ACTIONS = {
    FOLLOW_UP_ACTION,
    CEO_FOLLOW_UP_ACTION,
}

# Acciones seguras y reversibles (cero impacto financiero) que un agente puede
# auto-ejecutar en modo autónomo cuando el dueño las autoriza explícitamente.
# Las acciones financieras/contables NUNCA entran en esta lista: siguen
# exigiendo aprobación humana y servicios deterministas dedicados.
SAFE_AUTO_ACTIONS = frozenset(
    {
        FOLLOW_UP_ACTION,
        CEO_FOLLOW_UP_ACTION,
        DISMISS_ACTION,
        AUTOMATION_TOGGLE_ACTION,
        CEO_CREATE_LEAD_ACTION,
        CEO_MOVE_OPPORTUNITY_ACTION,
        CEO_CREATE_TASK_ACTION,
        CEO_LAUNCH_CAMPAIGN_ACTION,
        # T-082: omnimódulo — seguras y reversibles (asignación, cierre de
        # oportunidad, ajuste de stock). ``ceo_update_price`` NO entra:
        # es financiera y solo se auto-ejecuta bajo el umbral.
        CEO_ASSIGN_LEAD_ACTION,
        CEO_CLOSE_OPPORTUNITY_ACTION,
        CEO_ADJUST_STOCK_ACTION,
        # T-083: canal GHL — enviar un SMS/email a un lead y crear un
        # contacto en GHL. Solo se auto-ejecutan si el dueño las autoriza
        # explícitamente; el efecto queda en el outbox durable (reversible
        # antes de la entrega vía DLQ) y bajo el tope diario.
        GHL_SEND_MESSAGE_ACTION,
        GHL_CREATE_CONTACT_ACTION,
    }
)

# Etiquetas para la UI del portal (misma información que la API devuelve).
SAFE_ACTION_LABELS: dict[str, str] = {
    FOLLOW_UP_ACTION: "Follow-ups de leads",
    CEO_FOLLOW_UP_ACTION: "Follow-ups del CEO (leads fríos)",
    DISMISS_ACTION: "Descartar spam",
    AUTOMATION_TOGGLE_ACTION: "Pausar/activar automatizaciones",
    CEO_CREATE_LEAD_ACTION: "Crear leads",
    CEO_MOVE_OPPORTUNITY_ACTION: "Mover oportunidades",
    CEO_CREATE_TASK_ACTION: "Crear tareas",
    CEO_LAUNCH_CAMPAIGN_ACTION: "Lanzar campañas",
    CEO_ASSIGN_LEAD_ACTION: "Asignar leads a comerciales",
    CEO_CLOSE_OPPORTUNITY_ACTION: "Cerrar oportunidades (ganada/perdida)",
    CEO_ADJUST_STOCK_ACTION: "Ajustar stock de productos",
    GHL_SEND_MESSAGE_ACTION: "Enviar SMS/email a leads vía GHL",
    GHL_CREATE_CONTACT_ACTION: "Crear contactos en GHL",
}

DEFAULT_CONFIG = {
    "mode": "manual",
    "max_value_threshold": 0.0,
    "allow_follow_ups": False,
    "allow_spam_dismissals": False,
    "notify_on_deviation_only": False,
    "allowed_actions": [],
    "max_actions_per_day": 10,
}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _installation_id(db: Session) -> str:
    from app.installation_context import get_current_installation_id

    return get_current_installation_id() or "unknown"


def get_config(
    db: Session,
    *,
    agent_id: str,
    create: bool = True,
) -> AgentAutonomy | None:
    """Configuración durable del agente (get-or-create con defaults)."""

    install_id = _installation_id(db)
    row = (
        db.query(AgentAutonomy)
        .filter(
            AgentAutonomy.installation_id == install_id,
            AgentAutonomy.agent_id == agent_id,
        )
        .first()
    )
    if row is None and create:
        row = AgentAutonomy(
            installation_id=install_id,
            agent_id=agent_id,
            **DEFAULT_CONFIG,
        )
        db.add(row)
        db.flush()
    return row


def effective_config(db: Session, *, agent_id: str) -> dict[str, Any]:
    """Configuración efectiva (defaults deny-by-default + overrides)."""

    row = get_config(db, agent_id=agent_id, create=True)
    config = dict(DEFAULT_CONFIG)
    if row is not None:
        config.update(
            {
                "mode": row.mode,
                "max_value_threshold": float(row.max_value_threshold or 0),
                "allow_follow_ups": bool(row.allow_follow_ups),
                "allow_spam_dismissals": bool(row.allow_spam_dismissals),
                "notify_on_deviation_only": bool(row.notify_on_deviation_only),
                "allowed_actions": list(row.allowed_actions or []),
                "max_actions_per_day": int(
                    row.max_actions_per_day
                    if row.max_actions_per_day is not None
                    else DEFAULT_CONFIG["max_actions_per_day"]
                ),
            }
        )
    return config


def _effective_allowed_actions(config: dict[str, Any]) -> set[str]:
    """Conjunto efectivo de acciones seguras autorizadas.

    ``allowed_actions`` es la fuente de verdad granular. Los flags legacy
    (``allow_follow_ups``/``allow_spam_dismissals``) solo mandan como
    fallback cuando ``allowed_actions`` está vacío, para no romper
    configuraciones guardadas antes de esta feature.
    """

    allowed = set(config.get("allowed_actions") or [])
    if allowed:
        return allowed
    if config.get("allow_follow_ups"):
        allowed.update(FOLLOW_UP_ACTIONS)
    if config.get("allow_spam_dismissals"):
        allowed.add(DISMISS_ACTION)
    return allowed


def _daily_executed_count(db: Session, *, agent_id: str) -> int:
    """Decisiones autónomas de este agente hoy (UTC), ya flusheadas."""

    start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.query(AgentDecision.id)
        .filter(
            AgentDecision.installation_id == _installation_id(db),
            AgentDecision.agent_id == agent_id,
            AgentDecision.executed_at >= start,
        )
        .count()
    )


def _within_daily_cap(
    db: Session,
    approval: ApprovalRequest,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Tope diario: ``max_actions_per_day`` decisiones autónomas por agente."""

    cap = int(config["max_actions_per_day"])
    if cap <= 0:
        return False, "daily_cap_reached"
    used = _daily_executed_count(db, agent_id=str(approval.requested_by or ""))
    if used >= cap:
        return False, "daily_cap_reached"
    return True, "within_threshold"


def evaluate_auto_execution(
    db: Session,
    approval: ApprovalRequest,
) -> tuple[bool, str]:
    """¿Puede esta propuesta ejecutarse sin aprobación humana?

    Devuelve ``(ok, motivo)``. Motivos: ``manual`` (modo por defecto),
    ``follow_ups_not_allowed``, ``spam_dismissals_not_allowed``,
    ``action_not_allowed``, ``over_threshold``, ``daily_cap_reached`` o
    ``unknown_action`` — todos derivan al panel de aprobaciones humanas,
    que es la vía segura por defecto.
    """

    config = effective_config(db, agent_id=str(approval.requested_by or ""))
    if config["mode"] != "autonomous":
        return False, "manual"
    action = approval.action_type
    allowed = _effective_allowed_actions(config)

    if action in SAFE_AUTO_ACTIONS:
        if action not in allowed:
            if action in FOLLOW_UP_ACTIONS:
                return False, "follow_ups_not_allowed"
            if action == DISMISS_ACTION:
                return False, "spam_dismissals_not_allowed"
            return False, "action_not_allowed"
        return _within_daily_cap(db, approval, config)

    # Acciones con impacto económico: solo bajo el umbral, y el umbral debe
    # estar declarado en el payload (``value_eur``) para poder compararlo.
    payload = approval.payload or {}
    value = payload.get("value_eur")
    if value is None:
        return False, "unknown_action"
    try:
        impact = float(value)
    except (TypeError, ValueError):
        return False, "unknown_action"
    if impact > float(config["max_value_threshold"]):
        return False, "over_threshold"
    return _within_daily_cap(db, approval, config)


def auto_execute_proposals(
    db: Session,
    proposals: list[ApprovalRequest],
) -> dict[str, Any]:
    """Auto-ejecuta las propuestas autorizadas; el resto queda pendiente.

    Misma transacción que la aprobación humana (``apply_agent_proposal_``
    ``approved``): efecto aplicado + propuesta marcada ``approved`` con
    ``reviewed_by=agent:<id>`` + ``AgentDecision`` + auditoría. Las no
    autorizadas se devuelven intactas como ``deferred``.
    """

    from app.services.agent_proposals import apply_agent_proposal_approved

    executed: list[AgentDecision] = []
    deferred: list[ApprovalRequest] = []
    for approval in proposals:
        if approval.status != "pending":
            continue
        ok, reason = evaluate_auto_execution(db, approval)
        if not ok:
            deferred.append(approval)
            continue
        now = _utcnow()
        agent_key = f"agent:{approval.requested_by}"
        approval.status = "approved"
        approval.reviewed_at = now
        approval.reviewed_by = agent_key
        applied = apply_agent_proposal_approved(
            db,
            approval,
            reviewed_by=agent_key,
            reviewed_at=now,
        )
        deviation = _detect_deviation(approval, applied)
        decision = AgentDecision(
            installation_id=approval.installation_id,
            agent_id=str(approval.requested_by or ""),
            action_type=approval.action_type,
            target_key=approval.target_key,
            executed_at=now,
            executed_by=agent_key,
            approval_id=approval.id,
            payload={
                "applied": applied,
                "rationale": (approval.payload or {}).get("rationale"),
                "deviation_reason": _deviation_reason(applied),
            },
            deviation=deviation,
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
                    "deviation": deviation,
                    **applied,
                },
            )
        )
        executed.append(decision)
    return {"executed": executed, "deferred": deferred}


def _detect_deviation(
    approval: ApprovalRequest, applied: dict[str, Any]
) -> bool:
    """Desviación = el efecto no es exactamente el esperado.

    - Follow-up: se reutilizó una actividad existente (ya había una
      pendiente del mismo título creada por este agente).
    - Descarte de spam: el mensaje ya no estaba en ``triaged`` (ya
      descartado o atendido por otro camino).
    """

    if approval.action_type in FOLLOW_UP_ACTIONS:
        return bool(applied.get("reused"))
    if approval.action_type == DISMISS_ACTION:
        return bool(applied.get("already_dismissed"))
    return False


def _deviation_reason(applied: dict[str, Any]) -> str | None:
    if applied.get("reused"):
        return "Se reutilizó una actividad de follow-up ya existente del mismo agente"
    if applied.get("already_dismissed"):
        return "El mensaje ya no estaba en estado triaged (ya descartado o atendido)"
    return None


def build_digest(
    db: Session,
    *,
    days: int = 1,
    include_pending: bool = True,
) -> dict[str, Any]:
    """Digest diario: decisiones auto-ejecutadas + pendientes humanas.

    Agrega por agente las decisiones del periodo (con conteo de
    desviaciones y reverts), lista las últimas con su efecto, y opcionalmente
    cuenta las propuestas que siguen esperando aprobación humana (la parte
    que NO se auto-ejecutó, p. ej. por umbral). El campo
    ``deviations_only`` refleja la configuración ``notify_on_deviation_only``
    del agente para que el canal que emita el digest decida si avisa.
    """

    days = max(1, int(days or 1))
    since = _utcnow() - datetime.timedelta(days=days)
    install_id = _installation_id(db)
    decisions = (
        db.query(AgentDecision)
        .filter(
            AgentDecision.installation_id == install_id,
            AgentDecision.executed_at >= since,
        )
        .order_by(AgentDecision.executed_at.desc())
        .all()
    )
    # Labels en lenguaje llano para el digest y la supervisión: el dueño
    # no reconoce ``agent_proposal:create_follow_up`` ni UUIDs, sí «crear un
    # seguimiento» y el nombre del lead. Import perezoso (evita el ciclo
    # ceo_agent ↔ autonomy; mismo patrón que daily_digest).
    from app.services import ceo_agent  # noqa: PLC0415

    by_agent: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        bucket = by_agent.setdefault(
            decision.agent_id,
            {
                "agent_id": decision.agent_id,
                "agent_label": ceo_agent._plain_requester(decision.agent_id),
                "total": 0,
                "deviations": 0,
                "reverted": 0,
                "deviations_only": False,
            },
        )
        bucket["total"] += 1
        if decision.deviation:
            bucket["deviations"] += 1
        if decision.reverted_at is not None:
            bucket["reverted"] += 1
        config = effective_config(db, agent_id=decision.agent_id)
        bucket["deviations_only"] = bool(config["notify_on_deviation_only"])

    pending_count = 0
    if include_pending:
        pending_count = int(
            db.query(ApprovalRequest.id)
            .filter(
                ApprovalRequest.installation_id == install_id,
                ApprovalRequest.status == "pending",
                ApprovalRequest.action_type.like("agent_proposal:%"),
            )
            .count()
        )
    return {
        "window_days": days,
        "since": since.isoformat(),
        "until": _utcnow().isoformat(),
        "total_decisions": len(decisions),
        "by_agent": sorted(by_agent.values(), key=lambda b: -b["total"]),
        "pending_human_approvals": pending_count,
        "decisions": [
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
                "executed_by": d.executed_by,
                "deviation": d.deviation,
                "deviation_reason": (d.payload or {}).get("deviation_reason"),
                "reverted": d.reverted_at is not None,
                "reverted_at": d.reverted_at.isoformat() if d.reverted_at else None,
                "reverted_by": d.reverted_by,
                "revert_reason": d.revert_reason,
                "applied": (d.payload or {}).get("applied") or {},
            }
            for d in decisions
        ],
    }


def revert_decision(
    db: Session,
    decision: AgentDecision,
    *,
    reverted_by: str,
    reason: str,
) -> AgentDecision:
    """Revierte una decisión auto-ejecutada con trazabilidad (best-effort).

    Nunca borra evidencia: la actividad de follow-up pasa a ``cancelled``
    y el mensaje descartado vuelve a ``triaged`` (si el estado actual lo
    permite). El registro de la decisión conserva quién/motivo/fecha del
    revert y se audita ``agent_decision.reverted``.
    """

    if decision.reverted_at is not None:
        raise ValueError("La decisión ya fue revertida")
    applied = (decision.payload or {}).get("applied") or {}
    if decision.action_type in FOLLOW_UP_ACTIONS:
        activity_id = applied.get("activity_id")
        if activity_id:
            activity = (
                db.query(Activity)
                .filter(Activity.id == activity_id)
                .first()
            )
            if activity is not None and activity.status == "pending":
                activity.status = "cancelled"
                note = (
                    f"Revocada por {reverted_by} ({reason}) — "
                    "decisión autónoma revertida desde el digest"
                )
                activity.description = (
                    f"{activity.description}\n{note}"
                    if activity.description
                    else note
                )
                db.flush()
    elif decision.action_type == DISMISS_ACTION:
        message_id = applied.get("message_id") or decision.target_key
        message = (
            db.query(SocialMessage)
            .filter(SocialMessage.id == message_id)
            .first()
        )
        if message is not None and message.status == "dismissed":
            message.status = "triaged"
            db.flush()

    now = _utcnow()
    decision.reverted_at = now
    decision.reverted_by = reverted_by
    decision.revert_reason = reason
    db.add(
        AuditLog(
            installation_id=decision.installation_id,
            agent_id=decision.agent_id,
            user_id=None,
            event_type="agent_decision.reverted",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={
                "decision_id": decision.id,
                "action_type": decision.action_type,
                "target_key": decision.target_key,
                "reverted_by": reverted_by,
                "reason": reason,
            },
        )
    )
    db.flush()
    return decision
