from typing import Any

import httpx

from app.config import settings
from app.services.resilience import CircuitOpenError, guarded_request_with_retry

EXTERNAL_REFERENCE_KEY = "external_reference"
RECONCILIATION_PAGE_SIZE = 100
RECONCILIATION_MAX_PAGES = 50


class GHLIntegrationError(RuntimeError):
    pass


class GHLAdapter:
    def __init__(self) -> None:
        self.base_url = settings.GHL_BASE_URL.rstrip("/")
        self.token = settings.GHL_API_TOKEN
        self.location_id = settings.GHL_LOCATION_ID

    def configured(self) -> bool:
        return bool(self.base_url and self.token and self.location_id)

    def _headers(self) -> dict[str, str]:
        if not self.configured():
            raise GHLIntegrationError("GHL no está configurado")
        return {
            "Authorization": f"Bearer {self.token}",
            "Version": "2021-07-28",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await guarded_request_with_retry(
                    "ghl",
                    lambda: client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        **kwargs,
                    ),
                )
                response.raise_for_status()
                return response.json() if response.content else {}
        except CircuitOpenError as exc:
            raise GHLIntegrationError(
                f"Circuito hacia GHL abierto; la llamada se rechazó sin tocar la red: {exc}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise GHLIntegrationError(f"Error de GHL: {exc}") from exc

    async def upsert_contact(self, *, email: str, first_name: str, phone: str | None = None, company_name: str | None = None) -> dict[str, Any]:
        payload = {
            "locationId": self.location_id,
            "email": email,
            "firstName": first_name,
            "phone": phone,
            "companyName": company_name,
            "source": "Agente comercial Ofideep",
        }
        return await self._request("POST", "/contacts/upsert", json={k: v for k, v in payload.items() if v is not None})

    async def create_opportunity(self, *, contact_id: str, name: str, monetary_value: float = 0.0, external_id: str) -> dict[str, Any]:
        if not settings.GHL_PIPELINE_ID or not settings.GHL_PIPELINE_STAGE_ID:
            raise GHLIntegrationError("Faltan el pipeline y la etapa de GHL")
        payload = {
            "pipelineId": settings.GHL_PIPELINE_ID,
            "locationId": self.location_id,
            "name": name,
            "pipelineStageId": settings.GHL_PIPELINE_STAGE_ID,
            "status": "open",
            "contactId": contact_id,
            "monetaryValue": monetary_value,
            "customFields": [{"key": EXTERNAL_REFERENCE_KEY, "field_value": external_id}],
        }
        return await self._request("POST", "/opportunities/", json=payload)

    async def add_note(self, contact_id: str, body: str) -> dict[str, Any]:
        return await self._request("POST", f"/contacts/{contact_id}/notes", json={"body": body})

    async def send_sms(self, *, contact_id: str, content: str) -> dict[str, Any]:
        """Envía un SMS a un contacto (T-083).

        Endpoint documentado de GHL: ``POST /contacts/{contactId}/messages``
        con ``type=SMS``. El mensaje se envía desde el número configurado en
        la subcuenta de GHL.
        """

        return await self._request(
            "POST",
            f"/contacts/{contact_id}/messages",
            json={
                "type": "SMS",
                "contactId": contact_id,
                "content": content,
            },
        )

    async def send_email(
        self,
        *,
        contact_id: str,
        subject: str,
        content: str,
        html: str | None = None,
    ) -> dict[str, Any]:
        """Envía un email a un contacto (T-083).

        Mismo endpoint de mensajes de GHL con ``type=email``. El asunto es
        obligatorio en GHL; el cuerpo puede ser texto plano o HTML.
        """

        payload: dict[str, Any] = {
            "type": "email",
            "contactId": contact_id,
            "subject": subject,
            "content": content,
        }
        if html:
            payload["html"] = html
        return await self._request(
            "POST", f"/contacts/{contact_id}/messages", json=payload
        )

    async def _page_results(self, path: str, params: dict[str, Any], list_key: str) -> list[dict[str, Any]]:
        """Paginación acotada hasta EOF; un listado anómalo falla cerrado.

        Sin EOF confirmado no se puede garantir la ausencia de un efecto, así
        que el tope de páginas se trata como error de reconciliación y nunca
        como listado completo.
        """

        results: list[dict[str, Any]] = []
        offset = 0
        for _ in range(RECONCILIATION_MAX_PAGES):
            page_params = {**params, "limit": RECONCILIATION_PAGE_SIZE, "offset": offset}
            response = await self._request("GET", path, params=page_params)
            if isinstance(response, dict):
                page = response.get(list_key)
            else:
                page = response
            if not isinstance(page, list):
                raise GHLIntegrationError("GHL devolvió un listado de reconciliación inválido")
            results.extend(item for item in page if isinstance(item, dict))
            if len(page) < RECONCILIATION_PAGE_SIZE:
                return results
            offset += RECONCILIATION_PAGE_SIZE
        raise GHLIntegrationError(
            "La reconciliación con GHL superó el límite de páginas sin confirmar EOF"
        )

    async def find_opportunity_by_reference(
        self, *, contact_id: str, external_id: str
    ) -> dict[str, Any] | None:
        """Busca una oportunidad ya creada con la misma referencia externa.

        GHL no acepta claves de idempotencia en la creación de oportunidades,
        así que esta búsqueda es la reconciliación que evita duplicarlas tras
        un crash entre el efecto externo y el checkpoint (D-010).
        """

        reference = str(external_id or "").strip()
        if not reference:
            raise GHLIntegrationError(
                "La reconciliación de oportunidades exige una referencia externa"
            )
        opportunities = await self._page_results(
            "/opportunities/search",
            {"locationId": self.location_id, "contact_id": contact_id},
            "opportunities",
        )
        for opportunity in opportunities:
            if str(opportunity.get("contactId") or "") != str(contact_id):
                continue
            for field in opportunity.get("customFields") or []:
                if not isinstance(field, dict):
                    continue
                if (
                    field.get("key") == EXTERNAL_REFERENCE_KEY
                    and str(field.get("field_value") or "") == reference
                ):
                    return opportunity
        return None

    async def find_note_by_body(self, contact_id: str, body: str) -> dict[str, Any] | None:
        """Busca una nota existente con el mismo cuerpo exacto (reconciliación)."""

        target = str(body or "")
        if not target:
            return None
        notes = await self._page_results(
            f"/contacts/{contact_id}/notes", {"contactId": contact_id}, "notes"
        )
        for note in notes:
            if str(note.get("body") or "") == target:
                return note
        return None
