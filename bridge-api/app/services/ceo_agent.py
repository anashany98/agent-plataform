"""CEO agent (T-067): mando en lenguaje natural para el dueño de la empresa.

Una sola persona gestiona toda la empresa conversando con su asistente de
dirección. El CEO agent resuelve la intención de cada mensaje de forma
**determinista** (sin LLM ni red: normalización + catálogo de palabras
clave con puntuación) y delega en los datos reales de los módulos:

- Intenciones de **lectura** (ventas, pipeline, leads, actividades,
  aprobaciones, inbox social, stock): recopila datos verificados de la BD y
  sintetiza la respuesta — con el LLM configurado si lo hay, o con plantillas
  deterministas honestas (nunca inventa cifras).
- Intenciones de **acción** (follow-up de leads fríos): NO ejecuta. Crea
  ``ApprovalRequest`` ``agent_proposal:ceo_follow_up`` que el dueño aprueba
  en el panel de Aprobaciones; aprobarla crea la actividad (misma
  transacción, auditado). Regla innegociable: los agentes proponen, el
  humano decide.

Cada mensaje queda en la memoria de conversación (mismo mecanismo que el
chat comercial) y se audita como ``ceo_chat.message`` con la intención
resuelta, el proveedor usado y la respuesta.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any

from app.config import settings
from app.models.models import (
    Activity,
    AgentAutonomy,
    AgentDefinition,
    ApprovalRequest,
    AuditLog,
    Campaign,
    Customer,
    InvoiceDraft,
    Lead,
    Opportunity,
    Order,
    PipelineStage,
    Product,
    ScheduledTask,
    SocialMessage,
    SocialTriage,
    User,
)
from app.services import agent_ai
from app.services.autonomy import auto_execute_proposals
from sqlalchemy import func
from sqlalchemy.orm import Session

CEO_AGENT_ID = "ceo_agent"
CEO_ACCOUNT_ID = "ceo"
_STOCK_ALERT_THRESHOLD = 5
_MAX_COLD_LEADS = 10
_LOW_STOCK_LIMIT = 10
_ANSWER_MAX_AUDIT_CHARS = 2_000


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Catálogo de intenciones (resolución determinista)
# ---------------------------------------------------------------------------

# (palabra clave, peso). El peso 3 es para frases inequívocas.
_INTENT_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "greeting": [
        ("hola", 2),
        ("buenos dias", 2),
        ("buenas tardes", 2),
        ("buenas noches", 2),
        ("buenos días", 2),
        ("hey", 1),
    ],
    "sales_summary": [
        ("ventas", 2),
        ("facturacion", 2),
        ("facturado", 2),
        ("vendido", 2),
        ("ingresos", 2),
        ("recaudado", 2),
        ("pedidos", 1),
    ],
    "pipeline_status": [
        ("pipeline", 2),
        ("embudo", 2),
        ("funnel", 2),
        ("oportunidades", 2),
        ("win rate", 2),
        ("winrate", 2),
        ("ticket medio", 2),
        ("etapas", 1),
    ],
    "leads_summary": [
        ("leads", 2),
        ("clientes potenciales", 2),
        ("prospectos", 2),
        ("captacion", 1),
        ("nuevos clientes", 1),
    ],
    "activities_due": [
        ("actividades", 2),
        ("tareas", 2),
        ("recordatorios", 2),
        ("vencen", 2),
        ("vencida", 2),
        ("seguimientos", 1),
        ("pendiente", 1),
    ],
    "approvals_pending": [
        ("aprobaciones", 2),
        ("aprobar", 2),
        ("aprobacion", 2),
        ("pendiente de aprobar", 3),
        ("que hay que aprobar", 3),
    ],
    "social_inbox": [
        ("social", 2),
        ("inbox", 2),
        ("bandeja", 2),
        ("mensajes", 2),
        ("whatsapp", 2),
        ("escucha", 2),
        ("quejas", 2),
        ("urgente", 1),
    ],
    "stock_alert": [
        ("stock", 2),
        ("existencias", 2),
        ("inventario", 2),
        ("agotado", 2),
        ("sin stock", 2),
        ("reposicion", 2),
        ("bajo", 1),
    ],
    "follow_up_cold_leads": [
        ("follow-up", 2),
        ("follow up", 2),
        ("seguimiento", 2),
        ("haz seguimiento", 3),
        ("leads frios", 3),
        ("leads fríos", 3),
        ("sin asignar", 2),
        ("contacta", 2),
        ("contactar", 2),
        ("llamar", 1),
        ("escribir", 1),
    ],
    "automations_status": [
        ("automatizaciones", 3),
        ("automatizacion", 3),
        ("automatización", 3),
        ("tareas programadas", 3),
        ("programadas", 2),
        ("programado", 2),
        ("triggers", 2),
        ("reglas", 1),
        ("sync", 1),
        ("dunning", 1),
    ],
    "agents_status": [
        ("agentes", 3),
        ("agente", 3),
        ("quien gestiona", 3),
        ("quién gestiona", 3),
        ("quien lleva", 2),
        ("quién lleva", 2),
        ("supervision", 2),
        ("supervisión", 2),
    ],
    "automation_toggle": [
        ("pausa", 3),
        ("pausar", 3),
        ("deten", 3),
        ("detén", 3),
        ("activa", 3),
        ("arranca", 3),
        ("reactiva", 3),
        ("automatizacion", 2),
        ("automatización", 2),
        ("tarea programada", 2),
        ("sync", 1),
    ],
    "help": [
        ("que puedes hacer", 3),
        ("qué puedes hacer", 3),
        ("que sabes hacer", 3),
        ("qué sabes hacer", 3),
        ("ayuda", 2),
        ("ayudame", 2),
        ("comandos", 2),
        ("opciones", 1),
    ],
    "lead_create": [
        ("crea un lead", 4),
        ("crear un lead", 4),
        ("crea el lead", 4),
        ("crear lead", 3),
        ("nuevo lead", 3),
        ("añade un lead", 4),
        ("añade el lead", 4),
        ("registra un lead", 3),
        ("alta de lead", 3),
        ("crear un cliente", 3),
    ],
    "opportunity_move": [
        ("mueve la oportunidad", 4),
        ("mover la oportunidad", 4),
        ("mover oportunidad", 4),
        ("cambia de etapa", 4),
        ("cambia la etapa", 4),
        ("pasa la oportunidad", 4),
        ("pasar la oportunidad", 4),
        ("avanza la oportunidad", 4),
        ("mueve a", 2),
        ("mover a", 2),
    ],
    "task_create": [
        ("crea una tarea", 4),
        ("crear una tarea", 4),
        ("crea la tarea", 4),
        ("crear tarea", 4),
        ("asigna una tarea", 4),
        ("asigna la tarea", 4),
        ("asignar una tarea", 4),
        ("recordar que", 2),
        ("recordatorio de", 2),
        ("organiza una reunion", 3),
        ("organiza una llamada", 3),
        ("reunion con", 2),
        ("llamada a", 2),
    ],
    "campaign_launch": [
        ("lanza una campana", 4),
        ("lanzar una campana", 4),
        ("lanza la campana", 4),
        ("lanzar campana", 4),
        ("campana de email", 4),
        ("newsletter", 3),
        ("campana para", 3),
        ("campana a", 2),
        ("email a", 2),
    ],
    # T-082: omnimódulo — informes de gestión y acciones de módulo.
    "weekly_report": [
        ("resumen semanal", 3),
        ("resumen de la semana", 3),
        ("resumen de la empresa", 3),
        ("como esta la empresa", 3),
        ("cómo está la empresa", 3),
        ("estado general", 3),
        ("panorama", 2),
        ("situacion", 2),
        ("situación", 2),
    ],
    "aging_report": [
        ("llevan mas tiempo", 3),
        ("llevan más tiempo", 3),
        ("mas tiempo abiertas", 3),
        ("más tiempo abiertas", 3),
        ("estancadas", 3),
        ("atascadas", 3),
        ("sin moverse", 3),
        ("antiguedad", 2),
        ("antigüedad", 2),
        ("aging", 3),
    ],
    "top_products": [
        ("se venden mas", 3),
        ("se venden más", 3),
        ("los mas vendidos", 3),
        ("los más vendidos", 3),
        ("mas vendido", 3),
        ("más vendido", 3),
        ("top productos", 3),
        ("top ventas", 3),
        ("productos estrella", 3),
        ("que vende mas", 3),
        ("qué vende más", 3),
    ],
    "social_sla": [
        ("fuera de sla", 3),
        ("sla", 3),
        ("mensajes sin atender", 3),
        ("sin atender", 2),
        ("sin responder", 2),
        ("sin contestar", 2),
        ("urgentes", 2),
        ("atender la bandeja", 2),
        ("quejas sin", 2),
    ],
    "lead_assign": [
        ("asigna el lead", 4),
        ("asignar el lead", 4),
        ("asigna ese lead", 4),
        ("asigna este lead", 4),
        ("asigna el cliente", 4),
        ("pasa el lead a", 4),
        ("pasa ese lead a", 4),
        ("asignar un comercial", 3),
        ("asignale", 3),
        ("asígnalo", 3),
    ],
    "opportunity_close": [
        ("cierra la oportunidad", 4),
        ("cerrar la oportunidad", 4),
        ("cierra el trato", 4),
        ("cerrar el trato", 4),
        ("cierra la venta", 4),
        ("marca como ganada", 4),
        ("marca como perdida", 4),
        ("marcar como ganada", 4),
        ("marcar como perdida", 4),
        ("ganada la oportunidad", 4),
        ("perdida la oportunidad", 4),
    ],
    "stock_adjust": [
        ("ajusta el stock", 4),
        ("ajustar el stock", 4),
        ("actualiza el stock", 4),
        ("actualizar el stock", 4),
        ("cambia el stock", 4),
        ("pon el stock", 3),
        ("repon stock", 3),
        ("reponer stock", 3),
        ("stock de", 2),
    ],
    "product_price_update": [
        ("actualiza el precio", 4),
        ("actualizar el precio", 4),
        ("cambia el precio", 4),
        ("cambiar el precio", 4),
        ("sube el precio", 4),
        ("baja el precio", 4),
        ("pon el precio", 3),
        ("nuevo precio", 3),
        ("precio de", 2),
        ("precio a", 2),
    ],
    "ghl_send_message": [
        ("envia un sms", 4),
        ("enviar un sms", 4),
        ("enviale un sms", 4),
        ("manda un sms", 4),
        ("mandale un sms", 4),
        ("envia un email", 4),
        ("enviar un email", 4),
        ("enviale un email", 4),
        ("manda un email", 4),
        ("envia un correo", 4),
        ("enviar un correo", 4),
        ("enviale un correo", 4),
        ("manda un correo", 4),
        ("enviale un whatsapp", 4),
        ("envia un whatsapp", 4),
        ("enviar un whatsapp", 4),
        ("manda un whatsapp", 4),
        ("escribele un mensaje", 3),
        ("escribele un sms", 3),
        ("contacta por sms", 3),
        ("contactar por sms", 3),
        ("contacta por email", 3),
        ("contactar por email", 3),
        ("contacta por correo", 3),
        ("contactar por correo", 3),
        ("sms", 1),
        ("whatsapp", 1),
        ("correo", 1),
    ],
    "ghl_create_contact": [
        ("sincroniza con ghl", 4),
        ("sincronizar con ghl", 4),
        ("crea un contacto en ghl", 4),
        ("crear un contacto en ghl", 4),
        ("crea un contacto en gohighlevel", 4),
        ("dalo de alta en ghl", 4),
        ("dar de alta en ghl", 4),
        ("anade a ghl", 4),
        ("añade a ghl", 4),
        ("anade el lead a ghl", 4),
        ("en ghl", 2),
        ("con ghl", 2),
        ("a ghl", 2),
        ("gohighlevel", 2),
        ("leadconnector", 3),
        ("ghl", 1),
    ],
}

_ACTION_VERBS = ("haz", "haga", "crea", "prepare", "prepara", "envia", "envía", "manda", "escribe", "organiza", "contacta", "llama", "pausa", "deten", "detén", "activa", "arranca", "reactiva", "asigna", "asignar", "asignale", "asígnalo", "cierra", "cerrar", "marca", "marcar", "ajusta", "ajustar", "actualiza", "actualizar", "sube", "baja", "repon", "reponer", "cambia", "cambiar", "pon", "sincroniza", "sincronizar", "anade", "añade")

# Orden de prioridad para desempatar puntuaciones iguales: las intenciones
# de lectura se prefieren ante una consulta ambigua; las de acción requieren
# verbo + señal para ganar.
_INTENT_PRIORITY = [
    "greeting",
    "help",
    "sales_summary",
    "pipeline_status",
    "leads_summary",
    "activities_due",
    "approvals_pending",
    "social_inbox",
    "stock_alert",
    "automations_status",
    "agents_status",
    "weekly_report",
    "aging_report",
    "top_products",
    "social_sla",
    "automation_toggle",
    "follow_up_cold_leads",
    "lead_create",
    "opportunity_move",
    "task_create",
    "campaign_launch",
    "lead_assign",
    "opportunity_close",
    "stock_adjust",
    "product_price_update",
    "ghl_send_message",
    "ghl_create_contact",
]

_INTENT_LABEL = {
    "greeting": "saludo",
    "sales_summary": "resumen de ventas",
    "pipeline_status": "estado del pipeline",
    "leads_summary": "resumen de leads",
    "activities_due": "actividades pendientes",
    "approvals_pending": "aprobaciones pendientes",
    "social_inbox": "bandeja social",
    "stock_alert": "alerta de stock",
    "follow_up_cold_leads": "follow-up de leads fríos",
    "automations_status": "estado de las automatizaciones",
    "agents_status": "estado de los agentes",
    "automation_toggle": "cambio de estado de automatización",
    "lead_create": "crear un lead",
    "opportunity_move": "mover una oportunidad de etapa",
    "task_create": "crear una tarea",
    "campaign_launch": "lanzar una campaña",
    "weekly_report": "resumen de la empresa",
    "aging_report": "antigüedad del pipeline",
    "top_products": "productos más vendidos",
    "social_sla": "mensajes sociales fuera de SLA",
    "lead_assign": "asignar un lead a un comercial",
    "opportunity_close": "cerrar una oportunidad",
    "stock_adjust": "ajustar stock de un producto",
    "product_price_update": "actualizar el precio de un producto",
    "ghl_send_message": "enviar un SMS/email a un lead",
    "ghl_create_contact": "crear un contacto en GHL",
    "help": "ayuda",
    "unknown": "sin resolver",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text.lower()).strip()


def resolve_intent(message: str) -> str:
    """Resuelve la intención del mensaje de forma determinista.

    Normaliza (minúsculas, sin acentos) y puntúa cada intención con su
    catálogo de palabras clave. Las frases inequívocas (peso 3) o dos
    señales bastan; un verbo de acción inclina la balanza hacia las
    intenciones de acción. Sin señales → ``unknown`` (la respuesta pide
    reformular y muestra el catálogo).
    """

    norm = _normalize(message)
    if not norm:
        return "unknown"

    scores: dict[str, int] = {}
    has_action_verb = any(f" {verb} " in f" {norm} " or norm.startswith(verb) for verb in _ACTION_VERBS)
    for intent, keywords in _INTENT_KEYWORDS.items():
        score = 0
        for keyword, weight in keywords:
            if keyword in norm:
                score += weight
        if (
            intent
            in (
                "follow_up_cold_leads",
                "automation_toggle",
                "lead_create",
                "opportunity_move",
                "task_create",
                "campaign_launch",
                "lead_assign",
                "opportunity_close",
                "stock_adjust",
                "product_price_update",
                "ghl_send_message",
                "ghl_create_contact",
            )
            and has_action_verb
            and score > 0
        ):
            score += 1
        scores[intent] = score

    best_score = max(scores.values())
    if best_score <= 0:
        return "unknown"
    candidates = [i for i in _INTENT_PRIORITY if scores[i] == best_score]
    return candidates[0] if candidates else "unknown"


# ---------------------------------------------------------------------------
# Recopilación de datos verificados (solo lectura)
# ---------------------------------------------------------------------------


def _gather_sales(db: Session) -> dict[str, Any]:
    opportunities = db.query(Opportunity).all()
    values = [float(opp.monetary_value or 0) for opp in opportunities]
    open_opps = [opp for opp in opportunities if opp.status == "open"]
    won = [opp for opp in opportunities if opp.stage == "won" or opp.status == "won"]
    lost = [opp for opp in opportunities if opp.stage == "lost" or opp.status == "lost"]
    decided = len(won) + len(lost)
    win_rate = round(100 * len(won) / decided, 1) if decided else 0.0
    avg = round(sum(values) / len(values), 2) if values else 0.0
    orders = int(db.query(func.count(Order.id)).scalar() or 0)
    return {
        "open_count": len(open_opps),
        "open_value": round(sum(float(o.monetary_value or 0) for o in open_opps), 2),
        "won_count": len(won),
        "won_value": round(sum(float(o.monetary_value or 0) for o in won), 2),
        "lost_count": len(lost),
        "win_rate": win_rate,
        "ticket_medio": avg,
        "orders_count": orders,
        "total_opportunities": len(opportunities),
    }


def _gather_pipeline(db: Session) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    now = _utcnow()
    for opp in db.query(Opportunity).all():
        bucket = stages.setdefault(
            opp.stage,
            {"stage": opp.stage, "count": 0, "value": 0.0, "aging_max_days": 0},
        )
        bucket["count"] += 1
        bucket["value"] = round(bucket["value"] + float(opp.monetary_value or 0), 2)
        if opp.stage_changed_at:
            days = max(0, (now - opp.stage_changed_at).total_seconds() / 86_400)
            bucket["aging_max_days"] = max(bucket["aging_max_days"], round(days, 1))
    ordered = sorted(stages.values(), key=lambda s: -s["value"])
    open_total = sum(s["value"] for s in ordered)
    return {
        "stages": ordered,
        "open_total": round(open_total, 2),
        "stage_count": len(ordered),
    }


def _gather_leads(db: Session) -> dict[str, Any]:
    rows = db.query(Lead).all()
    by_status: dict[str, int] = {}
    for lead in rows:
        by_status[lead.status or "unknown"] = by_status.get(lead.status or "unknown", 0) + 1
    unassigned = sum(1 for lead in rows if not lead.assigned_to)
    recent = sorted(
        (lead for lead in rows if lead.created_at),
        key=lambda lead: lead.created_at,
        reverse=True,
    )[:5]
    return {
        "total": len(rows),
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "unassigned": unassigned,
        "recent": [
            {
                "name": lead.first_name,
                "email": lead.email,
                "status": lead.status,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }
            for lead in recent
        ],
    }


def _gather_activities(db: Session) -> dict[str, Any]:
    now = _utcnow()
    rows = db.query(Activity).filter(Activity.status == "pending").all()
    overdue = [a for a in rows if a.due_at and a.due_at < now]
    due_today = [
        a
        for a in rows
        if a.due_at and a.due_at.date() == now.date() and a.due_at >= now
    ]
    upcoming = sorted(
        (a for a in rows if a.due_at and a.due_at >= now),
        key=lambda a: a.due_at,
    )[:5]
    return {
        "pending": len(rows),
        "overdue": len(overdue),
        "due_today": len(due_today),
        "next": [
            {
                "title": a.title,
                "kind": a.kind,
                "due_at": a.due_at.isoformat() if a.due_at else None,
            }
            for a in upcoming
        ],
    }


def _gather_approvals(db: Session) -> dict[str, Any]:
    rows = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.created_at.asc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "action_type": row.action_type,
            "target_key": row.target_key,
            "requested_by": row.requested_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            # El payload NO se expone al LLM: solo alimenta la traducción a
            # lenguaje llano de la clave objetivo (nombres ya guardados).
            "payload": row.payload,
            "target_label": None,
        }
        item["target_label"] = _humanize_target(db, item)
        items.append(item)
    return {
        "pending": len(rows),
        "items": items,
    }


def _gather_social(db: Session) -> dict[str, Any]:
    now = _utcnow()
    pending = db.query(SocialMessage).filter(SocialMessage.status != "dismissed").count()
    urgent = (
        db.query(func.count(SocialMessage.id))
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.status != "dismissed",
            SocialTriage.intent.in_(("queja", "lead")),
            SocialTriage.urgency >= 40,
        )
        .scalar()
        or 0
    )
    return {
        "pending": int(pending),
        "urgent": int(urgent),
        "now": now.isoformat(),
    }


def _gather_stock(db: Session) -> dict[str, Any]:
    rows = (
        db.query(Product)
        .filter(Product.stock_quantity <= _STOCK_ALERT_THRESHOLD)
        .order_by(Product.stock_quantity.asc())
        .limit(_LOW_STOCK_LIMIT)
        .all()
    )
    return {
        "threshold": _STOCK_ALERT_THRESHOLD,
        "low_count": len(rows),
        "items": [
            {
                "sku": row.sku,
                "name": row.name,
                "stock": row.stock_quantity,
                "reserved": row.reserved_stock,
            }
            for row in rows
        ],
    }


def _gather_automations(db: Session) -> dict[str, Any]:
    """Automatizaciones programadas: tareas con su estado y próxima ejecución."""

    rows = (
        db.query(ScheduledTask)
        .order_by(ScheduledTask.name.asc())
        .all()
    )
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    return {
        "total": len(rows),
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "task_type": row.task_type,
                "status": row.status,
                "interval_seconds": row.interval_seconds,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            }
            for row in rows
        ],
    }


def _gather_agents(db: Session) -> dict[str, Any]:
    """Agentes por módulo: modo de autonomía y propuestas pendientes."""

    from app.main import AGENT_REGISTRY

    autonomy_rows = db.query(AgentAutonomy).all()
    mode_by_agent: dict[str, str] = {
        row.agent_id: row.mode for row in autonomy_rows
    }
    pending_by_agent: dict[str, int] = {}
    for approval in db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "pending"
    ):
        key = str(approval.requested_by or "")
        pending_by_agent[key] = pending_by_agent.get(key, 0) + 1
    persisted = {
        record.id: record for record in db.query(AgentDefinition).all()
    }
    items: list[dict[str, Any]] = []
    for agent_id, config in AGENT_REGISTRY.items():
        record = persisted.get(agent_id)
        items.append(
            {
                "agent_id": agent_id,
                "name": config.get("name", agent_id),
                "module_label": config.get("module_label"),
                "autonomy_level": config.get("autonomy_level"),
                "status": (record.status if record else config.get("status")) or "active",
                "autonomy_mode": mode_by_agent.get(agent_id, "manual"),
                "pending_proposals": pending_by_agent.get(agent_id, 0),
            }
        )
    return {
        "total": len(items),
        "autonomous": sum(1 for i in items if i["autonomy_mode"] == "autonomous"),
        "items": items,
    }


# ---------------------------------------------------------------------------
# T-082: informes de gestión (lectura) — resumen semanal, aging del pipeline,
# top de ventas y mensajes sociales fuera de SLA.
# ---------------------------------------------------------------------------


def _gather_weekly(db: Session) -> dict[str, Any]:
    """Resumen panorámico: compone los gatherers de todos los módulos."""

    return {
        "sales": _gather_sales(db),
        "pipeline": _gather_pipeline(db),
        "leads": _gather_leads(db),
        "activities": _gather_activities(db),
        "approvals": _gather_approvals(db),
        "social": _gather_social(db),
        "stock": _gather_stock(db),
    }


def _gather_aging(db: Session) -> dict[str, Any]:
    """Pipeline por antigüedad: abiertas ordenadas por días en su etapa."""

    now = _utcnow()
    rows: list[dict[str, Any]] = []
    for opp in db.query(Opportunity).filter(Opportunity.status == "open").all():
        days = 0
        if opp.stage_changed_at:
            days = max(0, int((now - opp.stage_changed_at).total_seconds() / 86_400))
        rows.append(
            {
                "id": opp.id,
                "name": opp.name,
                "stage": opp.stage,
                "value": float(opp.monetary_value or 0),
                "days_in_stage": days,
                "stage_changed_at": (
                    opp.stage_changed_at.isoformat() if opp.stage_changed_at else None
                ),
            }
        )
    rows.sort(key=lambda r: (-r["days_in_stage"], -r["value"]))
    return {
        "open_count": len(rows),
        "stale_count": sum(1 for r in rows if r["days_in_stage"] >= 7),
        "items": rows[:10],
    }


def _gather_top_products(db: Session) -> dict[str, Any]:
    """Productos más vendidos: agrega las líneas de pedidos confirmados."""

    qty_by_id: dict[str, int] = {}
    price_hint: dict[str, float] = {}
    for order in db.query(Order).filter(Order.status == "confirmed").all():
        for item in order.items or []:
            product_id = str(item.get("product_id") or "")
            if not product_id:
                continue
            qty_by_id[product_id] = qty_by_id.get(product_id, 0) + int(
                item.get("qty") or 0
            )
            unit = item.get("unit_price")
            if isinstance(unit, (int, float)) and float(unit) > 0:
                price_hint[product_id] = float(unit)
    products = {
        p.id: p
        for p in db.query(Product).filter(Product.id.in_(list(qty_by_id))).all()
    }
    ranked = sorted(qty_by_id.items(), key=lambda kv: -kv[1])[:10]
    items: list[dict[str, Any]] = []
    for product_id, qty in ranked:
        product = products.get(product_id)
        unit = price_hint.get(product_id) or float(
            product.base_price if product else 0
        )
        items.append(
            {
                "product_id": product_id,
                "name": product.name if product else f"Producto {product_id[:8]}",
                "sku": product.sku if product else None,
                "qty": qty,
                "revenue": round(qty * unit, 2),
            }
        )
    return {"top": items, "total_products": len(qty_by_id)}


def _gather_social_sla(db: Session) -> dict[str, Any]:
    """Mensajes urgentes (queja/lead) triados que siguen sin atender."""

    now = _utcnow()
    rows = (
        db.query(SocialMessage, SocialTriage)
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.status == "triaged",
            SocialTriage.intent.in_(("queja", "lead")),
            SocialTriage.urgency >= 40,
        )
        .order_by(SocialMessage.created_at.asc())
        .limit(10)
        .all()
    )
    items: list[dict[str, Any]] = []
    for message, triage in rows:
        age_hours = None
        if message.created_at:
            age_hours = max(0, int((now - message.created_at).total_seconds() / 3600))
        items.append(
            {
                "message_id": message.id,
                "sender": message.sender_name or message.sender_handle or "desconocido",
                "body_preview": (message.body or "")[:80],
                "intent": triage.intent,
                "urgency": triage.urgency,
                "age_hours": age_hours,
            }
        )
    return {"items": items, "count": len(items)}


_GATHERERS = {
    "sales_summary": _gather_sales,
    "pipeline_status": _gather_pipeline,
    "leads_summary": _gather_leads,
    "activities_due": _gather_activities,
    "approvals_pending": _gather_approvals,
    "social_inbox": _gather_social,
    "stock_alert": _gather_stock,
    "automations_status": _gather_automations,
    "agents_status": _gather_agents,
    "weekly_report": _gather_weekly,
    "aging_report": _gather_aging,
    "top_products": _gather_top_products,
    "social_sla": _gather_social_sla,
}


def _facts_block(intent: str, data: dict[str, Any]) -> str:
    """Bloque de datos verificados para el LLM (y para las plantillas)."""

    lines: list[str] = []
    if intent == "sales_summary":
        lines.append(
            f"Ventas: {data['open_count']} oportunidades abiertas por {data['open_value']} {settings.CURRENCY}; "
            f"{data['won_count']} ganadas por {data['won_value']} {settings.CURRENCY}; {data['lost_count']} perdidas; "
            f"win-rate {data['win_rate']}%; ticket medio {data['ticket_medio']} {settings.CURRENCY}; "
            f"{data['orders_count']} pedidos."
        )
    elif intent == "pipeline_status":
        for stage in data["stages"]:
            lines.append(
                f"Etapa '{stage['stage']}': {stage['count']} oportunidades, {stage['value']} {settings.CURRENCY}, "
                f"aging máx {stage['aging_max_days']} días"
            )
        lines.append(f"Total abierto: {data['open_total']} {settings.CURRENCY} en {data['stage_count']} etapas")
    elif intent == "leads_summary":
        by_status = ", ".join(f"{k}={v}" for k, v in data["by_status"].items())
        lines.append(f"Leads totales: {data['total']} ({by_status}); sin asignar: {data['unassigned']}")
        for lead in data["recent"]:
            lines.append(
                f"Lead reciente: {lead['name']} <{lead['email']}> estado={lead['status']} alta={lead['created_at']}"
            )
    elif intent == "activities_due":
        lines.append(
            f"Actividades pendientes: {data['pending']} (vencidas {data['overdue']}, para hoy {data['due_today']})"
        )
        for item in data["next"]:
            lines.append(f"Próxima: {item['title']} ({item['kind']}) vence {item['due_at']}")
    elif intent == "approvals_pending":
        by_type: dict[str, int] = {}
        for item in data["items"]:
            label = _plain_proposal_label(item["action_type"])
            by_type[label] = by_type.get(label, 0) + 1
        by_type_s = ", ".join(
            f"{k}: {v}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"Aprobaciones pendientes: {data['pending']} (por tipo: {by_type_s})")
        # Solo ejemplos y en lenguaje llano: el LLM tiende a volcar el bloque
        # entero (29 líneas técnicas) y eso no es una respuesta de chat
        # (observado 2026-08-19). Las claves objetivo (UUID, «inv-…») se
        # traducen al nombre humano del lead/cliente/producto…
        for item in data["items"][:5]:
            target = item.get("target_label") or item["target_key"]
            lines.append(
                f"- Ejemplo: {_plain_proposal_label(item['action_type'])} sobre "
                f"'{target}' pedida por {_plain_requester(item['requested_by'])}"
            )
    elif intent == "social_inbox":
        lines.append(
            f"Bandeja social: {data['pending']} mensajes sin descartar, {data['urgent']} urgentes"
        )
    elif intent == "stock_alert":
        lines.append(
            f"Productos con stock <= {data['threshold']}: {data['low_count']}"
        )
        for item in data["items"]:
            lines.append(f"- SKU {item['sku']} '{item['name']}': {item['stock']} uds (reservado {item['reserved']})")
    elif intent == "automations_status":
        lines.append(
            f"Automatizaciones: {data['total']} ({', '.join(f'{k}={v}' for k, v in data['by_status'].items())})"
        )
        for item in data["items"]:
            lines.append(
                f"- {item['name']} ({item['task_type']}): {item['status']}, próxima {item['next_run_at']}"
            )
    elif intent == "agents_status":
        lines.append(
            f"Agentes: {data['total']} ({data['autonomous']} en modo autónomo)"
        )
        for item in data["items"]:
            lines.append(
                f"- {item['name']} ({item['module_label']}): {item['status']}, autonomía {item['autonomy_mode']}, {item['pending_proposals']} propuestas pendientes"
            )
    elif intent == "weekly_report":
        s = data["sales"]
        p = data["pipeline"]
        leads_data = data["leads"]
        a = data["activities"]
        ap = data["approvals"]
        so = data["social"]
        st = data["stock"]
        lines.append(
            f"Ventas: {s['won_count']} ganadas por {s['won_value']} {settings.CURRENCY}, "
            f"{s['orders_count']} pedidos, pipeline {p['open_total']} {settings.CURRENCY} "
            f"en {p['stage_count']} etapas"
        )
        lines.append(
            f"Leads: {leads_data['total']} ({leads_data['unassigned']} sin asignar); "
            f"actividades pendientes {a['pending']} (vencidas {a['overdue']}); "
            f"aprobaciones {ap['pending']}"
        )
        lines.append(
            f"Social: {so['pending']} mensajes ({so['urgent']} urgentes); "
            f"stock bajo: {st['low_count']} productos"
        )
    elif intent == "aging_report":
        lines.append(
            f"Oportunidades abiertas: {data['open_count']} "
            f"({data['stale_count']} sin movimiento >= 7 días)"
        )
        for r in data["items"]:
            lines.append(
                f"- {r['name']} (etapa {r['stage']}): {r['days_in_stage']} días, "
                f"{r['value']} {settings.CURRENCY}"
            )
    elif intent == "top_products":
        lines.append(f"Productos con ventas: {data['total_products']}")
        for r in data["top"]:
            lines.append(
                f"- {r['name']} (SKU {r['sku'] or '-'}): {r['qty']} uds, "
                f"{r['revenue']} {settings.CURRENCY}"
            )
    elif intent == "social_sla":
        lines.append(f"Mensajes urgentes sin atender: {data['count']}")
        for r in data["items"]:
            lines.append(
                f"- {r['sender']} ({r['intent']}, urgencia {r['urgency']}): "
                f"{r['body_preview']} — {r['age_hours']}h sin respuesta"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Traducción a lenguaje llano para el chat del dueño: los tipos de acción de
# las propuestas (``agent_proposal:ceo_follow_up``, ``issue_invoice``…) y los
# agentes que las piden (``ceo_agent``, ``sales_agent``…) se muestran como
# frases humanas en las respuestas del chat y en las plantillas deterministas.
# ---------------------------------------------------------------------------

_PROPOSAL_PLAIN_LABELS: dict[str, str] = {
    "agent_proposal:ceo_follow_up": "seguimiento a un lead frío",
    "agent_proposal:create_follow_up": "crear un seguimiento",
    "agent_proposal:ceo_create_lead": "crear un lead",
    "agent_proposal:ceo_move_opportunity": "mover una oportunidad de etapa",
    "agent_proposal:ceo_create_task": "crear una tarea",
    "agent_proposal:ceo_launch_campaign": "lanzar una campaña",
    "agent_proposal:ceo_assign_lead": "asignar un lead a un comercial",
    "agent_proposal:ceo_close_opportunity": "cerrar una oportunidad",
    "agent_proposal:ceo_update_price": "actualizar el precio de un producto",
    "agent_proposal:ceo_adjust_stock": "ajustar el stock de un producto",
    "agent_proposal:automation_toggle": "activar o pausar una automatización",
    "agent_proposal:dismiss_message": "descartar un mensaje social",
    "agent_proposal:ghl_send_message": "enviar un mensaje (SMS o email)",
    "agent_proposal:ghl_create_contact": "crear un contacto",
    "issue_invoice": "emitir una factura",
    "create_contact": "crear un contacto",
}

_AGENT_PLAIN_LABELS: dict[str, str] = {
    "ceo_agent": "el asistente de dirección",
    "sales_agent": "el agente comercial",
    "commerce_agent": "el agente comercial de la tienda",
    "finance_agent": "el agente financiero",
    "crm_agent": "el agente de clientes (CRM)",
    "social_agent": "el agente de escucha social",
    "marketing_agent": "el agente de email y campañas",
    "content_agent": "el agente de contenido y SEO",
    "catalog_agent": "el agente de catálogo",
    "rag_agent": "el agente documental",
}


def _plain_proposal_label(action_type: str) -> str:
    """Traduce un tipo de acción de propuesta a lenguaje llano para el chat.

    Los nombres técnicos (``agent_proposal:ceo_follow_up``, ``issue_invoice``)
    no son de chat; se mapean a frases humanas. Los desconocidos se dejan
    intactos (nunca se inventa una traducción).
    """

    return _PROPOSAL_PLAIN_LABELS.get(action_type, action_type)


def _plain_requester(agent_id: str) -> str:
    """Nombre humano del agente que pide una propuesta (``ceo_agent`` → «el asistente de dirección»)."""

    return _AGENT_PLAIN_LABELS.get(agent_id, agent_id)


def _target_kind_for_action(action_type: str) -> str:
    """Qué módulo del portal contiene la ficha, derivado del tipo de acción.

    El ``kind`` no depende de si el registro sigue existiendo: una factura
    cuyo borrador se borró sigue enlazando a Ventas. Los tipos desconocidos
    devuelven ``unknown`` (el portal los muestra sin enlace).
    """

    if action_type in {
        "agent_proposal:ceo_follow_up",
        "agent_proposal:create_follow_up",
        "agent_proposal:ceo_assign_lead",
        "agent_proposal:ceo_create_lead",
    }:
        return "lead"
    if action_type in {
        "agent_proposal:ceo_move_opportunity",
        "agent_proposal:ceo_close_opportunity",
    }:
        return "opportunity"
    if action_type in {
        "agent_proposal:ceo_update_price",
        "agent_proposal:ceo_adjust_stock",
    }:
        return "product"
    if action_type == "agent_proposal:automation_toggle":
        return "automation"
    if action_type == "agent_proposal:dismiss_message":
        return "social_message"
    if action_type == "agent_proposal:ceo_create_task":
        return "task"
    if action_type in {
        "agent_proposal:ghl_send_message",
        "agent_proposal:ghl_create_contact",
        "create_contact",
    }:
        return "contact"
    if action_type == "issue_invoice":
        return "invoice"
    if action_type == "agent_proposal:ceo_launch_campaign":
        return "campaign"
    return "unknown"


def _resolve_target(db: Session, item: dict[str, Any]) -> tuple[str, str | None, str]:
    """Resuelve el objetivo de una propuesta a (tipo, id enfocable, label humano).

    Las claves objetivo son técnicamente identificadores: UUID del lead, id
    de factura (``inv-…``), email, huella del contenido… El dueño no los
    reconoce; se resuelven por modelo según el tipo de acción. Devuelve:

    - ``tipo``: ``lead`` | ``opportunity`` | ``invoice`` | ``product`` |
      ``automation`` | ``social_message`` | ``task`` | ``contact`` |
      ``campaign`` | ``unknown`` — qué módulo del portal contiene la ficha.
    - ``id enfocable``: id del registro al que el portal puede navegar para
      mostrar la ficha (para una oportunidad, el id del lead que la contiene;
      ``None`` cuando no hay un registro único que enfocar).
    - ``label``: el nombre humano (o la clave tal cual si no se resuelve:
      nunca se inventa ni se rompe).
    """

    action_type = item["action_type"]
    target_key = item["target_key"]
    payload = item.get("payload") or {}
    kind = _target_kind_for_action(action_type)

    def _lead_label(lead_id: str) -> str | None:
        if not lead_id or lead_id == "general":
            return None
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead is None:
            return None
        return (lead.first_name or "").strip() or (lead.email or "").strip() or None

    if action_type in {
        "agent_proposal:ceo_follow_up",
        "agent_proposal:create_follow_up",
        "agent_proposal:ceo_assign_lead",
    }:
        label = _lead_label(target_key)
        if label:
            return kind, target_key, label

    if action_type in {
        "agent_proposal:ceo_move_opportunity",
        "agent_proposal:ceo_close_opportunity",
    }:
        opp = db.query(Opportunity).filter(Opportunity.id == target_key).first()
        if opp is not None and (opp.name or "").strip():
            # La ficha del lead contiene sus oportunidades. getattr: los
            # dobles de test pueden omitir lead_id sin romper la resolución.
            return kind, getattr(opp, "lead_id", None), opp.name.strip()

    if action_type in {
        "agent_proposal:ceo_update_price",
        "agent_proposal:ceo_adjust_stock",
    }:
        product = db.query(Product).filter(Product.id == target_key).first()
        if product is not None:
            return kind, target_key, f"{product.name.strip()} (SKU {product.sku})"

    if action_type == "agent_proposal:automation_toggle":
        task = db.query(ScheduledTask).filter(ScheduledTask.id == target_key).first()
        if task is not None and (task.name or "").strip():
            return kind, target_key, task.name.strip()

    if action_type == "agent_proposal:dismiss_message":
        msg = db.query(SocialMessage).filter(SocialMessage.id == target_key).first()
        if msg is not None:
            sender = (msg.sender_name or msg.sender_handle or "").strip()
            if sender:
                return kind, target_key, sender

    if action_type == "agent_proposal:ceo_create_task":
        # target_key = "{lead_id}:{título}" (lead_id puede ser «general»).
        lead_part, sep, title = target_key.partition(":")
        if sep:
            lead_label = _lead_label(lead_part)
            if lead_label:
                return kind, lead_part, f"{title} (lead {lead_label})"
            return kind, lead_part, title or target_key
        return kind, lead_part, target_key

    if action_type == "agent_proposal:ghl_send_message":
        # target_key = "{lead_id}:{canal}:{huella}" — el lead manda.
        lead_id = target_key.split(":", 1)[0]
        label = _lead_label(lead_id)
        if label:
            return kind, lead_id, label

    if action_type == "issue_invoice":
        inv = db.query(InvoiceDraft).filter(InvoiceDraft.id == target_key).first()
        if inv is not None:
            client = ""
            customer = (
                db.query(Customer).filter(Customer.id == inv.customer_id).first()
            )
            if customer is not None and (customer.name or "").strip():
                client = customer.name.strip()
            if client:
                return kind, target_key, f"{client} ({inv.invoice_number})"
            return kind, target_key, inv.invoice_number

    # Tipos cuyo target ya es humano (email, nombre de campaña…) o tipos
    # desconocidos: los nombres ya guardados en el payload como segundo
    # recurso; si no hay, la clave tal cual. El kind se conserva del tipo de
    # acción aunque el registro ya no exista.
    for field in ("lead_name", "name", "title", "first_name", "sender", "invoice_number"):
        value = payload.get(field)
        if value and str(value).strip():
            return kind, None, str(value).strip()
    return kind, None, target_key


def _humanize_target(db: Session, item: dict[str, Any]) -> str:
    """Traduce la clave objetivo de una propuesta al nombre humano del chat.

    Las claves objetivo son técnicamente identificadores: UUID del lead, id
    de factura (``inv-…``), email, huella del contenido… El dueño no los
    reconoce; se resuelven por modelo según el tipo de acción (el nombre del
    lead, de la oportunidad, del producto, de la automatización o el cliente
    de la factura). Si el target ya no existe o el tipo es desconocido, se
    devuelve la clave tal cual (nunca se inventa ni se rompe).
    """

    return _resolve_target(db, item)[2]


# Artefactos de markdown que los LLM locales (p. ej. Qwen3 14B) emiten pese
# a que el prompt pida texto plano. El chat del portal renderiza en un ``<p>``
# plano, así que sin un filtro determinista la respuesta muestra ``**negrita**``
# y guiones crudos: el prompt solo no basta con modelos locales (observado en
# la comparativa 2026-08-19, docs/LLM_MODEL_COMPARISON.md).
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__)(.+?)\1")
_MD_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_MD_SINGLE_EMPHASIS_RE = re.compile(r"(?<![\w*])(\*|_)([^*_\n]+)\1(?![\w*])")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_BULLET_RE = re.compile(r"^\s*(?:[-*•·])\s+")


def _plain_chat_text(text: str) -> str:
    """Convierte una respuesta del LLM/plantilla a texto plano de chat.

    Quita los artefactos de markdown (negritas, cursivas, código, encabezados
    y viñetas) que los modelos locales emiten pese al prompt. No toca los
    separadores que ya van dentro de una frase (``·`` entre elementos), ni los
    números con puntos, ni los guiones bajos de identificadores (``win_rate``).
    """

    cleaned = _MD_EMPHASIS_RE.sub(r"\2", text or "")
    cleaned = _MD_BACKTICK_RE.sub(r"\1", cleaned)
    cleaned = _MD_SINGLE_EMPHASIS_RE.sub(r"\2", cleaned)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = _MD_HEADING_RE.sub("", raw).rstrip()
        lines.append(_MD_BULLET_RE.sub("", line))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plantillas deterministas (fallback honesto sin LLM)
# ---------------------------------------------------------------------------


def _template_answer(intent: str, data: dict[str, Any]) -> str:
    if intent == "greeting":
        return (
            "Hola, soy tu asistente. Desde aquí controlas toda la empresa: te "
            "informo de ventas, pipeline, leads, actividades, aprobaciones, "
            "bandeja social, stock, agentes y automatizaciones, y preparo las "
            "acciones (follow-ups, pausar o activar automatizaciones) para que "
            "solo las confirmes. ¿Qué necesitas?"
        )
    if intent == "sales_summary":
        return (
            f"Ventas ahora mismo: {data['open_count']} oportunidades abiertas por "
            f"{data['open_value']} {settings.CURRENCY} y {data['won_count']} ganadas por "
            f"{data['won_value']} {settings.CURRENCY} "
            f"(win-rate {data['win_rate']}%, ticket medio {data['ticket_medio']} {settings.CURRENCY}). "
            f"Hay {data['orders_count']} pedidos registrados."
        )
    if intent == "pipeline_status":
        if not data["stages"]:
            return "El pipeline está vacío: todavía no hay oportunidades."
        lines = []
        for stage in data["stages"]:
            lines.append(
                f"· {stage['stage']}: {stage['count']} oportunidades por {stage['value']} {settings.CURRENCY} "
                f"(aging máx {stage['aging_max_days']} días)"
            )
        return (
            f"El pipeline tiene {data['stage_count']} etapas con {data['open_total']} {settings.CURRENCY} abiertos:\n"
            + "\n".join(lines)
        )
    if intent == "leads_summary":
        by_status = ", ".join(f"{k}: {v}" for k, v in data["by_status"].items())
        return (
            f"Hay {data['total']} leads en total ({by_status}) y {data['unassigned']} "
            "sin comercial asignado. Si quieres, te propongo follow-ups para los "
            "leads fríos (quedarían pendientes de tu aprobación)."
        )
    if intent == "activities_due":
        if data["pending"] == 0:
            return "No tienes actividades pendientes. Buen momento para revisar el pipeline."
        text = (
            f"Tienes {data['pending']} actividades pendientes: {data['overdue']} vencidas "
            f"y {data['due_today']} para hoy."
        )
        if data["next"]:
            items = "\n".join(
                f"· {item['title']} ({item['kind']}) — vence {item['due_at']}"
                for item in data["next"][:5]
            )
            text += "\nPróximas:\n" + items
        return text
    if intent == "approvals_pending":
        if data["pending"] == 0:
            return "No hay aprobaciones pendientes: todo está al día."
        lines = [f"Hay {data['pending']} aprobaciones pendientes de tu decisión:"]
        for item in data["items"][:8]:
            target = item.get("target_label") or item["target_key"]
            lines.append(
                f"· {_plain_proposal_label(item['action_type'])} sobre "
                f"«{target[:60]}» (propuesta por {_plain_requester(item['requested_by'])})"
            )
        return "\n".join(lines)
    if intent == "social_inbox":
        return (
            f"En la bandeja social hay {data['pending']} mensajes sin atender, "
            f"{data['urgent']} de ellos urgentes (quejas o leads con urgencia alta)."
        )
    if intent == "stock_alert":
        if data["low_count"] == 0:
            return f"No hay productos con stock por debajo del umbral ({data['threshold']} uds)."
        lines = [
            f"Hay {data['low_count']} productos bajo el umbral de {data['threshold']} uds:"
        ]
        for item in data["items"][:8]:
            lines.append(
                f"· {item['sku']} — {item['name']}: {item['stock']} uds (reservadas {item['reserved']})"
            )
        return "\n".join(lines)
    if intent == "automations_status":
        if data["total"] == 0:
            return (
                "Todavía no hay automatizaciones programadas. Puedes crearlas desde "
                "la sección Automatizaciones (sync de PrestaShop, alerta de stock "
                "bajo o abandono de carrito) o pedírmelo y te guío."
            )
        by_status = ", ".join(f"{k}: {v}" for k, v in data["by_status"].items())
        lines = [
            f"Tienes {data['total']} automatizaciones ({by_status}):"
        ]
        for item in data["items"][:10]:
            lines.append(
                f"· {item['name']} ({item['task_type']}) — {item['status']}"
                + (f", próxima ejecución {item['next_run_at']}" if item["next_run_at"] else "")
            )
        return "\n".join(lines)
    if intent == "agents_status":
        lines = [
            f"Tienes {data['total']} agentes de IA ({data['autonomous']} en modo autónomo):"
        ]
        for item in data["items"][:12]:
            lines.append(
                f"· {item['name']} ({item['module_label']}) — {item['status']}, "
                f"autonomía {item['autonomy_mode']}, {item['pending_proposals']} propuesta(s) pendiente(s)"
            )
        return "\n".join(lines)
    if intent == "automation_toggle":
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return (
                "No he encontrado la automatización que quieres cambiar. Dime el "
                "nombre exacto (por ejemplo «pausa el sync de PrestaShop») o escribe "
                "«muestra las automatizaciones» para verlas."
            )
        target = data.get("name", "")
        action = data.get("action", "")
        verb = "pausar" if action == "pause" else "activar"
        return (
            f"He preparado la propuesta para {verb} «{target}»: queda pendiente de tu "
            "aprobación en el panel (los agentes proponen, tú decides)."
        )
    if intent == "lead_create":
        if data.get("error") == "missing_email":
            return (
                "Puedo prepararte el alta del lead, pero necesito su email. "
                "Por ejemplo: «crea un lead ana@empresa.com de Empresa SL»."
            )
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return "Ya existe una propuesta de alta para ese lead: revísala en el panel de Aprobaciones."
        auto = data.get("auto_executed", 0)
        name = data.get("name", "")
        email = data.get("email", "")
        if auto:
            return f"Lead «{name}» ({email}) creado al instante dentro de tu autonomía autorizada."
        return (
            f"He preparado la propuesta para crear el lead «{name}» ({email}): "
            "queda pendiente de tu aprobación en el panel."
        )
    if intent == "opportunity_move":
        if data.get("error") == "opportunity_not_found":
            return (
                "No he encontrado la oportunidad que quieres mover. Dime su nombre "
                "o su id, por ejemplo «mueve la oportunidad Presupuesto Q-1 a Negociación»."
            )
        if data.get("error") == "stage_not_found":
            return (
                f"He localizado «{data.get('name')}», pero no reconozco la etapa "
                "destino en el mensaje. Etapas válidas: Nuevo, Calificado, Propuesta, "
                "Negociación, Ganada o Perdida."
            )
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return "Ya hay una propuesta de cambio de etapa para esa oportunidad: revísala en Aprobaciones."
        auto = data.get("auto_executed", 0)
        if auto:
            return f"Oportunidad «{data.get('name')}» movida a {data.get('stage')} dentro de tu autonomía autorizada."
        return (
            f"He preparado la propuesta para mover «{data.get('name')}» a la etapa "
            f"{data.get('stage')}: queda pendiente de tu aprobación en el panel."
        )
    if intent == "task_create":
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return "Ya existe una propuesta de tarea con ese título: revísala en Aprobaciones."
        auto = data.get("auto_executed", 0)
        title = data.get("title", "")
        if auto:
            return f"Tarea «{title}» creada al instante dentro de tu autonomía autorizada."
        return (
            f"He preparado la propuesta para crear la tarea «{title}»: queda "
            "pendiente de tu aprobación en el panel."
        )
    if intent == "campaign_launch":
        if data.get("error") == "missing_name":
            return (
                "Puedo prepararte el lanzamiento de una campaña, pero dime su nombre. "
                "Por ejemplo: «lanza una campaña de bienvenida»."
            )
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return "Ya existe una propuesta de lanzamiento para esa campaña: revísala en Aprobaciones."
        auto = data.get("auto_executed", 0)
        name = data.get("name", "")
        verb = "activada" if data.get("exists") else "creada como borrador"
        if auto:
            return f"Campaña «{name}» {verb} dentro de tu autonomía autorizada."
        return (
            f"He preparado la propuesta para lanzar «{name}» (será {verb}): "
            "queda pendiente de tu aprobación en el panel."
        )
    if intent == "follow_up_cold_leads":
        proposed = data.get("proposed", 0)
        leads = data.get("leads", [])
        auto = data.get("auto_executed", 0)
        pending = max(0, proposed - auto)
        if proposed == 0:
            return (
                "No he encontrado leads fríos que ya no tengan seguimiento: "
                "no hay nada que proponer."
            )
        names = ", ".join(leads[:6])
        extra = f" ({names}{'…' if len(leads) > 6 else ''})" if names else ""
        if pending == 0:
            return (
                f"He creado {auto} follow-ups para leads sin asignar{extra} "
                "y ya están en tu calendario (dentro de tu autonomía autorizada). "
                "Si alguno no te convence, puedes revertirlo desde el digest diario "
                "de decisiones de los agentes."
            )
        return (
            f"He preparado {proposed} propuestas de follow-up para leads sin asignar{extra}: "
            f"{auto} ejecutadas al instante (dentro de tu autonomía) y {pending} "
            "pendientes de tu aprobación en el panel de Aprobaciones — "
            "los agentes proponen, tú decides."
        )
    if intent == "weekly_report":
        s = data["sales"]
        p = data["pipeline"]
        leads_data = data["leads"]
        a = data["activities"]
        ap = data["approvals"]
        so = data["social"]
        st = data["stock"]
        return (
            f"Resumen de la empresa: {s['won_count']} ventas ganadas por "
            f"{s['won_value']} {settings.CURRENCY} con {s['orders_count']} pedidos, y "
            f"pipeline de {p['open_total']} {settings.CURRENCY} en {p['stage_count']} etapas. "
            f"Leads: {leads_data['total']} ({leads_data['unassigned']} sin asignar); "
            f"{a['pending']} actividades pendientes ({a['overdue']} vencidas); "
            f"{ap['pending']} aprobaciones por decidir. Social: {so['urgent']} mensajes "
            f"urgentes de {so['pending']} sin atender; {st['low_count']} productos con "
            "stock bajo."
        )
    if intent == "aging_report":
        if data["open_count"] == 0:
            return "No hay oportunidades abiertas: no hay nada estancado en el pipeline."
        lines = [
            f"Hay {data['open_count']} oportunidades abiertas "
            f"({data['stale_count']} sin movimiento en 7+ días). Las más antiguas:"
        ]
        for r in data["items"][:8]:
            lines.append(
                f"· {r['name']} ({r['stage']}) — {r['days_in_stage']} días, "
                f"{r['value']} {settings.CURRENCY}"
            )
        return "\n".join(lines)
    if intent == "top_products":
        if not data["top"]:
            return (
                "Todavía no hay pedidos confirmados: no puedo calcular "
                "qué se vende más."
            )
        lines = [
            "Tus productos más vendidos (por unidades en pedidos confirmados):"
        ]
        for r in data["top"][:8]:
            lines.append(
                f"· {r['name']} ({r['sku'] or '-'}) — {r['qty']} uds, "
                f"{r['revenue']} {settings.CURRENCY}"
            )
        return "\n".join(lines)
    if intent == "social_sla":
        if data["count"] == 0:
            return "No hay mensajes urgentes sin atender: la bandeja social está al día."
        lines = [
            f"Hay {data['count']} mensajes urgentes triados que siguen sin respuesta:"
        ]
        for r in data["items"][:8]:
            hours = f"{r['age_hours']}h" if r["age_hours"] is not None else "—"
            lines.append(
                f"· {r['sender']} ({r['intent']}, urgencia {r['urgency']}): "
                f"{r['body_preview']} — {hours} sin atender"
            )
        return "\n".join(lines)
    if intent == "lead_assign":
        if data.get("error") == "lead_not_found":
            return (
                "No he encontrado ese lead. Dime su email, su nombre o su id, por "
                "ejemplo «asigna el lead de ana@empresa.com a carlos»."
            )
        if data.get("error") == "assignee_not_found":
            return (
                f"He localizado «{data.get('lead_name')}», pero no reconozco al "
                "comercial en el mensaje. Usa su usuario, por ejemplo «… a carlos»."
            )
        proposed = data.get("proposed", 0)
        auto = data.get("auto_executed", 0)
        if proposed == 0:
            return "Ya hay una propuesta de asignación para ese lead: revísala en Aprobaciones."
        if auto:
            return (
                f"Lead «{data.get('lead_name')}» asignado a {data.get('assignee')} "
                "dentro de tu autonomía autorizada."
            )
        return (
            f"He preparado la propuesta para asignar «{data.get('lead_name')}» a "
            f"{data.get('assignee')}: queda pendiente de tu aprobación."
        )
    if intent == "opportunity_close":
        if data.get("error") == "opportunity_not_found":
            return (
                "No he encontrado esa oportunidad. Dime su nombre o su id, por "
                "ejemplo «cierra la oportunidad Presupuesto Q-1 como ganada»."
            )
        if data.get("error") == "outcome_not_found":
            return (
                f"He localizado «{data.get('name')}», pero dime si la cierro como "
                "ganada o como perdida."
            )
        proposed = data.get("proposed", 0)
        auto = data.get("auto_executed", 0)
        outcome = data.get("outcome", "")
        if proposed == 0:
            return "Ya hay una propuesta de cierre para esa oportunidad: revísala en Aprobaciones."
        if auto:
            return (
                f"Oportunidad «{data.get('name')}» cerrada como {outcome} dentro de "
                "tu autonomía autorizada."
            )
        return (
            f"He preparado la propuesta para cerrar «{data.get('name')}» como "
            f"{outcome}: queda pendiente de tu aprobación."
        )
    if intent == "stock_adjust":
        if data.get("error") == "product_not_found":
            return (
                "No he encontrado ese producto. Dime su SKU o su nombre, por "
                "ejemplo «ajusta el stock de SKU-100 a 25»."
            )
        if data.get("error") == "missing_stock":
            return (
                f"He localizado «{data.get('name')}» ({data.get('sku')}), pero dime "
                "la cantidad, por ejemplo «… a 25 uds»."
            )
        proposed = data.get("proposed", 0)
        auto = data.get("auto_executed", 0)
        if proposed == 0:
            return "Ya hay una propuesta de ajuste para ese producto: revísala en Aprobaciones."
        if auto:
            return (
                f"Stock de «{data.get('name')}» ajustado a {data.get('new_stock')} uds "
                "dentro de tu autonomía autorizada."
            )
        return (
            f"He preparado la propuesta para poner el stock de «{data.get('name')}» "
            f"en {data.get('new_stock')} uds: queda pendiente de tu aprobación."
        )
    if intent == "product_price_update":
        if data.get("error") == "product_not_found":
            return (
                "No he encontrado ese producto. Dime su SKU o su nombre, por "
                "ejemplo «actualiza el precio de SKU-100 a 45,90»."
            )
        if data.get("error") == "missing_price":
            return (
                f"He localizado «{data.get('name')}» ({data.get('sku')}), pero dime "
                "el nuevo precio, por ejemplo «… a 45,90 €»."
            )
        proposed = data.get("proposed", 0)
        auto = data.get("auto_executed", 0)
        if proposed == 0:
            return "Ya hay una propuesta de cambio de precio para ese producto: revísala en Aprobaciones."
        if auto:
            return (
                f"Precio de «{data.get('name')}» actualizado a {data.get('new_price')} "
                f"{settings.CURRENCY} dentro de tu autonomía autorizada."
            )
        return (
            f"He preparado la propuesta para poner el precio de «{data.get('name')}» "
            f"en {data.get('new_price')} {settings.CURRENCY}: queda pendiente de tu "
            "aprobación."
        )
    if intent == "ghl_send_message":
        if data.get("error") == "channel_not_found":
            return (
                "¿Por qué canal quieres contactar? Dime «sms», «email» o «whatsapp», "
                "por ejemplo «envía un sms a ana@empresa.com que diga: tu pedido está listo»."
            )
        if data.get("error") == "lead_not_found":
            return (
                "No encuentro ese lead en el CRM. Dime su email exacto, por ejemplo "
                "«envía un email a ana@empresa.com que diga: …», o créalo primero."
            )
        if data.get("error") == "missing_content":
            return (
                "Puedo preparar el envío, pero dime el texto del mensaje. Por ejemplo: "
                "«envía un sms a ana@empresa.com que diga: tu pedido está listo»."
            )
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return (
                "Ya existe una propuesta de envío para ese lead y mensaje: "
                "revísala en el panel de Aprobaciones."
            )
        auto = data.get("auto_executed", 0)
        if auto:
            return (
                f"He enviado el {data.get('channel')} a «{data.get('lead_name')}» "
                "(autonomía autorizada) y queda registrado en el digest diario."
            )
        return (
            f"He preparado la propuesta para enviar el {data.get('channel')} a "
            f"«{data.get('lead_name')}»: queda pendiente de tu aprobación en el panel."
        )
    if intent == "ghl_create_contact":
        if data.get("error") == "missing_email":
            return (
                "Necesito el email del contacto para darlo de alta en GHL. Por "
                "ejemplo: «añade a GHL ana@empresa.com»."
            )
        proposed = data.get("proposed", 0)
        if proposed == 0:
            return (
                "Ya existe una propuesta de alta en GHL para ese email: "
                "revísala en el panel de Aprobaciones."
            )
        auto = data.get("auto_executed", 0)
        if auto:
            return (
                f"He creado el contacto {data.get('email')} en GHL (autonomía "
                "autorizada) y queda registrado en el digest diario."
            )
        return (
            f"He preparado la propuesta para dar de alta {data.get('email')} en GHL: "
            "queda pendiente de tu aprobación en el panel."
        )
    if intent == "help":
        return (
            "Puedo informarte al momento de: ventas («¿cómo van las ventas?»), pipeline "
            "(«¿cómo va el pipeline?»), leads («¿cuántos leads hay?»), actividades "
            "(«¿qué tengo pendiente?»), aprobaciones («¿qué hay que aprobar?»), bandeja "
            "social («¿hay mensajes urgentes?»), stock («¿hay stock bajo?»), agentes "
            "(«estado de los agentes»), automatizaciones («muestra las automatizaciones»), "
            "el resumen de la empresa («resumen de la semana»), la antigüedad del pipeline "
            "(«¿qué oportunidades llevan más tiempo abiertas?»), los más vendidos "
            "(«¿qué productos se venden más?») y los mensajes fuera de SLA («¿hay "
            "mensajes sin atender?»). Y preparo acciones para que solo las confirmes: "
            "follow-ups de leads fríos, asignar leads («asigna el lead de ana@empresa.com "
            "a carlos»), cerrar oportunidades («cierra el trato Q-1 como ganada»), pausar "
            "o activar automatizaciones («pausa el sync de PrestaShop»), ajustar stock "
            "(«ajusta el stock de SKU-100 a 25»), actualizar precios («sube el precio "
            "de SKU-100 a 49»), enviar mensajes a un lead vía GHL («envía un sms a "
            "ana@empresa.com que diga: tu pedido está listo») y dar de alta contactos "
            f"en GHL («añade a GHL ana@empresa.com»). Todo en {settings.CURRENCY}."
        )
    return (
        "No he entendido la petición. Puedo informarte de ventas, pipeline, leads, "
        "actividades, aprobaciones, bandeja social, stock, agentes, automatizaciones, "
        "resumen semanal, antigüedad del pipeline y productos más vendidos; o prepararte "
        "acciones (follow-ups, asignar leads, cerrar oportunidades, ajustar stock, cambiar "
        "precios, enviar SMS/email vía GHL o dar de alta contactos en GHL) con tu "
        "aprobación. Prueba con «¿cómo van las ventas?» o «resumen de la semana»."
    )


# ---------------------------------------------------------------------------
# Acciones: follow-up de leads fríos (propuesta, nunca ejecución)
# ---------------------------------------------------------------------------

_CEO_FOLLOW_UP_ACTION = "agent_proposal:ceo_follow_up"


def _cold_leads(db: Session, now: datetime.datetime | None = None) -> list[Lead]:
    """Leads fríos: sin comercial asignado y sin actividad de seguimiento
    pendiente ni propuesta previa (pendiente o aprobada)."""

    from app.services.agent_proposals import _proposal_exists

    now = now or _utcnow()
    candidates = (
        db.query(Lead)
        .filter(Lead.assigned_to.is_(None))
        .order_by(Lead.created_at.asc())
        .limit(_MAX_COLD_LEADS * 2)
        .all()
    )
    cold: list[Lead] = []
    for lead in candidates:
        if _proposal_exists(
            db, action_type=_CEO_FOLLOW_UP_ACTION, target_key=lead.id
        ):
            continue
        has_pending = (
            db.query(Activity.id)
            .filter(
                Activity.lead_id == lead.id,
                Activity.status == "pending",
            )
            .first()
            is not None
        )
        if has_pending:
            continue
        cold.append(lead)
        if len(cold) >= _MAX_COLD_LEADS:
            break
    return cold


def propose_cold_lead_follow_ups(db: Session, lead_ids: list[str] | None = None) -> list[ApprovalRequest]:
    """Crea las propuestas de follow-up del CEO (dedupe por unicidad)."""

    from app.services.agent_proposals import _add_proposal

    leads = (
        _cold_leads(db)
        if lead_ids is None
        else [lead for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all() if lead.assigned_to is None]
    )
    proposed: list[ApprovalRequest] = []
    now = _utcnow()
    for lead in leads:
        proposal = _add_proposal(
            db,
            action_type=_CEO_FOLLOW_UP_ACTION,
            target_key=lead.id,
            payload={
                "action": "create_follow_up",
                "lead_id": lead.id,
                "title": f"Follow-up CEO: {lead.first_name or 'lead sin asignar'}",
                "rationale": (
                    "Lead sin comercial asignado propuesto por el CEO agent "
                    f"(alta {lead.created_at.isoformat() if lead.created_at else 'desconocida'})."
                ),
                "due_at": (now + datetime.timedelta(hours=24)).isoformat(),
            },
            agent_id=CEO_AGENT_ID,
        )
        if proposal is not None:
            proposed.append(proposal)
    return proposed


# ---------------------------------------------------------------------------
# Acciones: pausar/activar automatizaciones (propuesta, nunca ejecución)
# ---------------------------------------------------------------------------

_AUTOMATION_TOGGLE_ACTION = "agent_proposal:automation_toggle"
_PAUSE_VERBS = ("pausa", "pausar", "deten", "detén", "para")
_ACTIVATE_VERBS = ("activa", "arranca", "reactiva", "reinicia")


def _resolve_automation_toggle(
    db: Session, message: str
) -> tuple[ScheduledTask | None, str]:
    """Resuelve (automatización, acción) de forma determinista.

    Busca la tarea programada cuyo nombre (o tipo) aparece en el mensaje y
    decide pausar/activar por el verbo usado. Sin coincidencia → (None, "").
    """

    norm = _normalize(message)
    action = "pause" if any(v in norm for v in _PAUSE_VERBS) else "activate"
    rows = db.query(ScheduledTask).all()

    def _tokens(text: str) -> list[str]:
        # Tokens significativos: palabras con más de 2 caracteres (se cae
        # el id aleatorio tipo ``e2ef409435f495e`` que no aporta al match).
        return [t for t in text.split() if len(t) > 2]

    # 1) coincidencia por nombre normalizado dentro del mensaje
    for task in rows:
        if _normalize(task.name) and _normalize(task.name) in norm:
            return task, action
    # 2) el mensaje nombra solo una parte del nombre (p. ej. «el barrido E2E»
    #    para «Barrido E2E e2ef409435f495e»)
    best: tuple[int, ScheduledTask] | None = None
    for task in rows:
        name_norm = _normalize(task.name)
        if not name_norm:
            continue
        if norm in name_norm:
            return task, action
        # 3) solapamiento de tokens significativos consecutivos
        ntoks = _tokens(name_norm)
        hit = 0
        for i in range(len(ntoks) - 1):
            if f"{ntoks[i]} {ntoks[i + 1]}" in norm:
                hit = max(hit, 2)
            elif ntoks[i] in norm:
                hit = max(hit, 1)
        if hit and (best is None or hit > best[0]):
            best = (hit, task)
    if best is not None:
        return best[1], action
    # 4) coincidencia por tipo de tarea (p. ej. «sync de PrestaShop»)
    for task in rows:
        task_type_norm = _normalize((task.task_type or "").replace("_", " "))
        if task_type_norm and task_type_norm in norm:
            return task, action
    return None, action


def propose_automation_toggle(
    db: Session,
    task: ScheduledTask,
    action: str,
) -> ApprovalRequest | None:
    """Crea la propuesta de pausar/activar la automatización (dedupe)."""

    from app.services.agent_proposals import _add_proposal

    verb = "pausar" if action == "pause" else "activar"
    return _add_proposal(
        db,
        action_type=_AUTOMATION_TOGGLE_ACTION,
        target_key=task.id,
        payload={
            "action": action,
            "task_id": task.id,
            "name": task.name,
            "task_type": task.task_type,
            "rationale": (
                f"El dueño pidió {verb} la automatización «{task.name}» "
                f"({task.task_type}) desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


# ---------------------------------------------------------------------------
# Acciones de módulo del chat (T-075): crear lead, mover oportunidad, crear
# tarea y lanzar campaña — siempre como propuesta auditada (deny-by-default;
# solo se auto-ejecuta dentro de la autonomía autorizada del CEO agent).
# ---------------------------------------------------------------------------

_CEO_CREATE_LEAD_ACTION = "agent_proposal:ceo_create_lead"
_CEO_MOVE_OPPORTUNITY_ACTION = "agent_proposal:ceo_move_opportunity"
_CEO_CREATE_TASK_ACTION = "agent_proposal:ceo_create_task"
_CEO_LAUNCH_CAMPAIGN_ACTION = "agent_proposal:ceo_launch_campaign"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

_TASK_KINDS = {
    "llamada": "call",
    "llamar": "call",
    "reunion": "meeting",
    "reunión": "meeting",
    "email": "email",
    "correo": "email",
    "follow up": "follow_up",
    "seguimiento": "follow_up",
    "tarea": "follow_up",
}


def _resolve_create_lead(db: Session, message: str) -> dict[str, Any] | None:
    """Extrae email + nombre/empresa de «crea un lead …» (determinista).

    Sin email no se puede crear la propuesta: se devuelve el motivo para
    que la respuesta pida el dato que falta.
    """

    match = _EMAIL_RE.search(message or "")
    if match is None:
        return {"error": "missing_email"}
    email = match.group(0).strip().lower()
    name = "Lead vía chat"
    company: str | None = None
    rest = message[: match.start()] + message[match.end() :]
    rest = _normalize(rest)
    for token in ("crea un lead", "crear un lead", "crear lead", "nuevo lead", "para"):
        rest = rest.replace(token, "")
    rest = re.sub(r"^[\s,:;-]+", "", rest).strip()
    # «de <Empresa>» (al principio o al final) → empresa; el resto → nombre.
    company = None
    if rest.startswith("de "):
        company = rest[3:].strip()
        rest = ""
    elif " de " in rest:
        parts = rest.split(" de ", 1)
        if parts[0].strip():
            name = parts[0].strip().title()
        company = parts[1].strip().title() if parts[1].strip() else None
    if rest:
        name = rest.title()
    return {
        "email": email,
        "name": name[:120],
        "company": company[:120] if company else None,
    }


def propose_create_lead(db: Session, lead: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de alta de lead (dedupe por email)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_CREATE_LEAD_ACTION,
        target_key=lead["email"],
        payload={
            "action": "create_lead",
            "email": lead["email"],
            "name": lead["name"],
            "company": lead.get("company"),
            "rationale": (
                f"El dueño pidió crear el lead «{lead['name']}» "
                f"({lead['email']}) desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_opportunity_move(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve (oportunidad, etapa destino) de «mueve la oportunidad …»."""

    norm = _normalize(message)
    id_match = _UUID_RE.search(norm)
    opportunity: Opportunity | None = None
    opportunities = db.query(Opportunity).all()
    if id_match:
        opportunity = (
            db.query(Opportunity).filter(Opportunity.id == id_match.group(0)).first()
        )
    else:
        # Coincidencia por id literal (no UUID), nombre o referencia externa.
        for opp in opportunities:
            if opp.id and _normalize(opp.id) in norm:
                opportunity = opp
                break
    if opportunity is None:
        for opp in opportunities:
            if opp.name and _normalize(opp.name) in norm:
                opportunity = opp
                break
            if opp.external_reference and _normalize(opp.external_reference) in norm:
                opportunity = opp
                break
    if opportunity is None:
        return {"error": "opportunity_not_found"}

    # Etapa destino: nombre de una etapa configurada presente en el mensaje.
    stages = (
        db.query(PipelineStage).order_by(PipelineStage.position.asc()).all()
    )
    if not stages:
        # Fallback determinista sin necesidad de sembrar el pipeline.
        stages = [
            type("S", (), {"key": key, "name": name})
            for key, name in (
                ("new", "Nuevo"),
                ("qualified", "Calificado"),
                ("proposal", "Propuesta"),
                ("negotiation", "Negociación"),
                ("won", "Ganada"),
                ("lost", "Perdida"),
            )
        ]
    for stage in stages:
        stage_norm = _normalize(stage.key).replace("_", " ")
        name_norm = _normalize(stage.name).replace("_", " ")
        if (stage_norm and stage_norm in norm) or (name_norm and name_norm in norm):
            return {
                "opportunity_id": opportunity.id,
                "name": opportunity.name,
                "stage": stage.key,
                "current_stage": opportunity.stage,
            }
    return {"error": "stage_not_found", "opportunity_id": opportunity.id, "name": opportunity.name}


