"""Observabilidad estructurada para Bridge (D-028).

Capacidades:

- Logs JSON con campos estables: ``timestamp``, ``level``, ``message``,
  ``logger``, ``correlation_id``, ``request_id``, ``tenant_id``,
  ``user_id``, ``route``, ``method``, ``status_code``, ``latency_ms`` y
  pares arbitrarios pasados en ``extra``.
- ``ContextVar`` por proceso para correlación sin contaminar los logs
  fuera del request/efecto.
- Middleware FastAPI que genera ``X-Correlation-ID`` si falta, propaga
  ``X-Request-ID`` y etiqueta cada línea con tenant/usuario.
- Métricas Prometheus (counters + histograms) para HTTP, outbox,
  circuit breakers, RAG y alertas.

No se loguean nunca contraseñas, tokens, secretos ni cuerpos de
documento: el helper ``redact_for_log`` aplica filtros por claves y
detectores por valor antes de emitir una línea. Cualquier integración
que quiera dejar un rastro debe pasar por ``log_event`` o
``record_metric``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

try:  # prometheus-client es opcional pero forma parte del gate D-028.
    from prometheus_client import Counter, Histogram
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - prometheus-client está en requirements.
    _PROMETHEUS_AVAILABLE = False


CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
TENANT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_id", default=None
)
USER_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)
ROUTE: contextvars.ContextVar[str | None] = contextvars.ContextVar("route", default=None)
METHOD: contextvars.ContextVar[str | None] = contextvars.ContextVar("method", default=None)


_CONTEXT_VARS: dict[str, contextvars.ContextVar[str | None]] = {
    "correlation_id": CORRELATION_ID,
    "request_id": REQUEST_ID,
    "tenant_id": TENANT_ID,
    "user_id": USER_ID,
    "route": ROUTE,
    "method": METHOD,
}


# Claves sensibles: nunca se persisten en logs aunque pasen como ``extra``.
# Coincidencia por subcadena (``lower in key``) para cubrir ``bearer``,
# ``bearer_token``, ``api_key``, ``api-key``, etc.
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "private_key",
    "private-key",
    "x-api-key",
    "x-auth-token",
)

# Patrones por valor: cualquier string que coincida se redacta a ``[REDACTED]``.
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[a-z0-9]{10,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
)


@dataclass(slots=True)
class AlertEvent:
    rule_id: str
    summary: str
    severity: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AlertSink:
    events: list[AlertEvent] = field(default_factory=list)

    def fire(self, rule_id: str, summary: str, *, severity: str = "warning", **details: Any) -> None:
        self.events.append(
            AlertEvent(rule_id=rule_id, summary=summary, severity=severity, details=dict(details))
        )
        log_event("WARNING", "alert.fired", rule_id=rule_id, summary=summary, severity=severity, **details)

    def clear(self) -> None:
        self.events.clear()


_sink = AlertSink()


def get_alert_sink() -> AlertSink:
    """Devuelve el sumidero in-memory de alertas (sustituible en tests)."""

    return _sink


def reset_alert_sink() -> None:
    """Limpia el sumidero; debe usarse solo en fixtures y al iniciar tests."""

    _sink.clear()


def redact_for_log(value: Any) -> Any:
    """Aplica redacción de claves y patrones sensibles a cualquier estructura."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower().replace("-", "_")
            if any(fragment in lower for fragment in _SENSITIVE_KEY_FRAGMENTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_for_log(item)
        return redacted
    if isinstance(value, list | tuple | set):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        redacted_text = value
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            redacted_text = pattern.sub("[REDACTED]", redacted_text)
        return redacted_text
    return value


class _JsonFormatter(logging.Formatter):
    """Formatter JSON estable; añade siempre los contextvars cuando estén definidos."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for attr in (
            "correlation_id",
            "request_id",
            "tenant_id",
            "user_id",
            "route",
            "method",
        ):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        extras = getattr(record, "_obs_extras", None)
        if extras:
            payload.update(redact_for_log(extras))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Instala el formatter JSON en el logger raíz (idempotente)."""

    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_obs_json", False):
            return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler._obs_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    # Silenciar uvicorn duplicado y conservar solo el access log estructurado.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).propagate = True


def log_event(level: str, message: str, **fields: Any) -> None:
    """Emite una línea de log con ``message`` y los ``fields`` redactados."""

    logger = logging.getLogger("bridge.observability")
    extras = {
        "correlation_id": CORRELATION_ID.get(),
        "request_id": REQUEST_ID.get(),
        "tenant_id": TENANT_ID.get(),
        "user_id": USER_ID.get(),
        "route": ROUTE.get(),
        "method": METHOD.get(),
        **redact_for_log(fields),
    }
    logger.log(getattr(logging, level.upper(), logging.INFO), message, extra={"_obs_extras": extras})


# ---------------------------------------------------------------------------
# Métricas Prometheus
# ---------------------------------------------------------------------------

if _PROMETHEUS_AVAILABLE:

    HTTP_REQUESTS = Counter(
        "bridge_http_requests_total",
        "Peticiones HTTP atendidas por el bridge.",
        labelnames=("method", "route", "status"),
    )
    HTTP_LATENCY = Histogram(
        "bridge_http_request_duration_seconds",
        "Latencia por petición HTTP del bridge.",
        labelnames=("method", "route"),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    OUTBOX_EVENTS = Counter(
        "bridge_outbox_events_total",
        "Eventos del outbox durable por estado y topic.",
        labelnames=("topic", "result"),
    )
    BREAKER_EVENTS = Counter(
        "bridge_circuit_breaker_events_total",
        "Aperturas, sondeos y cierres del circuit breaker por proveedor.",
        labelnames=("provider", "result"),
    )
    RAG_EVENTS = Counter(
        "bridge_rag_events_total",
        "Búsquedas RAG por resultado (abstained o success).",
        labelnames=("result",),
    )
    ALERTS_FIRED = Counter(
        "bridge_alerts_total",
        "Alertas disparadas por el evaluador de observabilidad.",
        labelnames=("rule_id", "severity"),
    )

else:  # pragma: no cover - entorno sin prometheus-client.

    class _NullMetric:
        def labels(self, **_labels: Any) -> _NullMetric:
            return self

        def inc(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def observe(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    HTTP_REQUESTS = _NullMetric()
    HTTP_LATENCY = _NullMetric()
    OUTBOX_EVENTS = _NullMetric()
    BREAKER_EVENTS = _NullMetric()
    RAG_EVENTS = _NullMetric()
    ALERTS_FIRED = _NullMetric()


def record_metric(metric: Any, **labels: Any) -> None:
    """Incrementa una métrica con etiquetas; tolera el stub nulo."""

    if labels:
        metric.labels(**labels).inc()
    else:
        metric.inc()


def record_latency(metric: Any, value: float, **labels: Any) -> None:
    if labels:
        metric.labels(**labels).observe(value)
    else:
        metric.observe(value)


# ---------------------------------------------------------------------------
# Reglas de alerta (evaluables in-memory; sin acoplamiento a Prometheus aún)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AlertRule:
    rule_id: str
    summary: str
    severity: str = "warning"
    description: str = ""


DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        rule_id="circuit_breaker_open",
        summary="Circuit breaker abierto en uno o más proveedores",
        severity="critical",
        description="Salta cuando algún breaker está open; revisar proveedor y outbox.",
    ),
    AlertRule(
        rule_id="outbox_dead_letter_growth",
        summary="Mensajes en dead-letter queue",
        severity="critical",
        description="Salta cuando el outbox acumula mensajes dead.",
    ),
    AlertRule(
        rule_id="rag_abstention_rate",
        summary="Abstención masiva en RAG",
        severity="warning",
        description="Salta cuando la mayoría de las búsquedas se abstienen.",
    ),
    AlertRule(
        rule_id="dlp_findings",
        summary="DLP detectó secretos en documentos",
        severity="critical",
        description="Salta cuando un documento recién ingestado contiene secretos.",
    ),
)


def evaluate_breaker_rule(breaker_states: dict[str, dict[str, Any]]) -> list[AlertEvent]:
    fired: list[AlertEvent] = []
    for provider, state in breaker_states.items():
        if state.get("state") == "open":
            event = AlertEvent(
                rule_id="circuit_breaker_open",
                summary=f"Breaker abierto: {provider}",
                severity="critical",
                details={"provider": provider, "state": state},
            )
            fired.append(event)
            get_alert_sink().fire(
                event.rule_id,
                event.summary,
                severity=event.severity,
                provider=provider,
                retry_after_seconds=state.get("retry_after_seconds"),
            )
            record_metric(ALERTS_FIRED, rule_id=event.rule_id, severity=event.severity)
    return fired


def evaluate_outbox_rule(outbox_counts: dict[str, int]) -> list[AlertEvent]:
    fired: list[AlertEvent] = []
    dead = int(outbox_counts.get("dead", 0))
    if dead > 0:
        event = AlertEvent(
            rule_id="outbox_dead_letter_growth",
            summary=f"{dead} mensaje(s) en DLQ",
            severity="critical",
            details={"dead": dead, "counts": outbox_counts},
        )
        fired.append(event)
        get_alert_sink().fire(event.rule_id, event.summary, severity=event.severity, dead=dead)
        record_metric(ALERTS_FIRED, rule_id=event.rule_id, severity=event.severity)
    return fired


def evaluate_rag_rule(successes: int, abstentions: int) -> list[AlertEvent]:
    total = successes + abstentions
    if total < 5:
        return []
    ratio = abstentions / total
    if ratio <= 0.5:
        return []
    event = AlertEvent(
        rule_id="rag_abstention_rate",
        summary=f"Abstención RAG al {ratio:.0%}",
        severity="warning",
        details={"successes": successes, "abstentions": abstentions, "ratio": ratio},
    )
    get_alert_sink().fire(event.rule_id, event.summary, severity=event.severity, **event.details)
    record_metric(ALERTS_FIRED, rule_id=event.rule_id, severity=event.severity)
    return [event]


@contextmanager
def request_context(
    *,
    correlation_id: str | None = None,
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    route: str | None = None,
    method: str | None = None,
) -> Iterator[None]:
    """Activa un contexto de observabilidad y restaura los valores previos."""

    expected = {
        "correlation_id": correlation_id,
        "request_id": request_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "route": route,
        "method": method,
    }
    tokens = {
        "correlation_id": CORRELATION_ID.set(correlation_id),
        "request_id": REQUEST_ID.set(request_id),
        "tenant_id": TENANT_ID.set(tenant_id),
        "user_id": USER_ID.set(user_id),
        "route": ROUTE.set(route),
        "method": METHOD.set(method),
    }
    try:
        yield
    finally:
        for name, token in tokens.items():
            var = _CONTEXT_VARS[name]
            try:
                var.reset(token)
            except ValueError:
                # El token se consumió en otro Context (p.ej. al cerrar una
                # dependencia FastAPI tras un error). Restauramos al valor
                # anterior conocido en lugar de dejar el contexto sucio.
                previous = var.get()
                if previous == expected[name]:
                    continue
                var.set(expected[name])


def new_correlation_id() -> str:
    return str(uuid.uuid4())
