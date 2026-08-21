"""Proveedor SMTP real para el router de email de automatizaciones (D-012).

Se activa con ``EMAIL_PROVIDER=smtp``: envía por SMTP con STARTTLS (por
defecto, puerto 587) o SSL directo (``SMTP_SSL=true``, p. ej. puerto 465).
Nunca afirma entrega si la conexión, autenticación o ``send_message`` falla:
devuelve ``accepted=False`` con el error tipado para que ``send_email`` decida
la degradación controlada al spool local (entrega manual) y lo audite.

El módulo se importa de forma perezosa desde ``automations.send_email`` para
no acoplar el arranque del Bridge a librerías SMTP ni a la configuración de
red; aquí no hay salidas de red en import.
"""

from __future__ import annotations

import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings
from app.services.automations import EmailResult


class SmtpEmailProvider:
    """Envía correo real vía SMTP; errores cerrados, sin éxito fingido."""

    name = "smtp"

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: list[dict] | None = None,
        html: str | None = None,
        tracking_token: str | None = None,
    ) -> EmailResult:
        reference = f"smtp:{uuid.uuid4().hex[:12]}"
        host = (settings.SMTP_HOST or "").strip()
        if not host:
            return EmailResult(
                "smtp",
                to,
                subject,
                False,
                reference,
                error="smtp_host_not_configured",
                status="failed",
            )
        sender = (settings.SMTP_FROM or settings.SMTP_USERNAME or "").strip()
        if not sender:
            return EmailResult(
                "smtp",
                to,
                subject,
                False,
                reference,
                error="smtp_from_not_configured",
                status="failed",
            )
        message = EmailMessage()
        message["From"] = formataddr(("Bridge", sender))
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if html:
            # El cuerpo HTML (con pixel y enlaces de tracking) se envía como
            # alternativa multipart; el texto plano sigue siendo el body.
            message.add_alternative(html, subtype="html")
        for attachment in attachments or []:
            mime_parts = (attachment.get("mime_type") or "application/octet-stream").split("/", 1)
            maintype = mime_parts[0] or "application"
            subtype = mime_parts[1] if len(mime_parts) > 1 else "octet-stream"
            message.add_attachment(
                attachment.get("content", b""),
                maintype=maintype,
                subtype=subtype,
                filename=attachment.get("filename", "adjunto"),
            )

        try:
            if settings.SMTP_SSL:
                with smtplib.SMTP_SSL(
                    host,
                    settings.SMTP_PORT,
                    timeout=settings.SMTP_TIMEOUT_SEC,
                    context=ssl.create_default_context(),
                ) as server:
                    self._authenticate_and_send(server, message)
            else:
                with smtplib.SMTP(
                    host,
                    settings.SMTP_PORT,
                    timeout=settings.SMTP_TIMEOUT_SEC,
                ) as server:
                    server.ehlo()
                    if settings.SMTP_STARTTLS:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    self._authenticate_and_send(server, message)
        except Exception as exc:
            # Aceptar=False: el orquestador trata el envío como fallido y
            # decide la degradación (spool local) o el reintento/escalado.
            return EmailResult(
                "smtp",
                to,
                subject,
                False,
                reference,
                error=f"smtp_error:{type(exc).__name__}:{str(exc)[:200]}",
                status="failed",
            )
        return EmailResult("smtp", to, subject, True, reference, status="sent")

    @staticmethod
    def _authenticate_and_send(server: smtplib.SMTP, message: EmailMessage) -> None:
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)
