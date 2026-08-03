from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.config import settings

MAX_INSTALLATION_ID_LENGTH = 128
_installation_override: ContextVar[str | None] = ContextVar(
    "installation_id_override",
    default=None,
)


class InstallationContextError(RuntimeError):
    """Raised when an operation has no valid installation boundary."""


def validate_installation_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InstallationContextError("Se requiere un installation_id no vacío")
    normalized = value.strip()
    if len(normalized) > MAX_INSTALLATION_ID_LENGTH:
        raise InstallationContextError(
            f"installation_id supera {MAX_INSTALLATION_ID_LENGTH} caracteres"
        )
    return normalized


def get_current_installation_id() -> str:
    override = _installation_override.get()
    configured = override if override is not None else settings.INSTALLATION_ID
    return validate_installation_id(configured)


@contextmanager
def installation_scope(installation_id: str) -> Iterator[str]:
    """Temporarily selects one installation and always restores the prior scope."""

    normalized = validate_installation_id(installation_id)
    previous = _installation_override.get()
    token = _installation_override.set(normalized)
    try:
        yield normalized
    finally:
        try:
            _installation_override.reset(token)
        except ValueError:
            # El cleanup puede ejecutarse en un Context distinto (p. ej. el
            # cierre de dependencias generador de FastAPI tras un error de la
            # petición). Restaurar el valor anterior mantiene la semántica de
            # ámbito sin convertir el error original en un 500.
            _installation_override.set(previous)
