from typing import Any, Dict, List

import httpx

from app.config import settings


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
                response = await client.post(f"{self.base_url}{path}", json=payload, headers=self._headers())
                response.raise_for_status()
                if not response.content:
                    return {"status": "success", "http_status": response.status_code}
                return response.json()
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
