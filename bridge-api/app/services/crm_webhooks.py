"""Webhooks salientes de eventos CRM (P2-f, T-044).

Sobre el outbox durable y la firma HMAC ya existentes
(``automations.send_webhook`` / ``_assert_outbound_url_allowed``), este módulo
añade las suscripciones por evento:

- ``WEBHOOK_EVENT_CATALOG``: catálogo estable de eventos CRM que pueden
  suscribirse (``lead.created``, ``lead.assigned``,
  ``pipeline.stage_changed``, ``quote.confirmed``).
- ``validate_webhook_url``: validación barata en CRUD (esquema, host presente
  y literales de red privada/loopback) SIN resolución DNS — la resolución y
  el bloqueo real por IP se hacen en el dispatcher con
  ``_assert_outbound_url_allowed``, que es donde hay conexión.
- ``enqueue_crm_webhooks``: al producirse un evento, encola por el outbox un
  mensaje por suscripción activa (topic ``crm.webhook``) con
  ``commit=False``: el mensaje viaja en la MISMA transacción que la mutación
  que lo origina (patrón transactional outbox) — si la mutación revierte, el
  mensaje se descarta con ella.
- ``dispatch_crm_webhook``: dispatcher del worker. Resuelve la suscripción,
  re-valida SSRF con DNS, firma el payload con el secreto DE LA SUSCRIPCIÓN
  y lo envía con reintentos acotados. Una suscripción desactivada o eliminada
  omite el envío de forma auditable (nunca se envía a una URL que el
  propietario deshabilitó); una URL bloqueada por SSRF es un error permanente
  (dead-letter), no un reintento.

Hermeticidad: los evals inyectan un dispatcher falso o verifican el enqueue
sin tocar red; el envío real solo ocurre en el worker de producción o en la
validación en vivo contra el stack candidato.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import OutboxMessage, WebhookSubscription
from app.services.automations import (
    _assert_outbound_url_allowed,
    guarded_request_with_retry,  # re-export para el dispatcher
    sign_webhook_payload,
)
from app.services.outbox import OutboxPermanentError, OutboxService, OutboxTransientError

_LOG = logging.getLogger("bridge.crm_webhooks")

# Topic del outbox para entregas de webhook CRM.
CRM_WEBHOOK_TOPIC = "crm.webhook"

# Catálogo estable de eventos suscribibles. No añadir eventos aquí sin
# enganchar también el dispatch en el punto de mutación correspondiente.
WEBHOOK_EVENT_CATALOG: list[dict[str, str]] = [
    {
        "key": "lead.created",
        "label": "Lead creado",
        "description": "Se crea un lead local (alta manual, importación o chat).",
    },
    {
        "key": "lead.assigned",
        "label": "Lead asignado",
        "description": "Un operador asigna (o desasigna) un lead a un comercial.",
    },
    {
        "key": "pipeline.stage_changed",
        "label": "Cambio de etapa",
        "description": "Una oportunidad cambia de etapa en el kanban.",
    },
    {
        "key": "quote.confirmed",
        "label": "Presupuesto confirmado",
        "description": "Se confirma un presupuesto: se crea el pedido y la factura.",
    },
    {
        "key": "opportunity.closed",
        "label": "Oportunidad cerrada",
        "description": "Una oportunidad se cierra ganada o perdida, con motivo de pérdida.",
    },
    {
        "key": "social.message_triaged",
        "label": "Mensaje social triado",
        "description": "Un mensaje social (WhatsApp/genérico) se tria y se convierte en lead.",
    },
]

WEBHOOK_EVENT_KEYS: frozenset[str] = frozenset(
    event["key"] for event in WEBHOOK_EVENT_CATALOG
)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def validate_webhook_url(url: str) -> None:
    """Valida una URL de destino en CRUD (sin DNS, para no depender de red).

    Comprueba esquema http/https, host presente y bloquea literales de red
    privada, loopback, link-local y multicast. La defensa SSRF completa
    (resolución DNS + bloqueo de IPs) ocurre en el dispatcher vía
    ``_assert_outbound_url_allowed`` justo antes de abrir la conexión; un
    hostname válido aquí puede fallar allí si resuelve a una IP bloqueada.
    """

    import ipaddress
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"webhook_scheme_not_allowed:{parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("webhook_host_missing")
    # Allowlist explícita (misma política que el dispatcher) tiene prioridad.
    allowed_hosts = {
        h.strip().lower()
        for h in (settings.WEBHOOK_OUTBOUND_ALLOWED_HOSTS or "").split(",")
        if h.strip()
    }
    if host in allowed_hosts:
        return
    # Solo literales de IP se evalúan aquí (sin resolución DNS).
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        return  # hostname: la validación DNS real ocurre en el dispatcher
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        raise ValueError(f"webhook_private_network_blocked:{host}->{host}")


def _subscription_response(subscription: WebhookSubscription) -> dict[str, Any]:
    """Forma de API de una suscripción (el secreto NUNCA se devuelve)."""

    return {
        "id": subscription.id,
        "name": subscription.name,
        "url": subscription.url,
        "events": list(subscription.events or []),
        "is_active": subscription.is_active,
        "secret_set": bool(subscription.secret),
        "secret_prefix": subscription.secret[:4] if subscription.secret else "",
        "created_by": subscription.created_by,
        "created_at": subscription.created_at.isoformat()
        if subscription.created_at
        else None,
        "updated_at": subscription.updated_at.isoformat()
        if subscription.updated_at
        else None,
    }


def enqueue_crm_webhooks(
    db: Session,
    *,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any],
    occurrence_id: str,
) -> list[dict[str, Any]]:
    """Encola una entrega por suscripción activa del evento (atómico).

    El mensaje se añade con ``commit=False``: viaja en la transacción abierta
    del caller (la de la mutación que produce el evento). Si el caller
    revierte, el mensaje se descarta; si confirma, se confirma junto con la
    mutación — nunca un webhook para un efecto que no llegó a persistir.

    Devuelve el resumen de mensajes encolados (id + creado).
    """

    subscriptions = (
        db.query(WebhookSubscription)
        .filter(
            WebhookSubscription.is_active.is_(True),
        )
        .all()
    )
    queued: list[dict[str, Any]] = []
    outbox = OutboxService(db)
    for subscription in subscriptions:
        events = subscription.events or []
        if event_type not in events:
            continue
        message, created = outbox.enqueue(
            topic=CRM_WEBHOOK_TOPIC,
            idempotency_key=(
                f"crm-webhook:{subscription.id}:{event_type}:{occurrence_id}"
            ),
            payload={
                "subscription_id": subscription.id,
                "event_type": event_type,
                "entity_id": entity_id,
                "occurrence_id": occurrence_id,
                "data": payload,
            },
            commit=False,
        )
        queued.append({"outbox_id": message.id, "created": created})
    return queued


def _webhook_body(*, event_type: str, occurrence_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Cuerpo canónico del webhook (timestamp añadido en el envío)."""

    return {
        "event_type": event_type,
        "occurrence_id": occurrence_id,
        "data": data,
    }


