"""Superficie de mando del dueño por email/WhatsApp (T-069).

El propietario consulta y da órdenes a los agentes desde el canal que ya
usa — sin abrir el portal — reutilizando dos piezas existentes:

- **Email**: un webhook entrante (``POST /commands/email/webhook``) entrega
  el correo del dueño; la intención se resuelve con el CEO agent
  (``ceo_agent.ceo_chat``, memoria de conversación incluida) y la respuesta
  se envía de vuelta por ``automations.send_email`` → SMTP real o spool
  local con degradación auditada (nunca pérdida silenciosa).
- **WhatsApp**: en el webhook de escucha social, si el remitente es el
  número del dueño, el mensaje NO entra al triaje comercial: se resuelve
  con el CEO agent y la respuesta se registra como mensaje saliente
  (``direction="out"``) en el mismo canal, visible en el inbox.

Seguridad (fail-closed):

- Identidad configurada por instalación (``OWNER_COMMAND_EMAIL`` y
  ``OWNER_COMMAND_PHONE``). Vacía → la superficie está desactivada.
- Remitente distinto del configurado → nada se responde: se audita
  ``ceo_command.<canal>.ignored`` (motivo ``unknown_sender``) y el mensaje
  se descarta de forma silenciosa (WhatsApp) o se ignora (email).
- El webhook de email exige firma HMAC; el de WhatsApp reutiliza la firma
  del canal (Meta X-Hub-Signature-256).

Cada comando atendido se audita como ``ceo_command.email`` /
``ceo_command.whatsapp`` con la intención resuelta, el proveedor y el
identificador de la respuesta, además de la auditoría propia del CEO chat.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.config import settings
from app.models.models import AuditLog, SocialMessage, SocialTriage
from sqlalchemy.orm import Session


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _installation_id(db: Session) -> str:
    from app.installation_context import get_current_installation_id

    return get_current_installation_id() or "unknown"


def _owner_email() -> str:
    return (settings.OWNER_COMMAND_EMAIL or "").strip().lower()


def _owner_phone() -> str:
    return (settings.OWNER_COMMAND_PHONE or "").strip()


def _normalize_phone(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def owner_command_email_enabled() -> bool:
    return bool(_owner_email())


def owner_command_whatsapp_enabled() -> bool:
    return bool(_owner_phone())


def _audit_command(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            installation_id=_installation_id(db),
            agent_id="ceo_agent",
            user_id=None,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )


async def handle_owner_email(
    db: Session,
    *,
    sender: str,
    subject: str,
    body: str,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Procesa un correo del dueño: CEO chat + respuesta por el spool/SMTP.

    ``sender`` debe coincidir exactamente (case-insensitive) con
    ``OWNER_COMMAND_EMAIL``; en caso contrario se ignora de forma auditada y
    nunca se responde (no revela la existencia del asistente).
    """

    normalized_sender = (sender or "").strip().lower()
    owner = _owner_email()
    if not owner or normalized_sender != owner:
        _audit_command(
            db,
            event_type="ceo_command.email.ignored",
            status_value="ignored",
            details={
                "reason": "unknown_sender" if owner else "surface_disabled",
                "sender": normalized_sender,
                "subject": (subject or "")[:200],
            },
        )
        db.commit()
        return {"handled": False, "reason": "unknown_sender" if owner else "surface_disabled"}

    subject_text = (subject or "").strip()
    body_text = (body or "").strip()
    message = subject_text
    if body_text and body_text not in subject_text:
        message = f"{subject_text}\n{body_text}" if subject_text else body_text
    message = message.strip() or "hola"

    # T-074: responder al digest con «REVERTIR <id>» anula la decisión con
    # la misma trazabilidad que el portal (determinista, sin pasar por el
    # LLM). Si el id no existe o ya está revertida, se explica en la
    # respuesta; nunca se borra evidencia.
    from app.services import daily_digest

    decision_id = daily_digest.parse_revert_command(message)
    if decision_id is not None:
        revert = daily_digest.revert_from_email(
            db,
            decision_id=decision_id,
            sender=normalized_sender,
        )
        from app.services import automations

        result = automations.send_email(
            db,
            to=owner,
            subject=f"Re: {subject_text[:80]}" if subject_text else "Confirmación de revert",
            body=revert["message"],
            actor="agent:finance_agent",
        )
        _audit_command(
            db,
            event_type="ceo_command.email.revert",
            status_value=revert["status"],
            details={
                "sender": normalized_sender,
                "subject": subject_text[:200],
                "decision_id": decision_id,
                "reply_ref": result.reference,
                "reply_accepted": bool(result.accepted),
            },
        )
        db.commit()
        return {
            "handled": True,
            "intent": "revert_decision",
            "intent_label": "revertir decisión desde el digest",
            "revert_status": revert["status"],
            "reply_accepted": bool(result.accepted),
            "reply_ref": result.reference,
            "reply_provider": result.provider,
        }

    conversation_id = f"email-{owner}"
    response = await _ceo_chat(
        db,
        message=message,
        conversation_id=conversation_id,
        provider_id=provider_id,
    )
    answer = response["answer"]
    reply_subject = (
        f"Re: {subject_text[:80]}" if subject_text else "Respuesta de tu asistente de dirección"
    )
    from app.services import automations

    result = automations.send_email(
        db,
        to=owner,
        subject=reply_subject[:200],
        body=answer,
        actor="agent:ceo_agent",
    )
    _audit_command(
        db,
        event_type="ceo_command.email",
        status_value="success",
        details={
            "sender": normalized_sender,
            "subject": subject_text[:200],
            "intent": response["intent"],
            "intent_label": response["intent_label"],
            "provider": response["provider"],
            "conversation_id": conversation_id,
            "reply_ref": result.reference,
            "reply_accepted": bool(result.accepted),
            "reply_provider": result.provider,
        },
    )
    db.commit()
    return {
        "handled": True,
        "intent": response["intent"],
        "intent_label": response["intent_label"],
        "reply_accepted": bool(result.accepted),
        "reply_ref": result.reference,
        "reply_provider": result.provider,
        "conversation_id": conversation_id,
    }


