"""Política de herramientas deny-by-default y executor gobernado para agentes.

Reglas innegociables:

- Solo existen las herramientas declaradas en ``TOOL_SPECS``; cualquier otro
  nombre se rechaza como desconocido.
- Un agente solo puede invocar la intersección de su ``allowed_tools`` con
  ``TOOL_SPECS``. Una allowlist vacía o con nombres desconocidos no otorga
  ninguna herramienta (fail-closed).
- Las herramientas financieras mutantes (confirmar pedidos, emitir facturas,
  fijar impuestos o precios) no son invocables por agentes: requieren flujo
  de aprobación humano y servicios deterministas dedicados.
- Toda invocación queda auditada: éxito, denegación y error.
- Los argumentos se validan contra el esquema antes de tocar ningún servicio;
  claves no declaradas se rechazan para impedir inyección de parámetros.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.models import AuditLog
from app.security import Principal
from app.services.deterministic_tools import BusinessRuleError, DeterministicToolsService
from app.services.rag_service import RAGError, RAGService
from fastapi import HTTPException
from sqlalchemy.orm import Session

TOOL_POLICY_DENY_BY_DEFAULT = "deny-by-default"

_MAX_TEXT_LEN = 2_000
_MAX_ITEMS = 100


class ToolPolicyError(Exception):
    """Herramienta desconocida o no autorizada para el agente."""


class ToolArgumentError(Exception):
    """Argumentos inválidos según el esquema declarado."""


_ARG_SPECS: dict[str, dict[str, Any]] = {
    "search_products": {
        "query": {"type": "str", "max_len": 500, "default": ""},
    },
    "get_product": {
        "product_id": {"type": "str", "required": True, "max_len": 150},
    },
    "get_customer": {
        "customer_id": {"type": "str", "required": True, "max_len": 150},
    },
    "check_stock": {
        "product_id": {"type": "str", "required": True, "max_len": 150},
        "qty": {"type": "int", "min": 1, "max": 100_000, "default": 1},
    },
    "calculate_price": {
        "product_id": {"type": "str", "required": True, "max_len": 150},
        "qty": {"type": "int", "min": 1, "max": 100_000, "default": 1},
        "customer_id": {"type": "str", "max_len": 150, "default": None},
        "combination_id": {"type": "str", "max_len": 150, "default": None},
    },
    "create_quote": {
        "customer_id": {"type": "str", "required": True, "max_len": 150},
        "items": {"type": "list", "required": True, "max_items": _MAX_ITEMS},
        "conversation_id": {"type": "str", "max_len": 150, "default": None},
        "source_message_id": {"type": "str", "max_len": 150, "default": None},
    },
    "rag_search": {
        "query": {"type": "str", "required": True, "max_len": _MAX_TEXT_LEN},
        "top_k": {"type": "int", "min": 1, "max": 10, "default": 3},
    },
    # T-057: herramientas read-only por módulo para los agentes
    # especializados. Deterministas y sin mutación (kind "read").
    "list_leads": {
        "status": {"type": "str", "max_len": 32, "default": None},
        "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
    },
    "list_activities": {
        "lead_id": {"type": "str", "max_len": 150, "default": None},
        "status": {"type": "str", "max_len": 32, "default": None},
        "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
    },
    "get_pipeline_report": {},
    "list_social_inbox": {
        "status": {"type": "str", "max_len": 32, "default": None},
        "intent": {"type": "str", "max_len": 32, "default": None},
        "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
    },
    "get_social_stats": {},
    "list_campaigns": {
        "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
    },
        "get_campaign_stats": {
            "campaign_id": {"type": "str", "required": True, "max_len": 150},
        },
        # Mejoras de agentes: contenido/SEO/wiki/landing y SLA social.
        "search_wiki": {
            "query": {"type": "str", "max_len": 500, "default": ""},
            "status": {"type": "str", "max_len": 32, "default": "published"},
            "limit": {"type": "int", "min": 1, "max": 100, "default": 20},
        },
        "get_seo_overview": {},
        "list_landing_pages": {
            "status": {"type": "str", "max_len": 32, "default": None},
            "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
        },
        "list_social_sla_breaches": {
            "limit": {"type": "int", "min": 1, "max": 200, "default": 50},
        },
}

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "search_products": {"kind": "read", "args": _ARG_SPECS["search_products"]},
    "get_product": {"kind": "read", "args": _ARG_SPECS["get_product"]},
    "get_customer": {"kind": "read", "args": _ARG_SPECS["get_customer"]},
    "check_stock": {"kind": "read", "args": _ARG_SPECS["check_stock"]},
    "calculate_price": {"kind": "read", "args": _ARG_SPECS["calculate_price"]},
    # Borrador: create_quote crea un presupuesto en estado borrador; la
    # confirmación exige la máquina de estados con token y aprobación humana.
    "create_quote": {"kind": "draft", "args": _ARG_SPECS["create_quote"]},
    "rag_search": {"kind": "read", "args": _ARG_SPECS["rag_search"]},
    "list_leads": {"kind": "read", "args": _ARG_SPECS["list_leads"]},
    "list_activities": {"kind": "read", "args": _ARG_SPECS["list_activities"]},
    "get_pipeline_report": {"kind": "read", "args": _ARG_SPECS["get_pipeline_report"]},
    "list_social_inbox": {"kind": "read", "args": _ARG_SPECS["list_social_inbox"]},
    "get_social_stats": {"kind": "read", "args": _ARG_SPECS["get_social_stats"]},
    "list_campaigns": {"kind": "read", "args": _ARG_SPECS["list_campaigns"]},
    "get_campaign_stats": {"kind": "read", "args": _ARG_SPECS["get_campaign_stats"]},
    # Mejoras de agentes (contenido/SEO/wiki/landing y SLA social).
    "search_wiki": {"kind": "read", "args": _ARG_SPECS["search_wiki"]},
    "get_seo_overview": {"kind": "read", "args": _ARG_SPECS["get_seo_overview"]},
    "list_landing_pages": {"kind": "read", "args": _ARG_SPECS["list_landing_pages"]},
    "list_social_sla_breaches": {
        "kind": "read",
        "args": _ARG_SPECS["list_social_sla_breaches"],
    },
}

# Herramientas que ningún agente puede invocar directamente aunque figuren en
# una allowlist: efectos financieros/contables requieren aprobación humana.
_FORBIDDEN_AGENT_TOOLS = frozenset(
    {
        "reserve_stock",
        "release_stock",
        "cancel_order_stock",
        "confirm_quote",
        "confirm_quote_transactional",
        "create_order",
        "create_invoice_draft",
        "submit_invoice_for_approval",
    }
)


def known_tool_names() -> list[str]:
    return sorted(TOOL_SPECS)


def authorized_tools_for(agent_config: Mapping[str, Any] | None) -> list[str]:
    """Allowlist efectiva del agente: intersección estricta con TOOL_SPECS.

    Nombres desconocidos o prohibidos se descartan silenciosamente de la
    autorización (fail-closed); una allowlist vacía no autoriza nada.
    """
    if not agent_config:
        return []
    declared = agent_config.get("allowed_tools") or []
    if not isinstance(declared, list | tuple | set | frozenset):
        return []
    authorized = {
        name
        for name in declared
        if isinstance(name, str) and name in TOOL_SPECS and name not in _FORBIDDEN_AGENT_TOOLS
    }
    return sorted(authorized)


def _validate_arguments(tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    spec_args = TOOL_SPECS[tool]["args"]
    unknown = set(arguments) - set(spec_args)
    if unknown:
        raise ToolArgumentError(f"Argumentos no declarados para {tool}: {sorted(unknown)}")
    validated: dict[str, Any] = {}
    for name, spec in spec_args.items():
        if name not in arguments:
            if spec.get("required"):
                raise ToolArgumentError(f"Falta el argumento obligatorio '{name}'")
            if "default" in spec:
                validated[name] = spec["default"]
            continue
        value = arguments[name]
        expected = spec["type"]
        if expected == "str":
            if value is None and not spec.get("required"):
                validated[name] = spec.get("default")
                continue
            if not isinstance(value, str):
                raise ToolArgumentError(f"El argumento '{name}' debe ser una cadena")
            max_len = spec.get("max_len", _MAX_TEXT_LEN)
            if len(value) > max_len:
                raise ToolArgumentError(f"El argumento '{name}' supera {max_len} caracteres")
            validated[name] = value
        elif expected == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ToolArgumentError(f"El argumento '{name}' debe ser un entero")
            if value < spec.get("min", 0) or value > spec.get("max", 10**9):
                raise ToolArgumentError(f"El argumento '{name}' está fuera de rango")
            validated[name] = value
        elif expected == "list":
            if not isinstance(value, list):
                raise ToolArgumentError(f"El argumento '{name}' debe ser una lista")
            if not value:
                raise ToolArgumentError(f"El argumento '{name}' no puede estar vacío")
            if len(value) > spec.get("max_items", _MAX_ITEMS):
                raise ToolArgumentError(f"El argumento '{name}' supera {spec.get('max_items')} elementos")
            if not all(isinstance(item, dict) for item in value):
                raise ToolArgumentError(f"El argumento '{name}' debe contener objetos")
            validated[name] = value
        else:  # pragma: no cover - defensivo
            raise ToolArgumentError(f"Especificación inválida para '{name}'")
    return validated


class ToolExecutor:
    """Única vía de ejecución de herramientas para agentes, con auditoría."""

    def __init__(self, db: Session, principal: Principal, agent_config: Mapping[str, Any]):
        self.db = db
        self.principal = principal
        self.agent_config = agent_config
        self.agent_id = str(agent_config.get("agent_id") or "unknown_agent")
        self.authorized = frozenset(authorized_tools_for(agent_config))

    def _audit(self, tool: str, status_value: str, detail: str | None = None) -> None:
        details: dict[str, Any] = {
            "tool": tool,
            "policy": TOOL_POLICY_DENY_BY_DEFAULT,
            "authorized_tools": sorted(self.authorized),
        }
        if detail:
            details["detail"] = detail[:500]
        self.db.add(
            AuditLog(
                installation_id=self.principal.installation_id,
                agent_id=self.agent_id,
                user_id=self.principal.user_id,
                event_type="tool_call",
                provider="internal",
                model_name="deterministic",
                status=status_value,
                details=details,
            )
        )
        self.db.commit()

    async def invoke(self, tool: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        name = (tool or "").strip()
        arguments = dict(arguments or {})
        if not name or name not in TOOL_SPECS or name in _FORBIDDEN_AGENT_TOOLS:
            self._audit(name or "<vacío>", "denied", "herramienta desconocida o prohibida")
            raise ToolPolicyError("Herramienta desconocida o no invocable por agentes")
        if name not in self.authorized:
            self._audit(name, "denied", "fuera de la allowlist del agente")
            raise ToolPolicyError(f"El agente {self.agent_id} no tiene autorizada la herramienta {name}")
        try:
            validated = _validate_arguments(name, arguments)
        except ToolArgumentError as exc:
            self._audit(name, "error", str(exc))
            raise
        try:
            result = await self._dispatch(name, validated)
        except (BusinessRuleError, RAGError) as exc:
            self._audit(name, "error", str(exc))
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        self._audit(name, "success")
        return result

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tools = DeterministicToolsService(self.db)
        if name == "search_products":
            return {"products": tools.search_products(query=args.get("query", ""))}
        if name == "get_product":
            return {"product": tools.get_product(args["product_id"])}
        if name == "get_customer":
            return {"customer": tools.get_customer(args["customer_id"])}
        if name == "check_stock":
            return {"stock": tools.check_stock(args["product_id"], args.get("qty", 1))}
        if name == "calculate_price":
            return {
                "price": tools.calculate_price(
                    args["product_id"],
                    args.get("qty", 1),
                    args.get("customer_id"),
                    combination_id=args.get("combination_id"),
                )
            }
        if name == "create_quote":
            return {
                "quote": tools.create_quote(
                    args["customer_id"],
                    args["items"],
                    conversation_id=args.get("conversation_id"),
                    source_message_id=args.get("source_message_id"),
                )
            }
        if name == "rag_search":
            rag = RAGService(self.db)
            return await rag.search(
                args["query"],
                top_k=args.get("top_k", 3),
                role=self.principal.role,
            )
        # T-057: herramientas read-only por módulo (agentes especializados).
        if name == "list_leads":
            return tools.list_leads(
                status=args.get("status"), limit=args.get("limit", 50)
            )
        if name == "list_activities":
            return tools.list_activities(
                lead_id=args.get("lead_id"),
                status=args.get("status"),
                limit=args.get("limit", 50),
            )
        if name == "get_pipeline_report":
            return tools.get_pipeline_report()
        if name == "list_social_inbox":
            return tools.list_social_inbox(
                status=args.get("status"),
                intent=args.get("intent"),
                limit=args.get("limit", 50),
            )
        if name == "get_social_stats":
            return tools.get_social_stats()
        if name == "list_campaigns":
            return tools.list_campaigns(limit=args.get("limit", 50))
        if name == "get_campaign_stats":
            return tools.get_campaign_stats(args["campaign_id"])
        if name == "search_wiki":
            return tools.search_wiki(
                query=args.get("query"),
                status=args.get("status", "published"),
                limit=args.get("limit", 20),
            )
        if name == "get_seo_overview":
            return tools.get_seo_overview()
        if name == "list_landing_pages":
            return tools.list_landing_pages(
                status=args.get("status"), limit=args.get("limit", 50)
            )
        if name == "list_social_sla_breaches":
            return tools.list_social_sla_breaches(limit=args.get("limit", 50))
        raise ToolPolicyError("Herramienta sin executor registrado")  # pragma: no cover
