import datetime as dt
import json
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog, DailyLLMBudget


class ProviderUnavailable(RuntimeError):
    pass


class PricingConfigurationError(RuntimeError):
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


@dataclass(frozen=True)
class PricingRate:
    catalog_version: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal


class LLMRouterService:
    _LOCAL_ZERO_COST_PROVIDERS = frozenset({"ollama", "mock"})
    _TOKEN_OVERHEAD_RESERVE = 512
    _COST_QUANTUM = Decimal("0.000001")

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

    @staticmethod
    def _decimal_rate(value: Any, field_name: str) -> Decimal:
        try:
            rate = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PricingConfigurationError(f"Tarifa inválida en {field_name}") from exc
        if not rate.is_finite() or rate < 0:
            raise PricingConfigurationError(f"Tarifa inválida en {field_name}")
        return rate

    def _pricing_for(self, provider: str, model: str) -> PricingRate:
        normalized_provider = provider.strip().lower()
        normalized_model = model.strip()
        if normalized_provider in self._LOCAL_ZERO_COST_PROVIDERS:
            return PricingRate("local-zero-cost", Decimal("0"), Decimal("0"))

        raw_catalog = settings.LLM_PRICING_CATALOG_JSON.strip()
        if not raw_catalog:
            raise PricingConfigurationError(
                f"No existe tarifa versionada para {normalized_provider}/{normalized_model}"
            )
        try:
            catalog = json.loads(raw_catalog)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PricingConfigurationError("LLM_PRICING_CATALOG_JSON no contiene JSON válido") from exc
        if not isinstance(catalog, dict):
            raise PricingConfigurationError("El catálogo de precios debe ser un objeto JSON")
        version = str(catalog.get("version") or "").strip()
        currency = str(catalog.get("currency") or "").strip().upper()
        models = catalog.get("models")
        if not version or currency != "USD" or not isinstance(models, dict):
            raise PricingConfigurationError(
                "El catálogo requiere version, currency=USD y un objeto models"
            )
        entry = None
        for key in (
            f"{normalized_provider}/{normalized_model}",
            f"{normalized_provider}:{normalized_model}",
        ):
            if key in models:
                entry = models[key]
                break
        if not isinstance(entry, dict):
            raise PricingConfigurationError(
                f"No existe tarifa versionada para {normalized_provider}/{normalized_model}"
            )
        input_rate = self._decimal_rate(entry.get("input_usd_per_million"), "input_usd_per_million")
        output_rate = self._decimal_rate(entry.get("output_usd_per_million"), "output_usd_per_million")
        if input_rate == 0 and output_rate == 0:
            raise PricingConfigurationError("Un proveedor externo no puede declararse con coste cero")
        return PricingRate(version, input_rate, output_rate)

    @classmethod
    def _rounded_cost(cls, value: Decimal) -> Decimal:
        if value <= 0:
            return Decimal("0")
        return value.quantize(cls._COST_QUANTUM, rounding=ROUND_CEILING)

    @classmethod
    def _estimate_cost(
        cls,
        rate: PricingRate,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Decimal:
        if prompt_tokens < 0 or completion_tokens < 0:
            raise PricingConfigurationError("El proveedor devolvió usage negativo")
        raw_cost = (
            Decimal(prompt_tokens) * rate.input_usd_per_million
            + Decimal(completion_tokens) * rate.output_usd_per_million
        ) / Decimal("1000000")
        return cls._rounded_cost(raw_cost)

    def _maximum_request_cost(
        self,
        rate: PricingRate,
        prompt: str,
        system_prompt: Optional[str],
    ) -> Decimal:
        input_bytes = len(prompt.encode("utf-8")) + len((system_prompt or "").encode("utf-8"))
        if input_bytes > settings.LLM_MAX_INPUT_BYTES:
            raise HTTPException(status_code=413, detail="El contexto supera el límite de entrada de IA")
        input_token_bound = input_bytes + self._TOKEN_OVERHEAD_RESERVE
        return self._estimate_cost(
            rate,
            input_token_bound,
            settings.LLM_MAX_OUTPUT_TOKENS,
        )

    def _lock_daily_budget(self, maximum_cost: Decimal) -> DailyLLMBudget:
        budget_date = dt.datetime.now(dt.UTC).date()
        row = (
            self.db.query(DailyLLMBudget)
            .filter(DailyLLMBudget.budget_date == budget_date)
            .with_for_update()
            .first()
        )
        if row is None:
            try:
                with self.db.begin_nested():
                    self.db.add(
                        DailyLLMBudget(
                            budget_date=budget_date,
                            spent_usd=Decimal("0"),
                        )
                    )
                    self.db.flush()
            except IntegrityError:
                pass
            row = (
                self.db.query(DailyLLMBudget)
                .filter(DailyLLMBudget.budget_date == budget_date)
                .with_for_update()
                .one()
            )
        limit = Decimal(str(settings.LLM_MAX_DAILY_COST_USD))
        if Decimal(row.spent_usd or 0) + maximum_cost > limit:
            raise HTTPException(status_code=429, detail="Límite diario de gasto de IA alcanzado")
        return row

    async def generate_response(
        self,
        prompt: str,
        profile: str = "standard",
        system_prompt: Optional[str] = None,
        correlation_id: str = "internal",
        agent_id: str = "default_agent",
        user_id: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        if not prompt.strip():
            raise HTTPException(status_code=422, detail="El mensaje no puede estar vacío")
        start = time.perf_counter()
        errors: list[str] = []
        result: ProviderResult | None = None
        selected_rate: PricingRate | None = None
        budget_row: DailyLLMBudget | None = None
        reserved_ceiling = Decimal("0")
        pricing_blocked = False
        budget_blocked = False
        for config in self._profiles().get(profile, self._profiles()["standard"]):
            if not config["provider"] or not config["model"]:
                errors.append(f"{config['provider'] or 'proveedor'} sin modelo configurado")
                continue
            try:
                candidate_rate = self._pricing_for(config["provider"], config["model"])
                candidate_ceiling = self._maximum_request_cost(
                    candidate_rate,
                    prompt,
                    system_prompt,
                )
                candidate_budget_row = (
                    self._lock_daily_budget(candidate_ceiling)
                    if candidate_ceiling > 0
                    else None
                )
            except PricingConfigurationError as exc:
                pricing_blocked = True
                errors.append(str(exc))
                continue
            except HTTPException as exc:
                if exc.status_code != 429:
                    raise
                budget_blocked = True
                errors.append(str(exc.detail))
                continue
            try:
                result = await self._call_provider(config["provider"], config["model"], prompt, system_prompt)
                if (
                    result.provider.strip().lower() != config["provider"].strip().lower()
                    or result.model.strip() != config["model"].strip()
                ):
                    raise ProviderUnavailable(
                        "El proveedor devolvió una identidad de modelo distinta de la solicitada"
                    )
                selected_rate = candidate_rate
                reserved_ceiling = candidate_ceiling
                budget_row = candidate_budget_row
                break
            except ProviderUnavailable as exc:
                errors.append(str(exc))

        if result is None and settings.ALLOW_MOCK_LLM and not pricing_blocked and not budget_blocked:
            result = ProviderResult(
                content="Modo de demostración: no hay un proveedor de IA real configurado.",
                prompt_tokens=0,
                completion_tokens=0,
                provider="mock",
                model="explicit-development-mock",
                raw_usage={},
                simulated=True,
            )
            selected_rate = self._pricing_for(result.provider, result.model)
        if result is None:
            self._audit_failure(
                correlation_id,
                agent_id,
                user_id,
                profile,
                errors,
                (time.perf_counter() - start) * 1000,
                allowed_tools=allowed_tools,
            )
            if budget_blocked:
                raise HTTPException(status_code=429, detail="Límite diario de gasto de IA alcanzado")
            raise HTTPException(status_code=503, detail={"message": "Ningún proveedor de IA está disponible", "errors": errors})

        latency_ms = (time.perf_counter() - start) * 1000
        total_tokens = result.prompt_tokens + result.completion_tokens
        if selected_rate is None:
            raise HTTPException(status_code=503, detail="No se pudo determinar la tarifa del proveedor")
        cost_bearing = bool(
            selected_rate.input_usd_per_million > 0
            or selected_rate.output_usd_per_million > 0
        )
        if cost_bearing and total_tokens <= 0:
            self.db.add(
                AuditLog(
                    correlation_id=correlation_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    event_type="agent_run",
                    provider=result.provider,
                    model_name=result.model,
                    status="usage_missing",
                    latency_ms=round(latency_ms, 2),
                    details={
                        "profile": profile,
                        "pricing_catalog_version": selected_rate.catalog_version,
                        "provider_usage": result.raw_usage,
                    },
                )
            )
            self.db.commit()
            raise HTTPException(
                status_code=502,
                detail="El proveedor facturable no devolvió usage verificable",
            )
        cost = self._estimate_cost(
            selected_rate,
            result.prompt_tokens,
            result.completion_tokens,
        )
        input_token_bound = (
            len(prompt.encode("utf-8"))
            + len((system_prompt or "").encode("utf-8"))
            + self._TOKEN_OVERHEAD_RESERVE
        )
        usage_contract_violation = cost_bearing and (
            result.prompt_tokens > input_token_bound
            or result.completion_tokens > settings.LLM_MAX_OUTPUT_TOKENS
        )
        billing_anomaly = bool(
            budget_row is not None
            and (cost > reserved_ceiling or usage_contract_violation)
        )
        if budget_row is not None:
            budget_row.spent_usd = Decimal(budget_row.spent_usd or 0) + cost
            budget_row.updated_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
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
            status=(
                "billing_anomaly"
                if billing_anomaly
                else ("success" if not result.simulated else "simulated")
            ),
            details={
                "profile": profile,
                "simulated": result.simulated,
                "provider_usage": result.raw_usage,
                "pricing_catalog_version": selected_rate.catalog_version,
                "reserved_ceiling_usd": float(reserved_ceiling),
                "tool_policy": "deny-by-default",
                "authorized_tools": sorted(allowed_tools or []),
            },
        )
        self.db.add(audit)
        self.db.commit()
        if billing_anomaly:
            raise HTTPException(
                status_code=502,
                detail="El usage del proveedor superó la reserva máxima; respuesta bloqueada",
            )
        return {
            "content": result.content,
            "provider": result.provider,
            "model": result.model,
            "simulated": result.simulated,
            "tokens": {"prompt": result.prompt_tokens, "completion": result.completion_tokens, "total": total_tokens},
            "latency_ms": round(latency_ms, 2),
            "estimated_cost_usd": float(cost),
        }

    def _audit_failure(
        self,
        correlation_id: str,
        agent_id: str,
        user_id: str | None,
        profile: str,
        errors: list[str],
        latency: float,
        allowed_tools: Optional[list[str]] = None,
    ) -> None:
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
                details={
                    "profile": profile,
                    "errors": errors,
                    "tool_policy": "deny-by-default",
                    "authorized_tools": sorted(allowed_tools or []),
                },
            )
        )
        self.db.commit()

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
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": settings.LLM_MAX_OUTPUT_TOKENS},
        }
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
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
                    },
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
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
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
