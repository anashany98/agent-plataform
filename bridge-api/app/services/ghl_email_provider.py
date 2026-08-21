"""Proveedor de email real vía GoHighLevel (T-083).

Se activa con ``EMAIL_PROVIDER=ghl``: entrega el correo por la API de
mensajes de GHL (``POST /contacts/{contactId}/messages`` con ``type=email``)
resolviendo antes el contacto con ``upsert_contact`` (idempotente por email
en GHL). Nunca afirma entrega si el contacto no se resuelve o el envío falla:
devuelve ``accepted=False`` con el error tipado para que ``send_email``
decida la degradación controlada y lo audite.

El tracking de apertura/clic del portal funciona igual que con SMTP: el HTML
que recibe el proveedor ya lleva el pixel y los enlaces reescritos
(``send_templated_email``), y GHL lo entrega tal cual — los eventos los
registran los endpoints públicos del Bridge.

El adaptador GHL es async y el contrato de proveedores de email es sync: el
módulo puentea con ``_run_async`` (``asyncio.run`` si no hay loop en el hilo
— caso de los endpoints sync y del worker de tareas programadas que corre
los autómats en ``to_thread`` — y un hilo dedicado con su propio loop si ya
hay un loop corriendo, p. ej. un endpoint async).

El módulo se importa de forma perezosa desde ``automations.send_email`` para
no acoplar el arranque del Bridge al adaptador GHL.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from app.services.automations import EmailResult
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError


def _run_async(coro: Any) -> Any:
    """Ejecuta una corrutina en este hilo (sin loop) o en un hilo dedicado
    si ya hay un event loop corriendo (evita «Cannot run the event loop
    while another loop is running»)."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {"value": None, "error": None}

    def _runner() -> None:
        try:
            result["value"] = asyncio.new_event_loop().run_until_complete(coro)
        except Exception as exc:  # noqa: BLE001 — el error se propaga al caller
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


class GhlEmailProvider:
    """Envía correo real vía GoHighLevel; errores cerrados, sin éxito fingido."""

    name = "ghl"

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
        html: str | None = None,
        tracking_token: str | None = None,
    ) -> EmailResult:
        reference = f"ghl:{uuid.uuid4().hex[:12]}"
        email = (to or "").strip().lower()
        if not email:
            return EmailResult(
                "ghl",
                to,
                subject,
                False,
                reference,
                error="ghl_email_missing_recipient",
                status="failed",
            )
        adapter = GHLAdapter()
        if not adapter.configured():
            return EmailResult(
                "ghl",
                to,
                subject,
                False,
                reference,
                error="ghl_not_configured",
                status="failed",
            )
        try:
            contact_response = _run_async(
                adapter.upsert_contact(email=email, first_name="")
            )
            contact = contact_response.get("contact") or contact_response
            contact_id = str(contact.get("id") or "")
            if not contact_id:
                raise GHLIntegrationError(
                    "GHL no devolvió un ID de contacto para el envío"
                )
            _run_async(
                adapter.send_email(
                    contact_id=contact_id,
                    subject=subject,
                    content=body,
                    html=html,
                )
            )
        except Exception as exc:
            # Aceptar=False: el orquestador trata el envío como fallido y
            # decide la degradación (spool local auditado) o el escalado.
            return EmailResult(
                "ghl",
                to,
                subject,
                False,
                reference,
                error=f"ghl_error:{type(exc).__name__}:{str(exc)[:200]}",
                status="failed",
            )
        return EmailResult(
            "ghl",
            to,
            subject,
            True,
            reference,
            error=None,
            status="sent",
        )
