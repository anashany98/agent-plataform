"""Propuestas de agentes por módulo (Fase 2, T-058).

Los agentes especializados NO ejecutan: **proponen**. Cada propuesta es un
``ApprovalRequest`` (reutilizando el flujo de aprobación humana existente) con
``action_type`` ``agent_proposal:<accion>`` y ``requested_by`` = id del agente:

- ``agent_proposal:create_follow_up`` (``crm_agent``): propone una actividad
  de follow-up para un lead con mensaje social urgente (queja o lead con
  ``urgency >= 40``) cuya actividad de seguimiento falta o está vencida.
- ``agent_proposal:dismiss_message`` (``social_agent``): propone descartar un
  mensaje triado como spam (score 0) que sigue en el inbox.

Reglas de negocio (deterministas, sin LLM/red):

- Una misma propuesta (action_type + target_key) solo existe una vez: la
  unicidad de ``ApprovalRequest`` y la consulta previa evitan duplicados; un
  re-run no propone lo ya propuesto (pendiente o decidido).
- El re-run re-propone cuando la propuesta anterior se REchazó y la señal
  sigue (el comercial puede aceptar el spam o el follow-up más tarde); una
  propuesta aprobada no se re-propone (ya ejecutada).
- Al aprobar se aplica el efecto: crear la actividad (idempotente por
  marcador ``created_by=agent:<id>`` + título) o marcar el mensaje
  ``dismissed``. El efecto y la decisión viajan en la misma transacción del
  endpoint de aprobación y quedan auditados.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.models.models import (
    Activity,
    ApprovalRequest,
    AuditLog,
    Lead,
    SocialMessage,
    SocialTriage,
)
from sqlalchemy.orm import Session

AGENT_PROPOSAL_PREFIX = "agent_proposal:"
FOLLOW_UP_ACTION = "agent_proposal:create_follow_up"
DISMISS_ACTION = "agent_proposal:dismiss_message"
# T-067: CEO agent — follow-up de leads sin comercial asignado. El efecto
# es idéntico al follow-up del CRM (crear la actividad), pero con
# ``requested_by=ceo_agent`` para que la auditoría distinga quién propuso.
CEO_FOLLOW_UP_ACTION = "agent_proposal:ceo_follow_up"
# T-071: CEO agent — pausar/activar una automatización desde el chat. Al
# aprobarse, la ``ScheduledTask`` cambia de estado (``paused``/``active`` +
# ``next_run_at``) con la misma transacción que la decisión.
AUTOMATION_TOGGLE_ACTION = "agent_proposal:automation_toggle"
# T-075: CEO agent — órdenes de acción por módulo desde el chat: crear un
# lead, mover una oportunidad de etapa, crear una tarea y lanzar/crear una
# campaña. Todas se proponen (deny-by-default) y, al aprobarse (humano o
# autonomía autorizada), aplican la mutación real con la misma transacción.
CEO_CREATE_LEAD_ACTION = "agent_proposal:ceo_create_lead"
CEO_MOVE_OPPORTUNITY_ACTION = "agent_proposal:ceo_move_opportunity"
CEO_CREATE_TASK_ACTION = "agent_proposal:ceo_create_task"
CEO_LAUNCH_CAMPAIGN_ACTION = "agent_proposal:ceo_launch_campaign"
# T-082: CEO agent — omnimódulo. Mismo patrón deny-by-default: se proponen y,
# al aprobarse (humano o autonomía autorizada), aplican la mutación real con
# la misma transacción. ``ceo_assign_lead``, ``ceo_close_opportunity`` y
# ``ceo_adjust_stock`` son seguras y reversibles (entran en la autonomía
# autorizada); ``ceo_update_price`` es financiera: solo bajo umbral.
CEO_ASSIGN_LEAD_ACTION = "agent_proposal:ceo_assign_lead"
CEO_CLOSE_OPPORTUNITY_ACTION = "agent_proposal:ceo_close_opportunity"
CEO_ADJUST_STOCK_ACTION = "agent_proposal:ceo_adjust_stock"
CEO_UPDATE_PRICE_ACTION = "agent_proposal:ceo_update_price"
# T-083: adaptador GoHighLevel — canal de entrada y salida. Mismo patrón
# deny-by-default: el CEO propone (enviar un SMS/email a un lead, crear un
# contacto en GHL) y al aprobarse (humano o autonomía autorizada) el efecto
# se encola en el outbox durable (topic ``ghl.send_message`` /
# ``ghl.create_contact``) en la MISMA transacción que la decisión; la
# entrega la hace el worker con reintentos, circuito y DLQ. Sin GHL
# configurado el mensaje va a la DLQ con motivo claro, nunca se pierde.
GHL_SEND_MESSAGE_ACTION = "agent_proposal:ghl_send_message"
GHL_CREATE_CONTACT_ACTION = "agent_proposal:ghl_create_contact"
GHL_SEND_MESSAGE_TOPIC = "ghl.send_message"
GHL_CREATE_CONTACT_TOPIC = "ghl.create_contact"

_FOLLOW_UP_SLA_MINUTES = 4 * 60  # 4 horas para responder una urgencia social
_URGENT_INTENTS = ("queja", "lead")
_URGENT_URGENCY_MIN = 40


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _proposal_exists(
    db: Session, *, action_type: str, target_key: str
) -> bool:
    """Ya existe una propuesta de este tipo para este objetivo.

    Una propuesta aprobada no se re-propone (su efecto ya está aplicado);
    una rechazada o pendiente tampoco (la decisión del humano prevalece
    hasta que el estado del objetivo cambie de verdad).
    """

    return (
        db.query(ApprovalRequest.id)
        .filter(
            ApprovalRequest.action_type == action_type,
            ApprovalRequest.target_key == target_key,
            ApprovalRequest.status.in_(
                ["pending", "approved"]
            ),
        )
        .first()
        is not None
    )


def _add_proposal(
    db: Session,
    *,
    action_type: str,
    target_key: str,
    payload: dict[str, Any],
    agent_id: str,
) -> ApprovalRequest | None:
    """Inserta la propuesta en un savepoint: un duplicado (unicidad de
    ``ApprovalRequest``) no descarta las propuestas ya flusheadas de la
    misma ronda.
    """

    from sqlalchemy.exc import IntegrityError

    proposal = ApprovalRequest(
        action_type=action_type,
        target_key=target_key,
        payload=payload,
        requested_by=agent_id,
        status="pending",
    )
    try:
        with db.begin_nested():
            db.add(proposal)
            db.flush()
        return proposal
    except IntegrityError:
        return None


def propose_crm_follow_ups(
    db: Session,
    *,
    agent_id: str = "crm_agent",
    now: datetime.datetime | None = None,
) -> list[ApprovalRequest]:
    """Propone follow-ups para leads sociales urgentes fuera de SLA."""

    now = now or _utcnow()
    proposed: list[ApprovalRequest] = []
    urgent_leads = (
        db.query(SocialMessage.lead_id)
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.lead_id.is_not(None),
            SocialTriage.intent.in_(_URGENT_INTENTS),
            SocialTriage.urgency >= _URGENT_URGENCY_MIN,
        )
        .distinct()
        .all()
    )
    for (lead_id,) in urgent_leads:
        if _proposal_exists(
            db, action_type=FOLLOW_UP_ACTION, target_key=lead_id
        ):
            continue
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead is None:
            continue
        # ¿Hay ya un follow-up pendiente no vencido? Si sí, el humano ya
        # está encima: no se propone.
        open_activity = (
            db.query(Activity)
            .filter(
                Activity.lead_id == lead_id,
                Activity.status == "pending",
            )
            .order_by(Activity.created_at.desc())
            .first()
        )
        if open_activity is not None and (
            open_activity.due_at is None or open_activity.due_at > now
        ):
            continue
        latest = (
            db.query(SocialTriage)
            .join(SocialMessage, SocialMessage.id == SocialTriage.message_id)
            .filter(SocialMessage.lead_id == lead_id)
            .order_by(SocialTriage.created_at.desc())
            .first()
        )
        if latest is None:
            continue
        if open_activity is not None:
            context = (
                f"la actividad «{open_activity.title}» venció el "
                f"{open_activity.due_at.isoformat() if open_activity.due_at else '—'}"
            )
        else:
            context = "no hay ninguna actividad de seguimiento"
        rationale = (
            f"Mensaje social triado como «{latest.intent}» (urgencia "
            f"{latest.urgency}, score {latest.score_social}); {context}."
        )
        proposal = _add_proposal(
            db,
            action_type=FOLLOW_UP_ACTION,
            target_key=lead_id,
            payload={
                "agent_id": agent_id,
                "module": "crm",
                "action": "create_follow_up",
                "lead_id": lead_id,
                "title": "Follow-up urgente (SLA social)",
                "kind_activity": "follow_up",
                "due_at": (now + datetime.timedelta(minutes=_FOLLOW_UP_SLA_MINUTES)).isoformat(),
                "rationale": rationale,
            },
            agent_id=agent_id,
        )
        if proposal is not None:
            proposed.append(proposal)
    return proposed


def propose_spam_dismissals(
    db: Session,
    *,
    agent_id: str = "social_agent",
) -> list[ApprovalRequest]:
    """Propone descartar mensajes sociales triados como spam."""

    proposed: list[ApprovalRequest] = []
    spam_messages = (
        db.query(SocialMessage)
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.status == "triaged",
            SocialTriage.intent == "spam",
        )
        .all()
    )
    for message in spam_messages:
        if _proposal_exists(
            db, action_type=DISMISS_ACTION, target_key=message.id
        ):
            continue
        proposal = _add_proposal(
            db,
            action_type=DISMISS_ACTION,
            target_key=message.id,
            payload={
                "agent_id": agent_id,
                "module": "social",
                "action": "dismiss_message",
                "message_id": message.id,
                "sender": (
                    message.sender_name or message.sender_handle or "desconocido"
                ),
                "body_preview": (message.body or "")[:120],
                "rationale": (
                    "Triaje determinista: intención spam (score 0). "
                    "Descartarlo lo saca del inbox de comercial sin borrar "
                    "la evidencia."
                ),
            },
            agent_id=agent_id,
        )
        if proposal is not None:
            proposed.append(proposal)
    return proposed


def run_agent_proposals(db: Session) -> dict[str, Any]:
    """Ejecuta la ronda de propuestas de los agentes por módulo.

    T-068: las propuestas autorizadas por la configuración de autonomía
    (``AgentAutonomy``) se auto-ejecutan al instante y quedan registradas
    como ``AgentDecision``; el resto sigue pendiente de aprobación humana.
    """

    from app.services.autonomy import auto_execute_proposals

    crm = propose_crm_follow_ups(db)
    social = propose_spam_dismissals(db)
    proposals = [*crm, *social]
    result = auto_execute_proposals(db, proposals)
    db.commit()
    return {
        "proposed": len(proposals),
        "auto_executed": len(result["executed"]),
        "deferred": len(result["deferred"]),
        "by_agent": {
            "crm_agent": len(crm),
            "social_agent": len(social),
        },
        "decisions": [
            {
                "id": decision.id,
                "agent_id": decision.agent_id,
                "action_type": decision.action_type,
                "target_key": decision.target_key,
                "deviation": decision.deviation,
            }
            for decision in result["executed"]
        ],
        "proposals": [
            {
                "id": proposal.id,
                "action_type": proposal.action_type,
                "target_key": proposal.target_key,
                "requested_by": proposal.requested_by,
                "status": proposal.status,
                "rationale": (proposal.payload or {}).get("rationale"),
            }
            for proposal in proposals
        ],
    }


def _apply_follow_up(
    db: Session,
    approval: ApprovalRequest,
    payload: dict[str, Any],
    applied: dict[str, Any],
) -> dict[str, Any]:
    """Crea (idempotente) la actividad de follow-up de una propuesta aprobada.

    Compartido por ``crm_agent`` y ``ceo_agent`` (T-067): el efecto es el
    mismo — crear la ``Activity`` pendiente con ``created_by=agent:<id>``.
    """

    lead_id = str(payload.get("lead_id") or approval.target_key)
    title = str(payload.get("title") or "Follow-up (propuesta de agente)")
    existing = (
        db.query(Activity)
        .filter(
            Activity.lead_id == lead_id,
            Activity.title == title,
            Activity.created_by == f"agent:{approval.requested_by}",
            Activity.status == "pending",
        )
        .first()
    )
    if existing is None:
        due_at = payload.get("due_at")
        parsed_due = None
        if isinstance(due_at, str):
            try:
                parsed_due = datetime.datetime.fromisoformat(due_at)
            except ValueError:
                parsed_due = None
        activity = Activity(
            lead_id=lead_id,
            title=title,
            kind="follow_up",
            description=str(payload.get("rationale") or "")[:400],
            due_at=parsed_due,
            status="pending",
            created_by=f"agent:{approval.requested_by}",
        )
        db.add(activity)
        db.flush()
        applied["activity_id"] = activity.id
        # T-068: desviación = se reutilizó una actividad existente (ya había
        # un follow-up pendiente del mismo agente) en vez de crear el nuevo.
        applied["reused"] = False
    else:
        applied["activity_id"] = existing.id
        applied["reused"] = True
    applied["lead_id"] = lead_id
    return applied


def apply_agent_proposal_approved(
    db: Session,
    approval: ApprovalRequest,
    *,
    reviewed_by: str,
    reviewed_at: datetime.datetime,
) -> dict[str, Any]:
    """Aplica el efecto de una propuesta aprobada (misma transacción)."""

    payload = dict(approval.payload or {})
    applied: dict[str, Any] = {"action": payload.get("action")}
    if approval.action_type in (FOLLOW_UP_ACTION, CEO_FOLLOW_UP_ACTION):
        applied = _apply_follow_up(db, approval, payload, applied)
    elif approval.action_type == DISMISS_ACTION:
        message = (
            db.query(SocialMessage)
            .filter(SocialMessage.id == approval.target_key)
            .first()
        )
        if message is not None and message.status != "dismissed":
            message.status = "dismissed"
            db.flush()
            # T-068: desviación = el mensaje ya no estaba en ``triaged``
            # (ya descartado o atendido por otro camino).
            applied["already_dismissed"] = False
        else:
            applied["already_dismissed"] = True
        applied["message_id"] = approval.target_key
    elif approval.action_type == AUTOMATION_TOGGLE_ACTION:
        # T-071: pausar/activar una automatización desde el chat del dueño.
        from app.models.models import ScheduledTask

        task = (
            db.query(ScheduledTask)
            .filter(ScheduledTask.id == approval.target_key)
            .first()
        )
        action = str((approval.payload or {}).get("action") or "")
        if task is None:
            applied["task_found"] = False
        else:
            applied["task_found"] = True
            applied["task_id"] = task.id
            applied["name"] = task.name
            desired = "paused" if action == "pause" else "active"
            if task.status == desired:
                # La tarea ya estaba en el estado pedido (cambio sin efecto).
                applied["already_at_desired_state"] = True
            else:
                applied["already_at_desired_state"] = False
                task.status = desired
                if desired == "active":
                    task.next_run_at = _utcnow() + datetime.timedelta(
                        seconds=int(task.interval_seconds or 3600)
                    )
                else:
                    task.next_run_at = None
                db.flush()
                applied["status"] = desired
    elif approval.action_type == CEO_CREATE_LEAD_ACTION:
        # T-075: crear un lead desde el chat (idempotente por email).
        from app.models.models import Lead

        email = str(payload.get("email") or approval.target_key).strip().lower()
        existing = db.query(Lead).filter(Lead.email == email).first()
        if existing is not None:
            applied["lead_id"] = existing.id
            applied["reused"] = True
            applied["email"] = email
        else:
            lead = Lead(
                email=email,
                first_name=str(payload.get("name") or "Lead vía chat")[:120],
                company_name=str(payload.get("company") or "")[:120] or None,
                source="local",
                status="new",
            )
            db.add(lead)
            db.flush()
            applied["lead_id"] = lead.id
            applied["reused"] = False
            applied["email"] = email
    elif approval.action_type == CEO_MOVE_OPPORTUNITY_ACTION:
        # T-075: mover una oportunidad de etapa (drag&drop auditado).
        from app.models.models import Opportunity

        opportunity = (
            db.query(Opportunity)
            .filter(Opportunity.id == approval.target_key)
            .first()
        )
        stage = str(payload.get("stage") or "")
        if opportunity is None:
            applied["opportunity_found"] = False
        else:
            applied["opportunity_found"] = True
            applied["opportunity_id"] = opportunity.id
            applied["name"] = opportunity.name
            previous = opportunity.stage
            if stage and stage != previous:
                opportunity.stage = stage
                opportunity.stage_changed_at = _utcnow()
                db.flush()
                try:
                    from app.services.crm_webhooks import enqueue_crm_webhooks

                    enqueue_crm_webhooks(
                        db,
                        event_type="pipeline.stage_changed",
                        entity_id=opportunity.id,
                        payload={
                            "opportunity_id": opportunity.id,
                            "lead_id": opportunity.lead_id,
                            "stage_from": previous,
                            "stage_to": stage,
                            "name": opportunity.name,
                            "monetary_value": float(opportunity.monetary_value or 0),
                            "currency": opportunity.currency,
                        },
                        occurrence_id=f"{opportunity.id}:{opportunity.stage_changed_at.isoformat()}",
                    )
                except Exception:
                    # Los webhooks salientes no pueden bloquear el cambio.
                    pass
                applied["stage_from"] = previous
                applied["stage_to"] = stage
                applied["changed"] = True
            else:
                applied["stage_from"] = previous
                applied["stage_to"] = stage
                applied["changed"] = False
    elif approval.action_type == CEO_CREATE_TASK_ACTION:
        # T-075: crear una tarea/recordatorio desde el chat.
        from app.models.models import Activity

        title = str(payload.get("title") or "Tarea desde el chat")[:180]
        lead_id = payload.get("lead_id") or None
        kind = str(payload.get("kind") or "follow_up")
        parsed_due = None
        due_at = payload.get("due_at")
        if isinstance(due_at, str):
            try:
                parsed_due = datetime.datetime.fromisoformat(due_at)
            except ValueError:
                parsed_due = None
        existing = (
            db.query(Activity)
            .filter(
                Activity.lead_id == lead_id,
                Activity.title == title,
                Activity.created_by == f"agent:{approval.requested_by}",
                Activity.status == "pending",
            )
            .first()
        )
        if existing is not None:
            applied["activity_id"] = existing.id
            applied["reused"] = True
        else:
            activity = Activity(
                lead_id=lead_id,
                title=title,
                kind=kind,
                description=str(payload.get("rationale") or "")[:400],
                due_at=parsed_due,
                status="pending",
                created_by=f"agent:{approval.requested_by}",
            )
            db.add(activity)
            db.flush()
            applied["activity_id"] = activity.id
            applied["reused"] = False
        applied["title"] = title
        applied["kind"] = kind
    elif approval.action_type == CEO_LAUNCH_CAMPAIGN_ACTION:
        # T-075: lanzar/crear campaña desde el chat. Si la campaña ya
        # existe se activa (preparada para enviar con su segmento); si no,
        # se crea como borrador listo para configurar — nunca envía sin
        # plantilla y segmento definidos (fail-closed).
        from app.models.models import Campaign, EmailTemplate

        name = str(payload.get("name") or approval.target_key)[:200]
        campaign = db.query(Campaign).filter(Campaign.name == name).first()
        if campaign is None:
            # Plantilla por defecto: la primera activa si existe; si no,
            # queda como borrador que el dueño configura en el portal
            # (fail-closed: nunca se envía sin plantilla y segmento).
            template = (
                db.query(EmailTemplate)
                .filter(EmailTemplate.is_active.is_(True))
                .order_by(EmailTemplate.created_at.asc())
                .first()
            )
            campaign = Campaign(
                name=name,
                description=f"Creada desde el chat del dueño ({approval.requested_by})",
                template_name=template.name if template else "welcome",
                segment={},
                status="draft",
            )
            db.add(campaign)
            db.flush()
            applied["created"] = True
            applied["campaign_id"] = campaign.id
            applied["status"] = campaign.status
        else:
            applied["created"] = False
            applied["campaign_id"] = campaign.id
            if campaign.status != "active":
                campaign.status = "active"
                db.flush()
            applied["status"] = campaign.status
    elif approval.action_type == CEO_ASSIGN_LEAD_ACTION:
        # T-082: asignar un lead a un comercial desde el chat.
        # Import local: ``Lead`` ya es un nombre local de la función por el
        # ``from app.models.models import Lead`` del branch de alta de lead.
        from app.models.models import Lead

        lead = (
            db.query(Lead)
            .filter(Lead.id == approval.target_key)
            .first()
        )
        assignee = str(payload.get("assignee_id") or "")[:120]
        if lead is None:
            applied["lead_found"] = False
        else:
            applied["lead_found"] = True
            applied["lead_id"] = lead.id
            applied["lead_name"] = lead.first_name or lead.email
            applied["assignee"] = assignee
            previous = lead.assigned_to
            if not assignee or previous == assignee:
                applied["changed"] = False
            else:
                applied["changed"] = True
                applied["assigned_from"] = previous
                lead.assigned_to = assignee
                db.flush()
    elif approval.action_type == CEO_CLOSE_OPPORTUNITY_ACTION:
        # T-082: cerrar una oportunidad como ganada/perdida desde el chat.
        from app.models.models import Opportunity

        opportunity = (
            db.query(Opportunity)
            .filter(Opportunity.id == approval.target_key)
            .first()
        )
        outcome = str(payload.get("outcome") or "")
        if opportunity is None:
            applied["opportunity_found"] = False
        else:
            applied["opportunity_found"] = True
            applied["opportunity_id"] = opportunity.id
            applied["name"] = opportunity.name
            applied["outcome"] = outcome
            desired_stage = "won" if outcome == "won" else "lost"
            if opportunity.stage == desired_stage and opportunity.status == "closed":
                applied["changed"] = False
            else:
                applied["changed"] = True
                applied["stage_from"] = opportunity.stage
                opportunity.stage = desired_stage
                opportunity.status = "closed"
                opportunity.stage_changed_at = _utcnow()
                if outcome == "won":
                    opportunity.won_at = _utcnow()
                else:
                    opportunity.lost_at = _utcnow()
                    reason = str(payload.get("lost_reason") or "").strip()
                    if reason:
                        opportunity.lost_reason = reason[:500]
                db.flush()
    elif approval.action_type == CEO_ADJUST_STOCK_ACTION:
        # T-082: ajuste manual de stock desde el chat (idempotente; nunca
        # deja el stock por debajo de lo reservado).
        from app.models.models import Product

        product = (
            db.query(Product)
            .filter(Product.id == approval.target_key)
            .first()
        )
        try:
            new_stock = max(0, int(payload.get("new_stock") or 0))
        except (TypeError, ValueError):
            new_stock = 0
        if product is None:
            applied["product_found"] = False
        else:
            applied["product_found"] = True
            applied["product_id"] = product.id
            applied["sku"] = product.sku
            applied["name"] = product.name
            applied["previous_stock"] = int(product.stock_quantity)
            reserved = int(product.reserved_stock or 0)
            if new_stock < reserved:
                applied["adjusted"] = False
                applied["reason"] = (
                    f"No se puede bajar de {reserved} uds: hay {reserved} "
                    "reservadas para pedidos."
                )
            elif new_stock == int(product.stock_quantity):
                applied["adjusted"] = False
                applied["reason"] = "El stock ya estaba en ese valor."
            else:
                applied["adjusted"] = True
                applied["new_stock"] = new_stock
                product.stock_quantity = new_stock
                db.flush()
    elif approval.action_type == GHL_SEND_MESSAGE_ACTION:
        # T-083: enviar un SMS/email a un lead vía GHL. El efecto es encolar
        # el mensaje en el outbox durable (misma transacción que la
        # decisión); la entrega real la hace el worker con reintentos y DLQ.
        from app.services.outbox import OutboxService

        lead_id = str(payload.get("lead_id") or "").strip()
        channel = str(payload.get("channel") or "").strip()
        content = str(payload.get("content") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        if not lead_id or not channel or not content:
            applied["queued"] = False
            applied["reason"] = "missing_lead_channel_content"
        else:
            outbox = OutboxService(db)
            message, created = outbox.enqueue(
                topic=GHL_SEND_MESSAGE_TOPIC,
                idempotency_key=f"ghl-send:{approval.id}",
                payload={
                    "lead_id": lead_id,
                    "lead_name": str(payload.get("lead_name") or "")[:120],
                    "email": email,
                    "phone": payload.get("phone"),
                    "channel": channel,
                    "subject": str(payload.get("subject") or "")[:200]
                    or (content[:80] if channel == "email" else ""),
                    "content": content[:4000],
                },
                commit=False,
            )
            # El id se genera en el INSERT: flushear antes de registrarlo en
            # la decisión (misma transacción, sin commit).
            db.flush()
            applied["queued"] = True
            applied["outbox_id"] = message.id
            applied["created"] = created
            applied["channel"] = channel
            applied["lead_id"] = lead_id
    elif approval.action_type == GHL_CREATE_CONTACT_ACTION:
        # T-083: crear (upsert) un contacto en GHL. El efecto se encola en
        # el outbox durable; el worker hace el upsert (idempotente por email
        # en GHL) con reintentos y DLQ.
        from app.services.outbox import OutboxService

        email = str(payload.get("email") or "").strip().lower()
        if not email:
            applied["queued"] = False
            applied["reason"] = "missing_email"
        else:
            outbox = OutboxService(db)
            message, created = outbox.enqueue(
                topic=GHL_CREATE_CONTACT_TOPIC,
                idempotency_key=f"ghl-contact:{approval.id}",
                payload={
                    "email": email,
                    "first_name": str(payload.get("first_name") or "")[:120],
                    "phone": payload.get("phone"),
                    "company_name": payload.get("company_name"),
                    "lead_id": payload.get("lead_id"),
                },
                commit=False,
            )
            db.flush()
            applied["queued"] = True
            applied["outbox_id"] = message.id
            applied["created"] = created
            applied["email"] = email
    elif approval.action_type == CEO_UPDATE_PRICE_ACTION:
        # T-082: actualizar el precio de un producto desde el chat
        # (financiero: solo se auto-ejecuta bajo el umbral de autonomía;
        # fuera de él, aprueba el humano).
        from app.models.models import Product

        product = (
            db.query(Product)
            .filter(Product.id == approval.target_key)
            .first()
        )
        try:
            new_price = max(0.0, float(payload.get("new_price") or 0))
        except (TypeError, ValueError):
            new_price = 0.0
        if product is None:
            applied["product_found"] = False
        else:
            applied["product_found"] = True
            applied["product_id"] = product.id
            applied["sku"] = product.sku
            applied["name"] = product.name
            applied["previous_price"] = float(product.base_price)
            applied["new_price"] = new_price
            if abs(float(product.base_price) - new_price) < 0.0001:
                applied["changed"] = False
            else:
                applied["changed"] = True
                product.base_price = new_price
                db.flush()
    db.add(
        AuditLog(
            installation_id=approval.installation_id,
            agent_id=str(approval.requested_by or "agent"),
            user_id=None,
            event_type="agent_proposal.executed",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={
                "approval_id": approval.id,
                "action_type": approval.action_type,
                "target_key": approval.target_key,
                "reviewed_by": reviewed_by,
                **applied,
            },
        )
    )
    return applied
