from typing import Any, Dict, List

import httpx

from app.config import settings
from app.services.resilience import CircuitOpenError, guarded_request_with_retry


class ChatwootIntegrationError(RuntimeError):
    pass


class ChatwootAdapter:
    def __init__(self) -> None:
        self.base_url = settings.CHATWOOT_BASE_URL.rstrip("/")
        self.api_token = settings.CHATWOOT_API_TOKEN

    def _headers(self) -> Dict[str, str]:
        if not self.api_token:
            raise ChatwootIntegrationError("CHATWOOT_API_TOKEN no está configurado")
        return {"api_access_token": self.api_token, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if settings.ALLOW_INTEGRATION_STUBS and not self.api_token:
            return {"status": "simulated", "path": path, "payload": payload}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await guarded_request_with_retry(
                    "chatwoot",
                    lambda: client.post(
                        f"{self.base_url}{path}",
                        json=payload,
                        headers=self._headers(),
                    ),
                )
                response.raise_for_status()
                if not response.content:
                    return {"status": "success", "http_status": response.status_code}
                return response.json()
        except CircuitOpenError as exc:
            raise ChatwootIntegrationError(
                f"Circuito hacia Chatwoot abierto; la llamada se rechazó sin tocar la red: {exc}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ChatwootIntegrationError(f"Error al comunicarse con Chatwoot: {exc}") from exc

    async def send_reply(self, account_id: int, conversation_id: int, content: str) -> Dict[str, Any]:
        return await self._post(
            f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages",
            {"content": content, "message_type": "outgoing", "private": False},
        )

    async def toggle_human_handoff(self, account_id: int, conversation_id: int, status: str = "open") -> Dict[str, Any]:
        return await self._post(
            f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status",
            {"status": status},
        )

    async def assign_human_handoff(self, account_id: int, conversation_id: int) -> Dict[str, Any]:
        payload: Dict[str, int] = {}
        if settings.CHATWOOT_HANDOFF_TEAM_ID > 0:
            payload["team_id"] = settings.CHATWOOT_HANDOFF_TEAM_ID
        if settings.CHATWOOT_HANDOFF_ASSIGNEE_ID > 0:
            payload["assignee_id"] = settings.CHATWOOT_HANDOFF_ASSIGNEE_ID
        if not payload:
            raise ChatwootIntegrationError(
                "El handoff requiere CHATWOOT_HANDOFF_TEAM_ID o CHATWOOT_HANDOFF_ASSIGNEE_ID"
            )
        return await self._post(
            f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments",
            payload,
        )

    async def add_private_note(self, account_id: int, conversation_id: int, note_content: str) -> Dict[str, Any]:
        return await self._post(
            f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages",
            {"content": note_content, "message_type": "outgoing", "private": True},
        )

    async def add_labels(self, account_id: int, conversation_id: int, labels: List[str]) -> Dict[str, Any]:
        return await self._post(
            f"/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels",
            {"labels": labels},
        )
