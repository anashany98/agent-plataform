import ast
import inspect

import pytest

from scripts import verify_p0_migrations_postgres as migration_verifier
from scripts import verify_p0_postgres as verifier


def _set_valid_guard_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "a1b2c3d4e5f6"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://verifier:secret@db.invalid/p0_verify_{run_id}",
    )
    monkeypatch.setenv("INSTALLATION_ID", f"p0-verify-{run_id}")
    monkeypatch.setenv("P0_VERIFY_RUN_ID", run_id)
    monkeypatch.setenv("P0_VERIFY_EPHEMERAL_ACK", "DISPOSABLE-P0-POSTGRES-ONLY")


@pytest.mark.parametrize("module", [verifier, migration_verifier])
def test_postgres_verifier_has_no_optimizable_assert_statements(module) -> None:
    tree = ast.parse(inspect.getsource(module))

    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_postgres_verifier_accepts_only_run_bound_disposable_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_guard_environment(monkeypatch)

    assert verifier._validated_ephemeral_context() == (
        "postgresql://verifier:secret@db.invalid/p0_verify_a1b2c3d4e5f6",
        "p0-verify-a1b2c3d4e5f6",
        "a1b2c3d4e5f6",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("P0_VERIFY_EPHEMERAL_ACK", "yes"),
        ("P0_VERIFY_RUN_ID", "not-a-run-id"),
        ("INSTALLATION_ID", "production"),
        ("DATABASE_URL", "postgresql://verifier:secret@db.invalid/bridge_db"),
    ],
)
def test_postgres_verifier_rejects_unsafe_context(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _set_valid_guard_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="P0 PostgreSQL verification failed"):
        verifier._validated_ephemeral_context()
