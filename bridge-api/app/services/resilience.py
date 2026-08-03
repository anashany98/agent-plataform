"""Circuit breakers por proveedor para integración externa.

Reglas:

- Cada proveedor (``chatwoot``, ``ghl``, ``prestashop``, ``activepieces``...)
  tiene su propio breaker. Un breaker abierto falla rápido sin tocar la red.
- El breaker se abre tras ``CIRCUIT_BREAKER_FAILURE_THRESHOLD`` fallos
  consecutivos (errores de red o respuestas 408/425/429/5xx). Cualquier
  respuesta no reintentable (incluidos 4xx) cuenta como éxito: el proveedor
  responde y el circuito no debe castigarlo.
- Tras ``CIRCUIT_BREAKER_RECOVERY_SEC`` el breaker pasa a ``half_open`` y
  deja pasar sondas. Una sonda con éxito cierra el circuito; una sonda
  fallida lo reabre con el temporizador completo.
- El estado es observable (``/metrics``) y auditable; nunca se silencian
  fallos: abrir el circuito solo cambia cuándo se reintenta, no si se
  reintenta (eso lo gobierna el outbox).
"""

from __future__ import annotations

import datetime
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import settings


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class CircuitOpenError(RuntimeError):
    """El circuito hacia el proveedor está abierto y la llamada se rechaza."""

    def __init__(self, breaker_name: str, retry_after_seconds: float) -> None:
        self.breaker_name = breaker_name
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(
            f"Circuito '{breaker_name}' abierto; reintento permitido en "
            f"{self.retry_after_seconds:.1f}s"
        )


class CircuitBreaker:
    """Máquina de estados closed → open → half_open con reloj inyectable."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int | None = None,
        recovery_sec: float | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = max(
            1,
            int(
                failure_threshold
                if failure_threshold is not None
                else settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD
            ),
        )
        self.recovery_sec = max(
            0.0,
            float(
                recovery_sec
                if recovery_sec is not None
                else settings.CIRCUIT_BREAKER_RECOVERY_SEC
            ),
        )
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at: datetime.datetime | None = None

    def _elapsed_seconds(self) -> float:
        if self._opened_at is None:
            return float("inf")
        return (self._clock() - self._opened_at).total_seconds()

    def state(self) -> str:
        with self._lock:
            if self._state == "open" and self._elapsed_seconds() >= self.recovery_sec:
                self._state = "half_open"
            return self._state

    def allow_request(self) -> bool:
        return self.state() != "open"

    def retry_after_seconds(self) -> float:
        with self._lock:
            if self._state != "open":
                return 0.0
            return max(0.0, self.recovery_sec - self._elapsed_seconds())

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == "half_open"
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._state = "open"
                self._opened_at = self._clock()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            return {
                "name": self.name,
                "state": state,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "recovery_sec": self.recovery_sec,
                "opened_at": self._opened_at.isoformat() if self._opened_at else None,
                "retry_after_seconds": self.retry_after_seconds(),
            }


_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.RLock()


def get_breaker(name: str) -> CircuitBreaker:
    """Devuelve el breaker del proveedor, creándolo la primera vez."""

    key = name.strip().lower()
    if not key:
        raise ValueError("El nombre del circuit breaker no puede estar vacío")
    with _REGISTRY_LOCK:
        breaker = _REGISTRY.get(key)
        if breaker is None:
            breaker = CircuitBreaker(key)
            _REGISTRY[key] = breaker
        return breaker


def all_breaker_states() -> dict[str, dict[str, Any]]:
    with _REGISTRY_LOCK:
        breakers = list(_REGISTRY.values())
    return {breaker.name: breaker.to_dict() for breaker in sorted(breakers, key=lambda item: item.name)}


def reset_all_breakers() -> None:
    """Reinicia el registro completo; solo para tests y arranque limpio."""

    with _REGISTRY_LOCK:
        _REGISTRY.clear()


async def guarded_request_with_retry(
    breaker_name: str,
    operation: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """`request_with_retry` gobernado por el circuit breaker del proveedor."""

    from app.services.http_retry import request_with_retry

    return await request_with_retry(operation, breaker=get_breaker(breaker_name))
