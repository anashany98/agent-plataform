"""Evals D-022: validación stricta de entorno production-like.

``Settings.validate_runtime_security`` debe bloquear el arranque en producción
ante secretos débiles/por defecto, mocks/stubs, datos demo, SQLite, CORS/host
abiertos y DEBUG activo; y aceptar una configuración segura. No toca la red.
"""

from __future__ import annotations

import pytest
from app.config import Settings

_SECURE = dict(
    ENVIRONMENT="production",
    AUTH_SECRET="A" * 40,
    INITIAL_ADMIN_PASSWORD="B" * 40,
    CHATWOOT_API_TOKEN="C" * 40,
    CHATWOOT_WEBHOOK_SECRET="D" * 40,
    ALLOW_MOCK_LLM=False,
    ALLOW_INTEGRATION_STUBS=False,
    AUTO_CREATE_SCHEMA=False,
    ALLOW_DEMO_DATA=False,
    AUTO_SEED_DEMO_DATA=False,
    DATABASE_URL="postgresql://user:pass@db:5432/bridge",
    ALLOWED_ORIGINS="https://portal.example.com",
    ALLOWED_HOSTS="portal.example.com,bridge-api",
    CHATWOOT_HANDOFF_TEAM_ID=1,
)


def _settings(**overrides):
    kwargs = dict(_SECURE)
    kwargs.update(overrides)
    return Settings(**kwargs)


def test_secure_production_config_passes() -> None:
    _settings().validate_runtime_security()  # no debe lanzar


@pytest.mark.parametrize(
    "override",
    [
        dict(AUTH_SECRET="short"),
        dict(AUTH_SECRET="replace-this-development-auth-secret-0123456789"),
        dict(INITIAL_ADMIN_PASSWORD="ChangeMe-Development-Only!"),
        dict(ALLOW_MOCK_LLM=True),
        dict(ALLOW_INTEGRATION_STUBS=True),
        dict(ALLOW_DEMO_DATA=True),
        dict(AUTO_CREATE_SCHEMA=True),
        dict(DATABASE_URL="sqlite:///local.db"),
        dict(ALLOWED_ORIGINS="*"),
        dict(ALLOWED_HOSTS="*"),
    ],
)
def test_insecure_production_config_is_rejected(override) -> None:
    with pytest.raises(RuntimeError):
        _settings(**override).validate_runtime_security()


def test_non_production_skips_validation() -> None:
    # En desarrollo/staging no productivo la validación no bloquea.
    _settings(ENVIRONMENT="development", AUTH_SECRET="short").validate_runtime_security()
