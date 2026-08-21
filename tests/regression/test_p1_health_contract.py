import re
from pathlib import Path

from app.config import settings
from app.database import get_db
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"


def _bridge_healthcheck_command() -> str:
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    bridge_block = compose_text.split("\n  bridge-api:\n", 1)[1].split(
        "\n  flowwink-app:\n",
        1,
    )[0]
    match = re.search(
        r"(?m)^\s+test:\s*\[(?P<command>[^\n]+)]\s*$",
        bridge_block,
    )
    assert match is not None, "bridge-api carece de healthcheck en Compose"
    return match.group("command")


def test_liveness_is_independent_from_database(client) -> None:
    dependency_calls = 0

    def database_must_not_be_resolved():
        nonlocal dependency_calls
        dependency_calls += 1
        raise RuntimeError("liveness intentó resolver la base de datos")

    app.dependency_overrides[get_db] = database_must_not_be_resolved
    try:
        response = client.get("/live")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "bridge-api",
        "release_version": settings.APP_VERSION,
    }
    assert dependency_calls == 0


def test_readiness_fails_closed_when_database_is_unavailable(client) -> None:
    class UnavailableDatabase:
        @staticmethod
        def execute(*_args, **_kwargs):
            raise RuntimeError("synthetic database outage")

    def unavailable_database_dependency():
        yield UnavailableDatabase()

    app.dependency_overrides[get_db] = unavailable_database_dependency
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Base de datos no disponible"}


def test_readiness_requires_each_configured_worker(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OUTBOX_WORKER_ENABLED", True)
    monkeypatch.setattr(settings, "SCHEDULED_TASK_WORKER_ENABLED", False)
    outbox = client.get("/ready")
    assert outbox.status_code == 503
    assert outbox.json()["detail"] == "Worker de outbox no disponible"

    monkeypatch.setattr(settings, "OUTBOX_WORKER_ENABLED", False)
    monkeypatch.setattr(settings, "SCHEDULED_TASK_WORKER_ENABLED", True)
    scheduler = client.get("/ready")
    assert scheduler.status_code == 503
    assert scheduler.json()["detail"] == "Worker de tareas programadas no disponible"


def test_readiness_requires_redis_when_enabled(client, monkeypatch) -> None:
    from app.services.redis_backend import RedisBackend

    async def unavailable(_self) -> bool:
        return False

    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "OUTBOX_WORKER_ENABLED", False)
    monkeypatch.setattr(settings, "SCHEDULED_TASK_WORKER_ENABLED", False)
    monkeypatch.setattr(RedisBackend, "check", unavailable)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Backend Redis no disponible"


def test_compose_uses_readiness_for_bridge_healthcheck() -> None:
    healthcheck_command = _bridge_healthcheck_command()

    assert "curl -fsS" in healthcheck_command
    assert "http://127.0.0.1:8005/ready" in healthcheck_command
    assert "http://127.0.0.1:8005/health" not in healthcheck_command
    assert "http://127.0.0.1:8005/live" not in healthcheck_command
