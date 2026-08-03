from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.services.resilience import CircuitOpenError, guarded_request_with_retry


class GHLIntegrationError(RuntimeError):
    pass


class GHLAdapter:
    def __init__(self) -> None:
        self.base_url = settings.GHL_BASE_URL.rstrip("/")
        self.token = settings.GHL_API_TOKEN
        self.location_id = settings.GHL_LOCATION_ID

    def configured(self) -> bool:
        return bool(self.base_url and self.token and self.location_id)

    def _headers(self) -> Dict[str, str]:
        if not self.configured():
            raise GHLIntegrationError("GHL no está configurado")
        return {
            "Authorization": f"Bearer {self.token}",
            "Version": "2021-07-28",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
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

    async def upsert_contact(self, *, email: str, first_name: str, phone: Optional[str] = None, company_name: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "locationId": self.location_id,
            "email": email,
            "firstName": first_name,
            "phone": phone,
            "companyName": company_name,
            "source": "Agente comercial Ofideep",
        }
        return await self._request("POST", "/contacts/upsert", json={k: v for k, v in payload.items() if v is not None})

    async def create_opportunity(self, *, contact_id: str, name: str, monetary_value: float = 0.0, external_id: str) -> Dict[str, Any]:
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
            "customFields": [{"key": "external_reference", "field_value": external_id}],
        }
        return await self._request("POST", "/opportunities/", json=payload)

    async def add_note(self, contact_id: str, body: str) -> Dict[str, Any]:
        return await self._request("POST", f"/contacts/{contact_id}/notes", json={"body": body})
