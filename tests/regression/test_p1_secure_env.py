"""Evals D-022: validación stricta de entorno production-like.

``Settings.validate_runtime_security`` debe bloquear el arranque en producción
ante secretos débiles/por defecto, mocks/stubs, datos demo, SQLite, CORS/host
abiertos y DEBUG activo; y aceptar una configuración segura. No toca la red.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.main import _api_documentation_paths

_SECURE = dict(
    ENVIRONMENT="production",
    APP_VERSION="1.0.0+test",
    AUTH_SECRET="A" * 40,
    INITIAL_ADMIN_PASSWORD="B" * 40,
    PILOT_MODE=False,
    CHATWOOT_ENABLED=True,
    CHATWOOT_API_TOKEN="C" * 40,
    CHATWOOT_WEBHOOK_SECRET="D" * 40,
    ALLOW_MOCK_LLM=False,
    ALLOW_INTEGRATION_STUBS=False,
    AUTO_CREATE_SCHEMA=False,
    ALLOW_DEMO_DATA=False,
    AUTO_SEED_DEMO_DATA=False,
    RATE_LIMIT_ENABLED=True,
    TRUSTED_PROXY_COUNT=2,
    TRUSTED_PROXY_CIDRS="172.16.0.0/12",
    REDIS_ENABLED=True,
    RATE_LIMIT_BACKEND="redis",
    REDIS_RATE_LIMIT_FAIL_OPEN=False,
    OUTBOX_WORKER_ENABLED=True,
    SCHEDULED_TASK_WORKER_ENABLED=True,
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


def test_secure_production_core_does_not_require_chatwoot() -> None:
    _settings(
        CHATWOOT_ENABLED=False,
        CHATWOOT_API_TOKEN="",
        CHATWOOT_WEBHOOK_SECRET="",
        CHATWOOT_HANDOFF_TEAM_ID=0,
        CHATWOOT_HANDOFF_ASSIGNEE_ID=0,
    ).validate_runtime_security()


@pytest.mark.parametrize(
    "override",
    [
        dict(CHATWOOT_API_TOKEN=""),
        dict(CHATWOOT_WEBHOOK_SECRET=""),
        dict(CHATWOOT_HANDOFF_TEAM_ID=0, CHATWOOT_HANDOFF_ASSIGNEE_ID=0),
    ],
)
def test_enabled_chatwoot_is_fail_closed_in_production(override) -> None:
    with pytest.raises(RuntimeError):
        _settings(**override).validate_runtime_security()


@pytest.mark.parametrize(
    "override",
    [
        dict(AUTH_SECRET="short"),
        dict(APP_VERSION="0.9.1-dev"),
        dict(AUTH_SECRET="replace-this-development-auth-secret-0123456789"),
        dict(INITIAL_ADMIN_PASSWORD="ChangeMe-Development-Only!"),
        dict(ALLOW_MOCK_LLM=True),
        dict(ALLOW_INTEGRATION_STUBS=True),
        dict(PILOT_MODE=True),
        dict(ALLOW_DEMO_DATA=True),
        dict(AUTO_CREATE_SCHEMA=True),
        dict(DATABASE_URL="sqlite:///local.db"),
        dict(ALLOWED_ORIGINS="*"),
        dict(ALLOWED_HOSTS="*"),
        dict(RATE_LIMIT_ENABLED=False),
        dict(TRUSTED_PROXY_COUNT=0),
        dict(TRUSTED_PROXY_CIDRS="not-a-cidr"),
        dict(REDIS_ENABLED=False),
        dict(RATE_LIMIT_BACKEND="memory"),
        dict(REDIS_RATE_LIMIT_FAIL_OPEN=True),
        dict(OUTBOX_WORKER_ENABLED=False),
        dict(SCHEDULED_TASK_WORKER_ENABLED=False),
        dict(ENABLE_AUTOMATIC_ORDER_CONFIRMATION=True),
        dict(ENABLE_AUTOMATIC_INVOICE_ISSUANCE=True),
        dict(ENABLE_AUTOMATIC_PUBLISHING=True),
    ],
)
def test_insecure_production_config_is_rejected(override) -> None:
    with pytest.raises(RuntimeError):
        _settings(**override).validate_runtime_security()


def test_non_production_skips_validation() -> None:
    # En desarrollo/staging no productivo la validación no bloquea.
    _settings(ENVIRONMENT="development", AUTH_SECRET="short").validate_runtime_security()


def test_api_documentation_is_disabled_only_in_production_like(monkeypatch) -> None:
    from app.main import settings as runtime_settings

    monkeypatch.setattr(runtime_settings, "ENVIRONMENT", "production")
    assert _api_documentation_paths() == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    monkeypatch.setattr(runtime_settings, "ENVIRONMENT", "development")
    assert _api_documentation_paths()["docs_url"] == "/docs"