def propose_opportunity_move(db: Session, resolved: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de cambio de etapa (dedupe por oportunidad)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_MOVE_OPPORTUNITY_ACTION,
        target_key=resolved["opportunity_id"],
        payload={
            "action": "move_stage",
            "opportunity_id": resolved["opportunity_id"],
            "name": resolved["name"],
            "stage": resolved["stage"],
            "current_stage": resolved.get("current_stage"),
            "rationale": (
                f"El dueño pidió mover «{resolved['name']}» a la etapa "
                f"{resolved['stage']} desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_create_task(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «crea una tarea …»: título, lead opcional y tipo."""

    norm = _normalize(message)
    lead: Lead | None = None
    id_match = _UUID_RE.search(norm)
    if id_match:
        lead = db.query(Lead).filter(Lead.id == id_match.group(0)).first()
    else:
        email_match = _EMAIL_RE.search(norm)
        if email_match:
            lead = (
                db.query(Lead)
                .filter(Lead.email == email_match.group(0).lower())
                .first()
            )
    kind = "follow_up"
    for token, value in _TASK_KINDS.items():
        if token in norm:
            kind = value
            break
    title = norm
    title = re.sub(r"crea una tarea|crear una tarea|crear tarea|asigna una tarea|asignar una tarea|recordar que|recordatorio de", "", title)
    title = re.sub(r"(para |con |de |a )?[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", "", title)
    title = re.sub(r"^(para |con |de |a |al )", "", title)
    title = re.sub(r"^[\s,:;-]+", "", title).strip()
    title = title[:180] or "Tarea desde el chat"
    return {
        "title": title,
        "lead_id": lead.id if lead else None,
        "kind": kind,
        "due_at": (_utcnow() + datetime.timedelta(hours=24)).isoformat(),
    }


def propose_create_task(db: Session, resolved: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de tarea/recordatorio (dedupe por lead + título)."""

    from app.services.agent_proposals import _add_proposal

    lead_key = resolved.get("lead_id") or "general"
    target = f"{lead_key}:{resolved['title'][:60]}"
    return _add_proposal(
        db,
        action_type=_CEO_CREATE_TASK_ACTION,
        target_key=target,
        payload={
            "action": "create_task",
            "title": resolved["title"],
            "kind": resolved["kind"],
            "lead_id": resolved.get("lead_id"),
            "due_at": resolved["due_at"],
            "rationale": (
                f"El dueño pidió crear la tarea «{resolved['title']}» "
                f"(tipo {resolved['kind']}) desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_campaign_launch(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «lanza una campaña …»: nombre (entre comillas o tras
    «campaña»). Si la campaña ya existe, la propuesta la activa; si no,
    la crea como borrador listo para configurar."""

    quoted = re.search(r"[“«\"'](.+?)[”»\"']", message or "")
    if quoted:
        name = quoted.group(1).strip()
    else:
        norm = _normalize(message)
        for token in ("lanza una campana de", "lanzar una campana de", "lanza la campana", "campana de", "lanza una campana", "lanzar campana"):
            if token in norm:
                rest = norm.split(token, 1)[1].strip()
                if rest:
                    name = rest
                    break
        else:
            return {"error": "missing_name"}
    if not name:
        return {"error": "missing_name"}
    existing = (
        db.query(Campaign)
        .filter(Campaign.name == name[:200])
        .first()
    )
    return {
        "name": name[:200],
        "exists": existing is not None,
        "campaign_id": existing.id if existing else None,
        "current_status": existing.status if existing else None,
    }


def propose_campaign_launch(db: Session, resolved: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de lanzar/crear campaña (dedupe por nombre)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_LAUNCH_CAMPAIGN_ACTION,
        target_key=resolved["name"],
        payload={
            "action": "activate" if resolved.get("exists") else "create_draft",
            "name": resolved["name"],
            "campaign_id": resolved.get("campaign_id"),
            "current_status": resolved.get("current_status"),
            "rationale": (
                f"El dueño pidió lanzar la campaña «{resolved['name']}» desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


# ---------------------------------------------------------------------------
# T-082: acciones de módulo — asignar lead, cerrar oportunidad, ajustar stock
# y actualizar precio. Siempre como propuesta auditada (deny-by-default; solo
# se auto-ejecutan dentro de la autonomía autorizada del CEO agent; el cambio
# de precio, al ser financiero, solo bajo el umbral).
# ---------------------------------------------------------------------------

_CEO_ASSIGN_LEAD_ACTION = "agent_proposal:ceo_assign_lead"
_CEO_CLOSE_OPPORTUNITY_ACTION = "agent_proposal:ceo_close_opportunity"
_CEO_ADJUST_STOCK_ACTION = "agent_proposal:ceo_adjust_stock"
_CEO_UPDATE_PRICE_ACTION = "agent_proposal:ceo_update_price"


def _resolve_lead_assign(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «asigna el lead … a …»: lead (email/nombre/id) + comercial."""

    norm = _normalize(message)
    lead: Lead | None = None
    id_match = _UUID_RE.search(norm)
    if id_match:
        lead = db.query(Lead).filter(Lead.id == id_match.group(0)).first()
    if lead is None:
        email_match = _EMAIL_RE.search(norm)
        if email_match:
            lead = (
                db.query(Lead)
                .filter(Lead.email == email_match.group(0).lower())
                .first()
            )
    if lead is None:
        for row in db.query(Lead).all():
            if row.first_name and _normalize(row.first_name) and _normalize(row.first_name) in norm:
                lead = row
                break
    if lead is None:
        return {"error": "lead_not_found"}

    assignee: User | None = None
    for row in db.query(User).filter(User.is_active.is_(True)).all():
        if row.username and _normalize(row.username) in norm:
            assignee = row
            break
    if assignee is None:
        return {
            "error": "assignee_not_found",
            "lead_id": lead.id,
            "lead_name": lead.first_name or lead.email,
        }
    return {
        "lead_id": lead.id,
        "lead_name": lead.first_name or lead.email,
        "assignee_id": assignee.id,
        "assignee_username": assignee.username,
    }


def propose_lead_assign(db: Session, resolved: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de asignación de lead (dedupe por lead)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_ASSIGN_LEAD_ACTION,
        target_key=resolved["lead_id"],
        payload={
            "action": "assign_lead",
            "lead_id": resolved["lead_id"],
            "lead_name": resolved["lead_name"],
            "assignee_id": resolved["assignee_id"],
            "assignee_username": resolved["assignee_username"],
            "rationale": (
                f"El dueño pidió asignar el lead «{resolved['lead_name']}» al "
                f"comercial {resolved['assignee_username']} desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_opportunity_close(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «cierra la oportunidad … como ganada/perdida»."""

    norm = _normalize(message)
    opportunity: Opportunity | None = None
    id_match = _UUID_RE.search(norm)
    if id_match:
        opportunity = (
            db.query(Opportunity).filter(Opportunity.id == id_match.group(0)).first()
        )
    if opportunity is None:
        for opp in db.query(Opportunity).all():
            if opp.name and _normalize(opp.name) in norm:
                opportunity = opp
                break
            if opp.id and _normalize(opp.id) in norm:
                opportunity = opp
                break
    if opportunity is None:
        return {"error": "opportunity_not_found"}
    if "perdida" in norm or "perdido" in norm or " lost" in norm:
        outcome = "lost"
    elif "ganada" in norm or "ganado" in norm or " won" in norm:
        outcome = "won"
    else:
        return {
            "error": "outcome_not_found",
            "opportunity_id": opportunity.id,
            "name": opportunity.name,
        }
    lost_reason = None
    if outcome == "lost":
        reason_match = re.search(r"(?:por|motivo|razon|razón)[: ]+(.+)", message or "")
        if reason_match:
            lost_reason = reason_match.group(1).strip()[:500]
    return {
        "opportunity_id": opportunity.id,
        "name": opportunity.name,
        "outcome": outcome,
        "lost_reason": lost_reason,
    }


def propose_opportunity_close(
    db: Session, resolved: dict[str, Any]
) -> ApprovalRequest | None:
    """Propuesta de cierre de oportunidad (dedupe por oportunidad)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_CLOSE_OPPORTUNITY_ACTION,
        target_key=resolved["opportunity_id"],
        payload={
            "action": "close_opportunity",
            "opportunity_id": resolved["opportunity_id"],
            "name": resolved["name"],
            "outcome": resolved["outcome"],
            "lost_reason": resolved.get("lost_reason"),
            "rationale": (
                f"El dueño pidió cerrar «{resolved['name']}» como "
                f"{resolved['outcome']} desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_stock_adjust(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «ajusta el stock de … a N» (producto por SKU/nombre/id)."""

    norm = _normalize(message)
    product: Product | None = None
    id_match = _UUID_RE.search(norm)
    if id_match:
        product = db.query(Product).filter(Product.id == id_match.group(0)).first()
    if product is None:
        for row in db.query(Product).all():
            if row.sku and _normalize(row.sku) in norm:
                product = row
                break
    if product is None:
        for row in db.query(Product).all():
            if row.name and _normalize(row.name) in norm:
                product = row
                break
    if product is None:
        return {"error": "product_not_found"}
    numbers = re.findall(r"\b\d{1,6}\b", norm)
    if not numbers:
        return {
            "error": "missing_stock",
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
        }
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.name,
        "new_stock": int(numbers[-1]),
    }


def propose_stock_adjust(db: Session, resolved: dict[str, Any]) -> ApprovalRequest | None:
    """Propuesta de ajuste de stock (dedupe por producto)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_ADJUST_STOCK_ACTION,
        target_key=resolved["product_id"],
        payload={
            "action": "adjust_stock",
            "product_id": resolved["product_id"],
            "sku": resolved["sku"],
            "name": resolved["name"],
            "new_stock": resolved["new_stock"],
            "rationale": (
                f"El dueño pidió poner el stock de «{resolved['name']}» "
                f"({resolved['sku']}) en {resolved['new_stock']} uds desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_product_price(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «actualiza el precio de … a N» (producto por SKU/nombre/id)."""

    norm = _normalize(message)
    product: Product | None = None
    id_match = _UUID_RE.search(norm)
    if id_match:
        product = db.query(Product).filter(Product.id == id_match.group(0)).first()
    if product is None:
        for row in db.query(Product).all():
            if row.sku and _normalize(row.sku) in norm:
                product = row
                break
    if product is None:
        for row in db.query(Product).all():
            if row.name and _normalize(row.name) in norm:
                product = row
                break
    if product is None:
        return {"error": "product_not_found"}
    numbers = re.findall(r"\b\d{1,6}(?:[.,]\d{1,2})?\b", norm)
    if not numbers:
        return {
            "error": "missing_price",
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
        }
    new_price = float(numbers[-1].replace(",", "."))
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.name,
        "new_price": new_price,
    }


def propose_product_price(
    db: Session, resolved: dict[str, Any]
) -> ApprovalRequest | None:
    """Propuesta de cambio de precio (financiera: dedupe por producto)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_UPDATE_PRICE_ACTION,
        target_key=resolved["product_id"],
        payload={
            "action": "update_price",
            "product_id": resolved["product_id"],
            "sku": resolved["sku"],
            "name": resolved["name"],
            "new_price": resolved["new_price"],
            # Impacto financiero para la política de umbral de la autonomía:
            # el cambio se auto-ejecuta solo si el nuevo precio queda por
            # debajo de ``max_value_threshold`` EUR del agente.
            "value_eur": resolved["new_price"],
            "rationale": (
                f"El dueño pidió poner el precio de «{resolved['name']}» "
                f"({resolved['sku']}) en {resolved['new_price']} EUR desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


# ---------------------------------------------------------------------------
# T-083: canal GoHighLevel — enviar SMS/email a un lead y crear un contacto
# en GHL. Siempre como propuesta auditada (deny-by-default); al aprobarse el
# efecto se encola en el outbox durable (entrega con reintentos y DLQ).
# ---------------------------------------------------------------------------

_CEO_GHL_SEND_MESSAGE_ACTION = "agent_proposal:ghl_send_message"
_CEO_GHL_CREATE_CONTACT_ACTION = "agent_proposal:ghl_create_contact"


def _content_key(content: str) -> str:
    """Huella corta del contenido para dedupe de propuestas: reenviar el
    mismo texto al mismo lead no duplica; un texto distinto sí es nueva
    propuesta."""

    import hashlib

    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:8]


def _resolve_ghl_send_message(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «envía un sms/email a … que diga …»: canal + lead + texto."""

    norm = _normalize(message)
    if "whatsapp" in norm:
        channel = "whatsapp"
    elif "sms" in norm:
        channel = "sms"
    elif "email" in norm or "correo" in norm:
        channel = "email"
    else:
        return {"error": "channel_not_found"}

    lead: Lead | None = None
    email_match = _EMAIL_RE.search(norm)
    if email_match:
        lead = (
            db.query(Lead)
            .filter(Lead.email == email_match.group(0).lower())
            .first()
        )
    if lead is None:
        id_match = _UUID_RE.search(norm)
        if id_match:
            lead = db.query(Lead).filter(Lead.id == id_match.group(0)).first()
    if lead is None:
        for row in db.query(Lead).all():
            if (
                row.first_name
                and _normalize(row.first_name)
                and _normalize(row.first_name) in norm
            ):
                lead = row
                break
    if lead is None:
        return {"error": "lead_not_found"}

    # El texto se extrae del mensaje ORIGINAL (no normalizado) para no perder
    # acentos ni mayúsculas de lo que el dueño quiere enviar.
    raw = message or ""
    raw_lower = raw.lower()
    content: str | None = None
    for marker in (
        "que diga",
        "que ponga",
        "diciendo",
        "con el texto",
        "con el mensaje",
        "con este texto",
    ):
        idx = raw_lower.find(marker)
        if idx != -1:
            content = raw[idx + len(marker) :].strip()
            break
    if content is None:
        quoted = re.search(r"[“«\"'](.+?)[”»\"']", raw)
        if quoted:
            content = quoted.group(1).strip()
    if content is not None:
        # Quitar separadores que quedan tras el marcador («que diga: …»).
        content = content.lstrip(":,;").strip()
    if not content:
        return {
            "error": "missing_content",
            "lead_id": lead.id,
            "lead_name": lead.first_name or lead.email,
            "channel": channel,
        }
    return {
        "lead_id": lead.id,
        "lead_name": lead.first_name or lead.email,
        "email": lead.email,
        "phone": lead.phone,
        "channel": channel,
        "content": content[:4000],
    }


def propose_ghl_send_message(
    db: Session, resolved: dict[str, Any]
) -> ApprovalRequest | None:
    """Propuesta de envío de mensaje vía GHL (dedupe por lead+canal+texto)."""

    from app.services.agent_proposals import _add_proposal

    target_key = (
        f"{resolved['lead_id']}:{resolved['channel']}:"
        f"{_content_key(resolved['content'])}"
    )
    return _add_proposal(
        db,
        action_type=_CEO_GHL_SEND_MESSAGE_ACTION,
        target_key=target_key,
        payload={
            "action": "send_message",
            "lead_id": resolved["lead_id"],
            "lead_name": resolved["lead_name"],
            "email": resolved["email"],
            "phone": resolved.get("phone"),
            "channel": resolved["channel"],
            "content": resolved["content"],
            "rationale": (
                f"El dueño pidió enviar un {resolved['channel']} a "
                f"«{resolved['lead_name']}» ({resolved['email']}) desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


def _resolve_ghl_create_contact(db: Session, message: str) -> dict[str, Any] | None:
    """Resuelve «añade a GHL …»: contacto por email (con datos del lead local
    si ya existe, o un nombre razonable extraído del mensaje)."""

    norm = _normalize(message)
    email_match = _EMAIL_RE.search(norm)
    if not email_match:
        return {"error": "missing_email"}
    email = email_match.group(0).lower()
    lead = db.query(Lead).filter(Lead.email == email).first()
    if lead is not None:
        return {
            "email": email,
            "first_name": lead.first_name,
            "phone": lead.phone,
            "company_name": lead.company_name,
            "lead_id": lead.id,
        }

    # Sin lead local: intentar un nombre razonable del texto previo al email.
    raw = message or ""
    idx = raw.lower().find(email_match.group(0).lower())
    prefix = raw[:idx] if idx > 0 else ""
    name: str | None = None
    for token in (
        "crea un contacto en ghl para ",
        "crear un contacto en ghl para ",
        "crea un contacto para ",
        "anade a ghl a ",
        "añade a ghl a ",
        "sincroniza con ghl a ",
        "dalo de alta en ghl a ",
        "para ",
        "a ",
    ):
        prefix_lower = prefix.lower()
        if token in prefix_lower:
            idx = prefix_lower.find(token)
            # Extraer del mensaje ORIGINAL para conservar mayúsculas/acentos.
            candidate = prefix[idx + len(token) :].strip()
            if candidate:
                name = re.sub(r"[.,;:]+$", "", candidate).strip()[:120]
            break
    return {
        "email": email,
        "first_name": name or "Contacto GHL",
        "phone": None,
        "company_name": None,
        "lead_id": None,
    }


def propose_ghl_create_contact(
    db: Session, resolved: dict[str, Any]
) -> ApprovalRequest | None:
    """Propuesta de alta de contacto en GHL (dedupe por email)."""

    from app.services.agent_proposals import _add_proposal

    return _add_proposal(
        db,
        action_type=_CEO_GHL_CREATE_CONTACT_ACTION,
        target_key=resolved["email"],
        payload={
            "action": "create_contact",
            "email": resolved["email"],
            "first_name": resolved["first_name"],
            "phone": resolved.get("phone"),
            "company_name": resolved.get("company_name"),
            "lead_id": resolved.get("lead_id"),
            "rationale": (
                f"El dueño pidió dar de alta el contacto {resolved['email']} "
                "en GHL desde el chat."
            ),
        },
        agent_id=CEO_AGENT_ID,
    )


# ---------------------------------------------------------------------------
# Chat del CEO: orquestación, memoria y auditoría
# ---------------------------------------------------------------------------


async def ceo_chat(
    db: Session,
    *,
    message: str,
    conversation_id: str,
    username: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Procesa un mensaje del dueño y devuelve la respuesta del CEO agent."""

    conversation_id = (conversation_id or "ceo-default").strip() or "ceo-default"
    agent_ai.append_conversation_message(
        db,
        account_id=CEO_ACCOUNT_ID,
        conversation_id=conversation_id,
        role="client",
        content=message,
    )
    history = agent_ai.conversation_history(
        db, account_id=CEO_ACCOUNT_ID, conversation_id=conversation_id
    )
    prior = history
    if prior and prior[-1].get("role") == "client" and str(prior[-1].get("content") or "").strip() == (message or "").strip():
        prior = prior[:-1]

    intent = resolve_intent(message)
    data: dict[str, Any] = {}
    proposals: list[dict[str, Any]] = []

    if intent == "follow_up_cold_leads":
        created = propose_cold_lead_follow_ups(db)
        db.flush()
        # T-068: autonomía por excepción — las propuestas dentro del umbral
        # del CEO agent se ejecutan al instante (registradas como
        # ``AgentDecision``); el resto queda pendiente de aprobación humana.
        auto = auto_execute_proposals(db, created)
        db.flush()
        data = {
            "proposed": len(created),
            "auto_executed": len(auto["executed"]),
            "leads": [
                (str(p.payload.get("title") or "")).replace("Follow-up CEO: ", "")
                for p in created
            ],
        }
        proposals = [
            {
                "id": p.id,
                "action_type": p.action_type,
                "target_key": p.target_key,
                "status": p.status,
                "requested_by": p.requested_by,
                "decision_id": next(
                    (
                        d.id
                        for d in auto["executed"]
                        if d.approval_id == p.id
                    ),
                    None,
                ),
            }
            for p in created
        ]
    elif intent == "automation_toggle":
        task, action = _resolve_automation_toggle(db, message)
        if task is None:
            data = {"proposed": 0, "name": "", "action": action}
        else:
            proposal = propose_automation_toggle(db, task, action)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": task.name,
                "action": action,
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "lead_create":
        resolved = _resolve_create_lead(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0}
        else:
            proposal = propose_create_lead(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "email": resolved["email"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "opportunity_move":
        resolved = _resolve_opportunity_move(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_opportunity_move(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "stage": resolved["stage"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "task_create":
        resolved = _resolve_create_task(db, message)
        proposal = propose_create_task(db, resolved)
        db.flush()
        created = [proposal] if proposal is not None else []
        auto = auto_execute_proposals(db, created)
        db.flush()
        data = {
            "proposed": len(created),
            "auto_executed": len(auto["executed"]),
            "title": resolved["title"],
            "kind": resolved["kind"],
        }
        proposals = [
            {
                "id": p.id,
                "action_type": p.action_type,
                "target_key": p.target_key,
                "status": p.status,
                "requested_by": p.requested_by,
            }
            for p in created
        ]
    elif intent == "campaign_launch":
        resolved = _resolve_campaign_launch(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0}
        else:
            proposal = propose_campaign_launch(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "exists": resolved.get("exists", False),
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "lead_assign":
        resolved = _resolve_lead_assign(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_lead_assign(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "lead_name": resolved["lead_name"],
                "assignee": resolved["assignee_username"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "opportunity_close":
        resolved = _resolve_opportunity_close(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_opportunity_close(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "outcome": resolved["outcome"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "stock_adjust":
        resolved = _resolve_stock_adjust(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_stock_adjust(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "sku": resolved["sku"],
                "new_stock": resolved["new_stock"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "product_price_update":
        resolved = _resolve_product_price(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_product_price(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "name": resolved["name"],
                "sku": resolved["sku"],
                "new_price": resolved["new_price"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "ghl_send_message":
        resolved = _resolve_ghl_send_message(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_ghl_send_message(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "lead_name": resolved["lead_name"],
                "channel": resolved["channel"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent == "ghl_create_contact":
        resolved = _resolve_ghl_create_contact(db, message)
        if resolved.get("error"):
            data = {"error": resolved["error"], "proposed": 0, **resolved}
        else:
            proposal = propose_ghl_create_contact(db, resolved)
            db.flush()
            created = [proposal] if proposal is not None else []
            auto = auto_execute_proposals(db, created)
            db.flush()
            data = {
                "proposed": len(created),
                "auto_executed": len(auto["executed"]),
                "email": resolved["email"],
            }
            proposals = [
                {
                    "id": p.id,
                    "action_type": p.action_type,
                    "target_key": p.target_key,
                    "status": p.status,
                    "requested_by": p.requested_by,
                }
                for p in created
            ]
    elif intent in _GATHERERS:
        data = _GATHERERS[intent](db)

    answer_text: str | None = None
    provider_used = "deterministic"
    if intent not in ("greeting", "follow_up_cold_leads") and intent in _GATHERERS and agent_ai._real_llm_configured():
        try:
            from app.services.llm_router import LLMRouterService

            facts = _facts_block(intent, data)
            result = await LLMRouterService(db).generate_response(
                f"Petición del dueño: {message}\n\n"
                f"DATOS VERIFICADOS ({_INTENT_LABEL[intent]}):\n{facts}\n\n"
                "Responde en español, breve y natural, como un mensaje de chat en "
                "texto plano: sin markdown, sin negritas ni asteriscos, sin viñetas "
                "ni guiones de lista, sin encabezados. Una idea por línea si "
                "enumeras, sin símbolos delante. Si el bloque tiene muchos "
                "elementos, no los vuelques todos: resume por tipo con conteos y "
                "menciona solo 1-3 ejemplos como mucho. Usa SOLO esos datos. "
                "Nunca inventes cifras ni menciones datos que no estén en el bloque. "
                "Si no hay datos, dilo.",
                profile="standard",
                system_prompt=(
                    "Eres el asistente de dirección (CEO agent) de una empresa gestionada "
                    "por una sola persona con ayuda de agentes de IA. Hablas en español, "
                    "conciso y directo. Solo respondes con datos verificados del bloque. "
                    "Las acciones se proponen, nunca se ejecutan sin aprobación.\n"
                    "Formato: texto plano de chat, como un mensaje de WhatsApp o Teams: "
                    "sin markdown, sin negritas ni asteriscos, sin viñetas ni guiones de "
                    "lista, sin encabezados ni código. Frases cortas y naturales; si "
                    "enumeras, una idea por línea sin símbolos delante."
                ),
            )
            content = (result.get("content") or "").strip()
            if not result.get("simulated") and content:
                answer_text = agent_ai._polish_answer(
                    agent_ai._strip_greeting_repeat(
                        _plain_chat_text(content), has_history=bool(prior), intent=intent
                    )
                )
                provider_used = str(result.get("provider") or "deterministic").strip().lower()
        except Exception:
            answer_text = None
            provider_used = "deterministic"

    if answer_text is None:
        answer_text = agent_ai._polish_answer(
            _plain_chat_text(_template_answer(intent, data))
        )

    agent_ai.append_conversation_message(
        db,
        account_id=CEO_ACCOUNT_ID,
        conversation_id=conversation_id,
        role="assistant",
        content=answer_text,
    )
    db.add(
        AuditLog(
            installation_id=_installation_id(db),
            agent_id=CEO_AGENT_ID,
            user_id=user_id,
            event_type="ceo_chat.message",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={
                "conversation_id": conversation_id,
                "intent": intent,
                "intent_label": _INTENT_LABEL[intent],
                "provider": provider_used,
                "proposals": len(proposals),
                "answer": answer_text[:_ANSWER_MAX_AUDIT_CHARS],
            },
        )
    )
    db.commit()
    return {
        "answer": answer_text,
        "intent": intent,
        "intent_label": _INTENT_LABEL[intent],
        "provider": provider_used,
        "conversation_id": conversation_id,
        "proposals": proposals,
    }


def _installation_id(db: Session) -> str:
    from app.installation_context import get_current_installation_id

    return get_current_installation_id() or "unknown"
