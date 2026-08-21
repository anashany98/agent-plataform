"""Adaptadores de canales sociales (Fase 1, propuesta T-056).

Cada canal implementa tres operaciones sobre un ``SocialChannel``:

- ``verify_get(channel, params) -> str | None``: verifica el *challenge* de
  suscripción (WhatsApp/Meta lo exige por GET antes de entregar webhooks).
  Devuelve el ``challenge`` si es válido, ``None`` en caso contrario.
- ``verify_post(channel, raw_body, headers) -> bool``: valida la firma HMAC
  del cuerpo crudo (nunca del JSON re-serializado).
- ``parse(body) -> SocialEnvelope``: normaliza el payload del canal al
  contrato interno (``source_message_id`` es la clave de dedupe).

Hermeticidad D-032: los adaptadores son puros (sin red, sin estado global);
la firma se verifica con constant-time compare. Un canal desconocido falla
cerrado en ``get_adapter``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Any

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,17}\d)")


@dataclass
class SocialEnvelope:
    """Contrato interno normalizado de un mensaje social entrante."""

    source_message_id: str
    body: str
    sender_handle: str | None = None
    sender_name: str | None = None
    email: str | None = None
    phone: str | None = None
    media_urls: list[str] = field(default_factory=list)
    thread_id: str | None = None


def _hmac_hexdigest(raw_body: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


class GenericSocialAdapter:
    """Adaptador genérico: webhook JSON + firma ``X-Bridge-Signature``.

    Pensado para integraciones ligeras (Zapier/Make/scripts) y para los
    tests herméticos. El webhook espera:

    .. code-block:: json

        {
          "source_message_id": "…",
          "body": "hola, ¿presupuesto?",
          "sender_handle": "ana",
          "sender_name": "Ana",
          "email": "ana@…",
          "phone": "+34…",
          "media_urls": []
        }

    El challenge por GET acepta ``?verify_token=<token>&challenge=<x>`` y
    devuelve ``x`` si el token coincide.
    """

    name = "generic"

    def verify_get(self, channel, params: dict[str, str]) -> str | None:
        expected = (channel.verify_token or "").strip()
        provided = str(params.get("verify_token") or "").strip()
        if expected and hmac.compare_digest(provided, expected):
            return str(params.get("challenge") or "")
        return None

    def verify_post(
        self, channel, raw_body: bytes, headers: dict[str, str]
    ) -> bool:
        supplied = str(headers.get("x-bridge-signature") or "").strip()
        if not supplied:
            return False
        return hmac.compare_digest(
            supplied, _hmac_hexdigest(raw_body, channel.webhook_secret)
        )

    def parse(self, body: dict[str, Any]) -> SocialEnvelope:
        source_message_id = str(body.get("source_message_id") or "").strip()
        text = str(body.get("body") or "").strip()
        if not source_message_id or not text:
            raise ValueError("social_envelope_missing_fields")
        email = _extract_email(text) or (body.get("email") or None)
        phone = _extract_phone(text) or (body.get("phone") or None)
        return SocialEnvelope(
            source_message_id=source_message_id,
            body=text,
            sender_handle=body.get("sender_handle") or None,
            sender_name=body.get("sender_name") or None,
            email=str(email).strip() if email else None,
            phone=str(phone).strip() if phone else None,
            media_urls=list(body.get("media_urls") or []),
            thread_id=body.get("thread_id") or None,
        )


class WhatsAppSocialAdapter:
    """Adaptador de WhatsApp Business Cloud API (Meta).

    - GET: verificación de suscripción con ``hub.mode/hub.verify_token/
      hub.challenge`` (Meta exige responder el challenge antes de entregar).
    - POST: firma ``X-Hub-Signature-256: sha256=<hex>`` sobre el cuerpo crudo.
    - Parse: ``entry[].changes[].value.messages[]`` (texto; el resto de tipos
      de mensaje se descartan salvo el texto plano).

    El inbound en ventana de servicio de 24 h no tiene coste de plantilla;
    este adaptador solo recibe, nunca envía (las respuestas van por el portal
    en v1).
    """

    name = "whatsapp"

    def verify_get(self, channel, params: dict[str, str]) -> str | None:
        mode = str(params.get("hub.mode") or "")
        if mode != "subscribe":
            return None
        expected = (channel.verify_token or "").strip()
        provided = str(params.get("hub.verify_token") or "").strip()
        if not expected or not hmac.compare_digest(provided, expected):
            return None
        return str(params.get("hub.challenge") or "")

    def verify_post(
        self, channel, raw_body: bytes, headers: dict[str, str]
    ) -> bool:
        supplied = str(headers.get("x-hub-signature-256") or "").strip()
        if not supplied.startswith("sha256="):
            return False
        supplied_hex = supplied[len("sha256=") :].strip()
        return hmac.compare_digest(
            supplied_hex, _hmac_hexdigest(raw_body, channel.webhook_secret)
        )

    def parse(self, body: dict[str, Any]) -> SocialEnvelope:
        entries = body.get("entry") or []
        for entry in entries:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                contacts = value.get("contacts") or []
                sender_name = None
                if contacts:
                    profile = contacts[0].get("profile") or {}
                    sender_name = profile.get("name") or None
                messages = value.get("messages") or []
                for message in messages:
                    message_type = message.get("type")
                    if message_type != "text":
                        continue
                    text = ((message.get("text") or {}).get("body") or "").strip()
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or not text:
                        continue
                    sender = str(message.get("from") or "").strip()
                    return SocialEnvelope(
                        source_message_id=message_id,
                        body=text,
                        sender_handle=sender or None,
                        sender_name=sender_name,
                        phone=sender or None,
                        thread_id=value.get("phone_number_id") or None,
                    )
        raise ValueError("social_whatsapp_no_text_message")


ADAPTERS: dict[str, Any] = {
    "generic": GenericSocialAdapter(),
    "whatsapp": WhatsAppSocialAdapter(),
}

SOCIAL_CHANNEL_TYPES = {"generic", "whatsapp"}


def get_adapter(channel_type: str) -> Any:
    """Devuelve el adaptador del canal (fail-closed si es desconocido)."""

    adapter = ADAPTERS.get((channel_type or "").strip().lower())
    if adapter is None:
        raise ValueError(f"social_channel_unknown:{channel_type}")
    return adapter


def _extract_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def _extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    return match.group(1).strip() if match else None


def webhook_verify(
    channel, channel_type: str, raw_body: bytes, headers: dict[str, str]
) -> bool:
    """Verifica la firma del POST para el tipo de canal (fail-closed)."""

    return get_adapter(channel_type).verify_post(channel, raw_body, headers)


def parse_webhook(channel_type: str, body: dict[str, Any]) -> SocialEnvelope:
    """Normaliza el payload del canal al contrato interno."""

    return get_adapter(channel_type).parse(body)


def parse_json_body(raw: bytes) -> dict[str, Any]:
    """Decodifica el JSON del cuerpo con fallo controlado."""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("social_json_invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("social_json_object_expected")
    return parsed