async def handle_owner_whatsapp(
    db: Session,
    *,
    channel_id: str,
    message: SocialMessage,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Procesa un WhatsApp del dueño: CEO chat + respuesta outbound.

    ``message`` es el ``SocialMessage`` entrante ya persistido. El número
    debe coincidir con ``OWNER_COMMAND_PHONE`` (normalizado, dígitos);
    si no, el mensaje se descarta (``dismissed``) de forma auditada y nunca
    se responde. La respuesta se registra como mensaje saliente en el mismo
    canal y el entrante se marca ``triaged`` con intención ``command`` para
    que no entre en la cola comercial.
    """

    sender_digits = _normalize_phone(message.phone or message.sender_handle or "")
    owner_digits = _normalize_phone(_owner_phone())
    if not owner_digits or sender_digits != owner_digits:
        _audit_command(
            db,
            event_type="ceo_command.whatsapp.ignored",
            status_value="ignored",
            details={
                "reason": "unknown_sender" if owner_digits else "surface_disabled",
                "sender_handle": message.sender_handle,
                "sender_phone": message.phone,
                "message_id": message.id,
            },
        )
        message.status = "dismissed"
        db.commit()
        return {
            "handled": False,
            "reason": "unknown_sender" if owner_digits else "surface_disabled",
        }

    message_text = (message.body or "").strip() or "hola"
    conversation_id = f"whatsapp-{owner_digits}"
    response = await _ceo_chat(
        db,
        message=message_text,
        conversation_id=conversation_id,
        provider_id=provider_id,
    )
    answer = response["answer"]
    reply = SocialMessage(
        channel_id=channel_id,
        thread_id=message.thread_id,
        source_message_id=f"out-{message.source_message_id or message.id}",
        direction="out",
        sender_handle=message.sender_handle,
        sender_name=message.sender_name,
        phone=message.phone,
        body=answer,
        media_urls=[],
        status="triaged",
    )
    db.add(reply)
    db.flush()
    message.status = "triaged"
    db.add(
        SocialTriage(
            message_id=message.id,
            intent="command",
            language="es",
            register="formal",
            urgency=0,
            score_social=0,
            summary="Comando del dueño resuelto por el CEO agent",
            decided_by="deterministic",
        )
    )
    _audit_command(
        db,
        event_type="ceo_command.whatsapp",
        status_value="success",
        details={
            "message_id": message.id,
            "sender_phone": message.phone,
            "intent": response["intent"],
            "intent_label": response["intent_label"],
            "provider": response["provider"],
            "conversation_id": conversation_id,
            "reply_message_id": reply.id,
        },
    )
    db.commit()
    return {
        "handled": True,
        "intent": response["intent"],
        "intent_label": response["intent_label"],
        "reply_message_id": reply.id,
        "conversation_id": conversation_id,
    }


async def _ceo_chat(
    db: Session,
    *,
    message: str,
    conversation_id: str,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Resuelve el mensaje con el CEO agent (misma memoria por canal)."""

    from app.services import ceo_agent

    return await ceo_agent.ceo_chat(
        db,
        message=message,
        conversation_id=conversation_id,
        username="owner",
        user_id=None,
    )
