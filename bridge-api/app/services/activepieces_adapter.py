from typing import Any, Dict

import httpx

from app.config import settings


class ActivepiecesIntegrationError(RuntimeError):
    pass


class ActivepiecesAdapter:
    def __init__(self) -> None:
        self.base_url = settings.ACTIVEPIECES_BASE_URL.rstrip("/")
        self.api_key = settings.ACTIVEPIECES_API_KEY

    async def trigger_webhook(self, webhook_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not webhook_path.startswith("/"):
            webhook_path = f"/{webhook_path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(f"{self.base_url}{webhook_path}", json=payload, headers=headers)
                response.raise_for_status()
                return response.json() if response.content else {"status": "accepted"}
        except (httpx.HTTPError, ValueError) as exc:
            raise ActivepiecesIntegrationError(f"Error de Activepieces: {exc}") from exc
