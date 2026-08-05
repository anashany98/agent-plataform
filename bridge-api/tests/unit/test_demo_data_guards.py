from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import seed
from app.config import Settings
from app.models.models import Customer, Product, User


def _production_like_settings(environment: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": environment,
        "AUTH_SECRET": "synthetic-auth-secret-with-more-than-32-characters",
        "INITIAL_ADMIN_PASSWORD": "Synthetic-Admin-Password-For-Tests!",
        "CHATWOOT_API_TOKEN": "synthetic-chatwoot-api-token-for-tests-0123",
        "CHATWOOT_WEBHOOK_SECRET": "synthetic-webhook-secret-with-more-than-32-characters",
        "CHATWOOT_HANDOFF_TEAM_ID": 1,
        "ALLOW_MOCK_LLM": False,
        "ALLOW_INTEGRATION_STUBS": False,
        "AUTO_CREATE_SCHEMA": False,
        "ALLOW_DEMO_DATA": False,
        "AUTO_SEED_DEMO_DATA": False,
        # Autocontenido: en production-like SQLite/CORS abierto/DEBUG se rechazan
        # (D-022), así que el fixture usa PostgreSQL y orígenes/host cerrados para
        # aislar el comportamiento de los flags demo.
        "DATABASE_URL": "postgresql://user:pass@db:5432/bridge",
        "ALLOWED_ORIGINS": "https://portal.example.com",
        "ALLOWED_HOSTS": "portal.example.com,bridge-api",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_demo_data_flags_default_to_false_without_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_DEMO_DATA", raising=False)
    monkeypatch.delenv("AUTO_SEED_DEMO_DATA", raising=False)

    config = Settings(_env_file=None)

    assert config.ALLOW_DEMO_DATA is False
    assert config.AUTO_SEED_DEMO_DATA is False


def test_business_ttls_have_positive_defaults_without_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUOTE_CONFIRMATION_TTL_SEC", raising=False)
    monkeypatch.delenv("STOCK_RESERVATION_TTL_SEC", raising=False)

    config = Settings(_env_file=None)

    assert config.QUOTE_CONFIRMATION_TTL_SEC == 1800
    assert config.STOCK_RESERVATION_TTL_SEC == 900


@pytest.mark.parametrize("field", ["QUOTE_CONFIRMATION_TTL_SEC", "STOCK_RESERVATION_TTL_SEC"])
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_business_ttls_reject_non_positive_values(field: str, invalid_value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: invalid_value})


@pytest.mark.parametrize("environment", ["production", "staging"])
@pytest.mark.parametrize("enabled_flag", ["ALLOW_DEMO_DATA", "AUTO_SEED_DEMO_DATA"])
def test_production_like_rejects_each_demo_flag(environment: str, enabled_flag: str) -> None:
    config = _production_like_settings(environment, **{enabled_flag: True})

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_runtime_security()

    assert enabled_flag in str(exc_info.value)


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_production_like_accepts_demo_flags_only_when_both_are_disabled(environment: str) -> None:
    config = _production_like_settings(environment)

    config.validate_runtime_security()


class _FakeQuery:
    def __init__(self, *, first_result: object | None = None, count_result: int = 0) -> None:
        self._first_result = first_result
        self._count_result = count_result

    def filter(self, *_criteria: object) -> _FakeQuery:
        return self

    def first(self) -> object | None:
        return self._first_result

    def count(self) -> int:
        return self._count_result


class _FakeSession:
    def __init__(self) -> None:
        self.queried_models: list[object] = []
        self.added_instances: list[object] = []
        self.added_batches: list[list[object]] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.closed = False

    def query(self, model: object) -> _FakeQuery:
        self.queried_models.append(model)
        if model is User:
            return _FakeQuery(first_result=object())
        if model is Customer:
            return _FakeQuery(count_result=0)
        raise AssertionError(f"Consulta inesperada: {model}")

    def add(self, instance: object) -> None:
        self.added_instances.append(instance)

    def add_all(self, instances: list[object]) -> None:
        self.added_batches.append(list(instances))

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("allow_demo", "auto_seed", "expected_demo_seed"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_seed_requires_both_demo_flags(
    monkeypatch: pytest.MonkeyPatch,
    allow_demo: bool,
    auto_seed: bool,
    expected_demo_seed: bool,
) -> None:
    db = _FakeSession()
    test_settings = SimpleNamespace(
        INITIAL_ADMIN_USERNAME="existing-admin",
        ALLOW_DEMO_DATA=allow_demo,
        AUTO_SEED_DEMO_DATA=auto_seed,
    )
    monkeypatch.setattr(seed, "settings", test_settings)
    monkeypatch.setattr(seed, "SessionLocal", lambda: db)

    seed.seed_database()

    assert db.closed is True
    assert db.rollbacks == 0
    assert db.added_instances == []
    if not expected_demo_seed:
        assert Customer not in db.queried_models
        assert db.added_batches == []
        assert db.commits == 0
        return

    assert Customer in db.queried_models
    assert [len(batch) for batch in db.added_batches] == [5, 25, 100]
    assert all(isinstance(product, Product) for product in db.added_batches[-1])
    assert {product.source for product in db.added_batches[-1]} == {"demo"}
    assert db.flushes == 2
    assert db.commits == 1