async def _send_signed_webhook(
    *,
    url: str,
    payload: dict[str, Any],
    secret: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Envía un webhook firmado con el secreto de la suscripción.

    Reutiliza la defensa SSRF (``_assert_outbound_url_allowed``) y el cliente
    con reintentos acotados (``guarded_request_with_retry``) del pipeline
    existente. Devuelve el mismo contrato que ``automations.send_webhook``.
    """

    body = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    try:
        _assert_outbound_url_allowed(url)
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "rejected",
            "idempotency_key": idempotency_key,
            "error": str(exc),
            "accepted": False,
        }
    timestamp = str(int(_utcnow().timestamp()))
    signature = sign_webhook_payload(body, secret)
    try:
        response = await guarded_request_with_retry(
            "webhook",
            lambda: httpx.AsyncClient(timeout=20).request(
                "POST",
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bridge-Webhook-Id": idempotency_key,
                    "X-Bridge-Webhook-Signature": f"sha256={signature}",
                    "X-Bridge-Webhook-Key-Id": "subscription",
                    "X-Bridge-Webhook-Timestamp": timestamp,
                },
            ),
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — contrato de envío sin excepción
        return {
            "status": "failed",
            "idempotency_key": idempotency_key,
            "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            "accepted": False,
        }
    return {
        "status": "sent",
        "idempotency_key": idempotency_key,
        "signature": f"sha256={signature}",
        "key_id": "subscription",
        "timestamp": timestamp,
        "accepted": True,
    }


async def dispatch_crm_webhook(message: OutboxMessage) -> dict[str, Any]:
    """Dispatcher del outbox (topic ``crm.webhook``) para el worker durable.

    - Suscripción desactivada o eliminada → omite el envío con motivo
      registrado en ``response_body`` (auditable, nunca se envía a una URL
      deshabilitada).
    - URL bloqueada por SSRF / esquema inválido → ``OutboxPermanentError``
      (dead-letter inmediata: no tiene sentido reintentar una URL prohibida).
    - Error de red/HTTP → ``OutboxTransientError`` (reintento con backoff).
    """

    from sqlalchemy.orm import object_session

    session = object_session(message)
    if session is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    subscription_id = str(payload.get("subscription_id") or "")
    if not subscription_id:
        raise OutboxPermanentError("crm_webhook_missing_subscription_id")
    subscription = (
        session.query(WebhookSubscription)
        .filter(WebhookSubscription.id == subscription_id)
        .first()
    )
    if subscription is None:
        return {
            "status": "skipped",
            "reason": "subscription_gone",
            "subscription_id": subscription_id,
        }
    if not subscription.is_active:
        return {
            "status": "skipped",
            "reason": "subscription_inactive",
            "subscription_id": subscription_id,
        }
    body = _webhook_body(
        event_type=str(payload.get("event_type") or ""),
        occurrence_id=str(payload.get("occurrence_id") or ""),
        data=dict(payload.get("data") or {}),
    )
    result = await _send_signed_webhook(
        url=subscription.url,
        payload=body,
        secret=subscription.secret,
        idempotency_key=message.idempotency_key,
    )
    if result.get("accepted") is True:
        return result
    # Distinguir rechazo permanente (SSRF/validación) de fallo transitorio.
    error = str(result.get("error") or "")
    if result.get("status") == "rejected" or "webhook_" in error:
        raise OutboxPermanentError(error or "webhook_rejected")
    raise OutboxTransientError(error or "webhook_failed")
