import datetime as dt
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog


class ProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    provider: str
    model: str
    raw_usage: Dict[str, Any]
    simulated: bool = False


class LLMRouterService:
    def __init__(self, db: Session):
        self.db = db

    def _profiles(self) -> Dict[str, list[dict[str, str]]]:
        profiles = {
            "cheap": [
                {"provider": settings.CHEAP_LLM_PROVIDER, "model": settings.CHEAP_LLM_MODEL},
                {"provider": settings.STANDARD_LLM_PROVIDER, "model": settings.STANDARD_LLM_MODEL},
            ],
            "standard": [
                {"provider": settings.STANDARD_LLM_PROVIDER, "model": settings.STANDARD_LLM_MODEL},
                {"provider": settings.CHEAP_LLM_PROVIDER, "model": settings.CHEAP_LLM_MODEL},
            ],
            "advanced": [
                {"provider": settings.ADVANCED_LLM_PROVIDER, "model": settings.ADVANCED_LLM_MODEL},
                {"provider": settings.STANDARD_LLM_PROVIDER, "model": settings.STANDARD_LLM_MODEL},
            ],
            "critical": [
                {"provider": settings.CRITICAL_LLM_PROVIDER, "model": settings.CRITICAL_LLM_MODEL},
                {"provider": settings.ADVANCED_LLM_PROVIDER, "model": settings.ADVANCED_LLM_MODEL},
            ],
        }
        return profiles

    def _check_budget(self) -> None:
        today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        spent = self.db.query(func.coalesce(func.sum(AuditLog.estimated_cost_usd), 0)).filter(
            AuditLog.timestamp >= today,
            AuditLog.status == "success",
        ).scalar()
        if float(spent or 0) >= settings.LLM_MAX_DAILY_COST_USD:
            raise HTTPException(status_code=429, detail="Límite diario de gasto de IA alcanzado")

    async def generate_response(
        self,
        prompt: str,
        profile: str = "standard",
        system_prompt: Optional[str] = None,
        correlation_id: str = "internal",
        agent_id: str = "default_agent",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not prompt.strip():
            raise HTTPException(status_code=422, detail="El mensaje no puede estar vacío")
        self._check_budget()
        start = time.perf_counter()
        errors: list[str] = []
        result: ProviderResult | None = None
        for config in self._profiles().get(profile, self._profiles()["standard"]):
            if not config["provider"] or not config["model"]:
                errors.append(f"{config['provider'] or 'proveedor'} sin modelo configurado")
                continue
            try:
                result = await self._call_provider(config["provider"], config["model"], prompt, system_prompt)
                break
            except ProviderUnavailable as exc:
                errors.append(str(exc))

        if result is None and settings.ALLOW_MOCK_LLM:
            result = ProviderResult(
                content="Modo de demostración: no hay un proveedor de IA real configurado.",
                prompt_tokens=0,
                completion_tokens=0,
                provider="mock",
                model="explicit-development-mock",
                raw_usage={},
                simulated=True,
            )
        if result is None:
            self._audit_failure(correlation_id, agent_id, user_id, profile, errors, (time.perf_counter() - start) * 1000)
            raise HTTPException(status_code=503, detail={"message": "Ningún proveedor de IA está disponible", "errors": errors})

        latency_ms = (time.perf_counter() - start) * 1000
        total_tokens = result.prompt_tokens + result.completion_tokens
        cost = self._estimate_cost(result.provider, result.model, result.prompt_tokens, result.completion_tokens)
        audit = AuditLog(
            correlation_id=correlation_id,
            agent_id=agent_id,
            user_id=user_id,
            event_type="agent_run",
            provider=result.provider,
            model_name=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=total_tokens,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=cost,
            status="success" if not result.simulated else "simulated",
            details={"profile": profile, "simulated": result.simulated, "provider_usage": result.raw_usage},
        )
        self.db.add(audit)
        self.db.commit()
        return {
            "content": result.content,
            "provider": result.provider,
            "model": result.model,
            "simulated": result.simulated,
            "tokens": {"prompt": result.prompt_tokens, "completion": result.completion_tokens, "total": total_tokens},
            "latency_ms": round(latency_ms, 2),
            "estimated_cost_usd": float(cost),
        }

    def _audit_failure(self, correlation_id: str, agent_id: str, user_id: str | None, profile: str, errors: list[str], latency: float) -> None:
        self.db.add(
            AuditLog(
                correlation_id=correlation_id,
                agent_id=agent_id,
                user_id=user_id,
                event_type="agent_run",
                provider="none",
                model_name="none",
                status="error",
                latency_ms=round(latency, 2),
                details={"profile": profile, "errors": errors},
            )
        )
        self.db.commit()

    @staticmethod
    def _estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        # Rates are intentionally zero unless configured by an external billing catalogue.
        # This prevents fabricated costs. Raw token usage remains recorded.
        return 0.0

    async def _call_provider(self, provider: str, model: str, prompt: str, system_prompt: Optional[str]) -> ProviderResult:
        provider = provider.lower().strip()
        if provider == "ollama":
            return await self._call_ollama(model, prompt, system_prompt)
        if provider == "openai":
            return await self._call_openai_compatible(settings.OPENAI_BASE_URL, settings.OPENAI_API_KEY, provider, model, prompt, system_prompt)
        if provider in {"deepseek", "qwen", "kimi", "glm", "minimax", "openai_compatible"}:
            base_url = getattr(settings, f"{provider.upper()}_BASE_URL", "") or settings.OPENAI_BASE_URL
            api_key = getattr(settings, f"{provider.upper()}_API_KEY", "")
            return await self._call_openai_compatible(base_url, api_key, provider, model, prompt, system_prompt)
        if provider == "anthropic":
            return await self._call_anthropic(model, prompt, system_prompt)
        if provider == "mock" and settings.ALLOW_MOCK_LLM:
            return ProviderResult("Respuesta simulada explícita de desarrollo.", 0, 0, "mock", model, {}, True)
        raise ProviderUnavailable(f"Proveedor no soportado o no permitido: {provider}")

    async def _call_ollama(self, model: str, prompt: str, system_prompt: Optional[str]) -> ProviderResult:
        payload: Dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system_prompt:
            payload["system"] = system_prompt
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
                response = await client.post(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
            content = str(data.get("response") or "").strip()
            if not content:
                raise ProviderUnavailable("Ollama devolvió una respuesta vacía")
            return ProviderResult(
                content,
                int(data.get("prompt_eval_count") or 0),
                int(data.get("eval_count") or 0),
                "ollama",
                model,
                {k: data.get(k) for k in ("total_duration", "load_duration", "eval_duration")},
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"Ollama no disponible: {exc}") from exc

    async def _call_openai_compatible(self, base_url: str, api_key: str, provider: str, model: str, prompt: str, system_prompt: Optional[str]) -> ProviderResult:
        if not base_url or not api_key:
            raise ProviderUnavailable(f"Credenciales no configuradas para {provider}")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "temperature": 0.2},
                )
                response.raise_for_status()
                data = response.json()
            content = str(data["choices"][0]["message"]["content"]).strip()
            usage = data.get("usage") or {}
            return ProviderResult(content, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), provider, model, usage)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"{provider} no disponible: {exc}") from exc

    async def _call_anthropic(self, model: str, prompt: str, system_prompt: Optional[str]) -> ProviderResult:
        if not settings.ANTHROPIC_API_KEY:
            raise ProviderUnavailable("Credenciales de Anthropic no configuradas")
        payload: Dict[str, Any] = {"model": model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]}
        if system_prompt:
            payload["system"] = system_prompt
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_REQUEST_TIMEOUT_SEC) as client:
                response = await client.post(
                    f"{settings.ANTHROPIC_BASE_URL.rstrip('/')}/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()
            usage = data.get("usage") or {}
            if not content:
                raise ProviderUnavailable("Anthropic devolvió una respuesta vacía")
            return ProviderResult(content, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), "anthropic", model, usage)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"Anthropic no disponible: {exc}") from exc
