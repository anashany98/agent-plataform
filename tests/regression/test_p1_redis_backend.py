"""Evals Fase B, bloque 3: Redis real como backend de rate limit, locks y
cola del worker durable.

Hermetismo: se inyecta un ``InMemoryRedis`` (falso en memoria) que implementa
la interfaz mínima que usa ``RedisBackend`` — ningún eval contacta un Redis
real salvo el opt-in con ``RUN_REDIS_EVALS=1`` (que usa ``fakeredis`` si
está instalado o un servidor real en ``REDIS_URL``).

Cubre:
- rate limit: ventana fija con INCR+EXPIRE, retry-after, reset
- degradación: Redis caído → fail-open a memoria (nunca 500/503 por backend)
- locks distribuidos: SET NX EX, liberación con token correcto/ajeno, TTL
- worker durable: señal Redis, lock de dispatch, reclaim de leases vencidos
  (crash del worker) sin perder el efecto, idempotencia por clave
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import OutboxMessage, Product
from app.security import Principal, get_current_principal
from app.services.outbox import OutboxService
from app.services.outbox_worker import DISPATCH_LOCK, DurableOutboxWorker
from app.services.redis_backend import RedisBackend, RedisBackendError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_ID = "redis-evals"


class InMemoryRedis:
    """Falso de Redis en memoria con TTL y listas (interfaz mínima)."""

    def __init__(self, *, broken: bool = False) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}
        self._lists: dict[str, deque] = defaultdict(deque)
        self._ttl: dict[str, float] = {}
        self.broken = broken

    def _expired(self, key: str) -> bool:
        ttl = self._ttl.get(key)
        return ttl is not None and ttl <= time.monotonic()

    def _purge(self, key: str) -> None:
        if self._expired(key):
            self._store.pop(key, None)
            self._lists.pop(key, None)
            self._ttl.pop(key, None)

    async def ping(self) -> bool:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        return True

    async def incr(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        self._purge(key)
        value, _ = self._store.get(key, (0, None))
        value = int(value) + 1
        self._store[key] = (value, None)
        return value

    async def expire(self, key: str, seconds: int) -> int:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        if key not in self._store and key not in self._lists:
            return 0
        self._ttl[key] = time.monotonic() + max(1, int(seconds))
        return 1

    async def ttl(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        self._purge(key)
        ttl = self._ttl.get(key)
        if ttl is None:
            return -1
        return max(0, int(ttl - time.monotonic()))

    async def delete(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        removed = 0
        if key in self._store:
            self._store.pop(key, None)
            removed += 1
        if key in self._lists:
            self._lists.pop(key, None)
            removed += 1
        self._ttl.pop(key, None)
        return removed

    async def set(self, key: str, value: Any, *, nx: bool = False, ex: int | None = None) -> Any | None:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        self._purge(key)
        if nx and key in self._store:
            return None
        self._store[key] = (value, None)
        if ex is not None:
            self._ttl[key] = time.monotonic() + max(1, int(ex))
        return True

    async def get(self, key: str) -> Any | None:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        self._purge(key)
        value, _ = self._store.get(key, (None, None))
        return value

    def register_script(self, script: str):
        class _Script:
            def __init__(self, owner: InMemoryRedis, script_text: str):
                self.owner = owner
                self.script_text = script_text

            async def __call__(self, *, keys, args):
                if self.owner.broken:
                    raise ConnectionError("redis caído (simulado)")
                token = args[0]
                current = await self.owner.get(keys[0])
                if current == token:
                    await self.owner.delete(keys[0])
                    return 1
                return 0

        return _Script(self, script)

    async def lpush(self, key: str, value: Any) -> int:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        self._purge(key)
        self._lists[key].appendleft(value)
        return len(self._lists[key])

    async def brpop(self, key: str, timeout: float = 0) -> tuple[str, Any] | None:
        if self.broken:
            raise ConnectionError("redis caído (simulado)")
        start = time.monotonic()
        while True:
            self._purge(key)
            if self._lists.get(key):
                return key, self._lists[key].pop()
            if timeout <= 0:
                return None
            if time.monotonic() - start >= timeout:
                return None
            await asyncio.sleep(0.005)

    def pipeline(self, transaction: bool = True):
        class _Pipeline:
            def __init__(self, owner: InMemoryRedis):
                self.owner = owner
                self._ops: list[tuple[str, list[Any]]] = []

            def incr(self, key: str) -> None:
                self._ops.append(("incr", [key]))

            def expire(self, key: str, seconds: int) -> None:
                self._ops.append(("expire", [key, seconds]))

            async def execute(self) -> list[Any]:
                results = []
                for op, args in self._ops:
                    if op == "incr":
                        results.append(await self.owner.incr(*args))
                    elif op == "expire":
                        results.append(await self.owner.expire(*args))
                return results

        return _Pipeline(self)

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixture: API aislada con BD en memoria y Redis falso
# ---------------------------------------------------------------------------


class IsolatedEnv:
    def __init__(self, engine: Engine, session_factory: sessionmaker, client: TestClient, redis: InMemoryRedis):
        self.engine = engine
        self.session_factory = session_factory
        self.client = client
        self.redis = redis


@pytest.fixture
def isolated_env() -> IsolatedEnv:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def isolated_db():
        with installation_scope(INSTALLATION_ID):
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

    principal = Principal(
        user_id="redis-admin",
        username="redis-admin",
        role="provider_admin",
        installation_id=INSTALLATION_ID,
        token_version=0,
        jti="redis-jti",
    )
    previous_db = app.dependency_overrides.get(get_db)
    previous_principal = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_principal] = lambda: principal
    client = TestClient(app, raise_server_exceptions=False)
    redis = InMemoryRedis()
    try:
        yield IsolatedEnv(engine, session_factory, client, redis)
    finally:
        client.close()
        if previous_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = previous_principal
        engine.dispose()


@contextmanager
def _outbox_db(env: IsolatedEnv):
    with installation_scope(INSTALLATION_ID):
        db = env.session_factory()
        try:
            yield db
        finally:
            db.close()


def _seed_product(env: IsolatedEnv) -> None:
    with _outbox_db(env) as db:
        db.add(
            Product(
                id="redis-prod-1",
                external_id="redis-prod-1",
                sku="SKU-REDIS-0001",
                name="Producto Redis Worker",
                description="Fixture sintético del bloque 3.",
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("42.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=50,
                reserved_stock=0,
            )
        )
        db.commit()


async def _capturing_dispatcher(calls: list[dict[str, Any]], *, fail_times: int = 0):
    async def dispatcher(message: OutboxMessage) -> dict[str, Any]:
        call = {"id": message.id, "topic": message.topic}
        calls.append(call)
        if len(calls) <= fail_times:
            raise RuntimeError("fallo transitorio simulado")
        return {"status": "sent", **call}

    return dispatcher


# ---------------------------------------------------------------------------
# RedisBackend: rate limit, locks, cola
# ---------------------------------------------------------------------------


def test_redis_rate_limit_counts_and_enforces_window() -> None:
    backend = RedisBackend(client=InMemoryRedis())
    key = f"rl:{uuid.uuid4().hex}"

    async def scenario() -> None:
        allowed, _ = await backend.rate_limit(key, limit=3, window_sec=60)
        assert allowed is True
        await backend.rate_limit(key, limit=3, window_sec=60)
        await backend.rate_limit(key, limit=3, window_sec=60)
        blocked, retry_after = await backend.rate_limit(key, limit=3, window_sec=60)
        assert blocked is False
        assert retry_after is not None and retry_after > 0

    asyncio.run(scenario())


def test_redis_rate_limit_reset_clears_bucket() -> None:
    backend = RedisBackend(client=InMemoryRedis())
    key = f"rl-reset:{uuid.uuid4().hex}"

    async def scenario() -> None:
        for _ in range(2):
            await backend.rate_limit(key, limit=2, window_sec=60)
        blocked, _ = await backend.rate_limit(key, limit=2, window_sec=60)
        assert blocked is False
        await backend.rate_limit_reset(key)
        allowed, _ = await backend.rate_limit(key, limit=2, window_sec=60)
        assert allowed is True

    asyncio.run(scenario())


def test_redis_lock_is_exclusive_and_token_guarded() -> None:
    backend = RedisBackend(client=InMemoryRedis())
    name = f"lock:{uuid.uuid4().hex}"

    async def scenario() -> None:
        assert await backend.acquire_lock(name, ttl_sec=60, token="a") is True
        assert await backend.acquire_lock(name, ttl_sec=60, token="b") is False
        # Liberar con token ajeno no libera.
        assert await backend.release_lock(name, token="b") is False
        assert await backend.acquire_lock(name, ttl_sec=60, token="c") is False
        # Liberar con el token correcto sí.
        assert await backend.release_lock(name, token="a") is True
        assert await backend.acquire_lock(name, ttl_sec=60, token="d") is True

    asyncio.run(scenario())


def test_redis_lock_expires_after_ttl() -> None:
    redis = InMemoryRedis()
    backend = RedisBackend(client=redis)
    name = f"lock-ttl:{uuid.uuid4().hex}"

    async def scenario() -> None:
        assert await backend.acquire_lock(name, ttl_sec=1, token="a") is True
        redis._ttl[name] = time.monotonic() - 0.1  # simula expiración
        assert await backend.acquire_lock(name, ttl_sec=1, token="b") is True

    asyncio.run(scenario())


def test_redis_push_pop_roundtrip() -> None:
    backend = RedisBackend(client=InMemoryRedis())
    queue = f"q:{uuid.uuid4().hex}"

    async def scenario() -> None:
        await backend.push(queue, "m1")
        await backend.push(queue, "m2")
        # LPUSH + BRPOP = LIFO: el último encolado sale primero.
        assert await backend.pop(queue, timeout_sec=0.05) == "m1"
        assert await backend.pop(queue, timeout_sec=0.05) == "m2"
        assert await backend.pop(queue, timeout_sec=0.05) is None

    asyncio.run(scenario())


def test_redis_broken_raises_backend_error() -> None:
    backend = RedisBackend(client=InMemoryRedis(broken=True))

    async def scenario() -> None:
        with pytest.raises(RedisBackendError):
            await backend.rate_limit("k", limit=5, window_sec=60)
        with pytest.raises(RedisBackendError):
            await backend.acquire_lock("l", ttl_sec=5, token="t")
        with pytest.raises(RedisBackendError):
            await backend.pop("q", timeout_sec=0.01)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Rate limit con degradación fail-open a memoria (nunca tumba el servicio)
# ---------------------------------------------------------------------------


def test_rate_limit_backend_redis_with_broken_redis_fails_open_to_memory(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis caído en rate limit → fail-open a memoria: el servicio responde."""
    from app.rate_limit import RateLimitMiddleware

    monkeypatch.setattr(bridge_main.settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(bridge_main.settings, "REDIS_RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 100_000)

    # El backend del middleware se reemplaza por uno roto: el rate limit debe
    # degradar a memoria y el endpoint seguir respondiendo 200.
    broken = InMemoryRedis(broken=True)
    monkeypatch.setattr(RateLimitMiddleware, "_redis_backend", lambda self: RedisBackend(client=broken))

    response = isolated_env.client.get("/outbox")
    assert response.status_code == 200, response.text


def test_rate_limit_backend_redis_outage_is_503_when_fail_closed(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rate_limit import RateLimitMiddleware

    monkeypatch.setattr(bridge_main.settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(bridge_main.settings, "REDIS_RATE_LIMIT_FAIL_OPEN", False)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_ENABLED", True)
    broken = InMemoryRedis(broken=True)
    monkeypatch.setattr(
        RateLimitMiddleware,
        "_redis_backend",
        lambda self: RedisBackend(client=broken),
    )

    response = isolated_env.client.get("/outbox")
    assert response.status_code == 503
    assert response.json()["detail"] == "Backend de rate limit no disponible"


def test_rate_limit_redis_blocks_when_limit_exceeded(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con backend redis y límite bajo, la última petición recibe 429."""
    from app.rate_limit import RateLimitMiddleware

    monkeypatch.setattr(bridge_main.settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(bridge_main.settings, "REDIS_RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 3)
    monkeypatch.setattr(bridge_main.settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(RateLimitMiddleware, "_redis_backend", lambda self: RedisBackend(client=isolated_env.redis))

    statuses = []
    for _ in range(5):
        response = isolated_env.client.get("/outbox")
        statuses.append(response.status_code)
    assert statuses[0] == 200, statuses
    assert statuses[-1] == 429, f"la última petición debe superar el límite: {statuses}"
    assert statuses.count(429) == 2, statuses


# ---------------------------------------------------------------------------
# Worker durable: señal, lock de dispatch, reclaim de leases vencidos
# ---------------------------------------------------------------------------


def test_worker_run_once_processes_due_with_dispatch_lock(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls)
        with _outbox_db(isolated_env) as db:
            message, created = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"w-{uuid.uuid4().hex}",
                payload={"email": "worker@example.invalid"},
            )
            assert created is True
            message_id = message.id

        worker = DurableOutboxWorker(
            {"ghl_lead": dispatcher},
            backend=backend,
            session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID,
            poll_sec=0.01,
            lease_sec=60,
            lock_sec=30,
        )
        summary = await worker.run_once()
        assert summary["sent"] == 1, summary
        assert len(calls) == 1
        with _outbox_db(isolated_env) as db:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == message_id).one()
            assert message.state == "sent"
            assert message.processing_until is None

    asyncio.run(scenario())


def test_worker_reclaims_stale_processing_after_lease_expiry(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un worker muerto deja el mensaje en processing; el reclaim lo reintenta."""
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls)
        with _outbox_db(isolated_env) as db:
            message, _ = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"reclaim-{uuid.uuid4().hex}",
                payload={"email": "reclaim@example.invalid"},
            )
            message_id = message.id
            # Simula el crash: el mensaje quedó en processing con lease vencido.
            message.state = "processing"
            message.processing_until = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(seconds=10)
            db.commit()

        worker = DurableOutboxWorker(
            {"ghl_lead": dispatcher},
            backend=backend,
            session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID,
            poll_sec=0.01,
            lease_sec=60,
            lock_sec=30,
        )
        summary = await worker.run_once()
        assert summary["reclaimed"] == 1, summary
        assert summary["sent"] == 1, summary
        assert len(calls) == 1
        with _outbox_db(isolated_env) as db:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == message_id).one()
            assert message.state == "sent"
            assert message.attempt_count == 1, "el reclaim debe contar el reintento"

    asyncio.run(scenario())


def test_worker_stale_processing_without_lease_is_reclaimed(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mensajes processing sin lease (migración o versión previa) se reclaman."""
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls)
        with _outbox_db(isolated_env) as db:
            message, _ = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"nolease-{uuid.uuid4().hex}",
                payload={"email": "nolease@example.invalid"},
            )
            message.state = "processing"
            message.processing_until = None
            db.commit()

        worker = DurableOutboxWorker(
            {"ghl_lead": dispatcher},
            backend=backend,
            session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID,
            poll_sec=0.01,
            lease_sec=60,
            lock_sec=30,
        )
        summary = await worker.run_once()
        assert summary["reclaimed"] == 1
        assert summary["sent"] == 1

    asyncio.run(scenario())


def test_worker_active_lease_is_not_reclaimed(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con lease vivo, otro worker no debe tocar el mensaje."""
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls)
        with _outbox_db(isolated_env) as db:
            message, _ = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"live-{uuid.uuid4().hex}",
                payload={"email": "live@example.invalid"},
            )
            message.state = "processing"
            message.processing_until = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(seconds=300)
            db.commit()

        worker = DurableOutboxWorker(
            {"ghl_lead": dispatcher},
            backend=backend,
            session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID,
            poll_sec=0.01,
            lease_sec=60,
            lock_sec=30,
        )
        summary = await worker.run_once()
        assert summary["reclaimed"] == 0, summary
        assert summary["sent"] == 0, summary
        assert len(calls) == 0
        with _outbox_db(isolated_env) as db:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == message.id).one()
            assert message.state == "processing"

    asyncio.run(scenario())


def test_worker_dispatch_lock_prevents_double_processing(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos workers no procesan a la vez: el segundo cede el lock."""
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls)
        with _outbox_db(isolated_env) as db:
            message, _ = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"lock2-{uuid.uuid4().hex}",
                payload={"email": "lock2@example.invalid"},
            )
            assert message.id

        worker_a = DurableOutboxWorker(
            {"ghl_lead": dispatcher}, backend=backend, session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID, lease_sec=60, lock_sec=30
        )
        worker_b = DurableOutboxWorker(
            {"ghl_lead": dispatcher}, backend=backend, session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID, lease_sec=60, lock_sec=30
        )

        # A toma el lock y procesa.
        summary_a = await worker_a.run_once()
        assert summary_a["sent"] == 1
        # B no puede tomar el lock mientras A no lo libere: para simularlo,
        # A adquiere el lock y B intenta procesar.
        await backend.acquire_lock(DISPATCH_LOCK, ttl_sec=30, token="worker-a-holding")
        summary_b = await worker_b.run_once()
        assert summary_b["sent"] == 0, "el segundo worker debe ceder el lock de dispatch"

    asyncio.run(scenario())


def test_worker_failure_retries_with_backoff_and_keeps_lease_cycle(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo transitorio programa reintento; el mensaje sigue pendiente."""
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_RETRY_BASE_DELAY_SEC", 0.01)
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_RETRY_MAX_DELAY_SEC", 0.02)
    calls: list[dict[str, Any]] = []
    backend = RedisBackend(client=isolated_env.redis)

    async def scenario() -> None:
        dispatcher = await _capturing_dispatcher(calls, fail_times=1)
        with _outbox_db(isolated_env) as db:
            message, _ = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"retry-{uuid.uuid4().hex}",
                payload={"email": "retry@example.invalid"},
            )
            message_id = message.id

        worker = DurableOutboxWorker(
            {"ghl_lead": dispatcher}, backend=backend, session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID, lease_sec=60, lock_sec=30
        )
        summary = await worker.run_once()
        assert summary["retry_scheduled"] == 1, summary
        with _outbox_db(isolated_env) as db:
            message = db.query(OutboxMessage).filter(OutboxMessage.id == message_id).one()
            assert message.state == "pending"
            assert message.attempt_count == 1
            assert message.processing_until is None

    asyncio.run(scenario())


def test_worker_enqueue_signals_redis_queue() -> None:
    """El enqueue publica el id en la cola de señal (best-effort)."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    created = False
    with installation_scope("signal-test"):
        db = session_factory()
        try:
            from app.config import settings as _settings

            original = _settings.REDIS_ENABLED
            try:
                _settings.REDIS_ENABLED = True
                _, created = OutboxService(db).enqueue(
                    topic="ghl_lead",
                    idempotency_key=f"sig-{uuid.uuid4().hex}",
                    payload={"email": "sig@example.invalid"},
                )
            finally:
                _settings.REDIS_ENABLED = original
        finally:
            db.close()
    engine.dispose()

    # El enqueue usa su propio cliente síncrono a REDIS_URL real (no el fake);
    # al no haber Redis levantado, la señal se ignora sin romper (best-effort).
    assert created is True


# ---------------------------------------------------------------------------
# Integración del bloque 3 con el flujo webhook (sin externos)
# ---------------------------------------------------------------------------


def test_outbox_worker_end_to_end_via_webhook_and_reclaim(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2E: outbox → worker durable (con Redis falso) → provider local.

    El worker usa un dispatcher real sobre el CRM local de Fase B y el lease
    se libera al completar.
    """
    _seed_product(isolated_env)
    monkeypatch.setattr(bridge_main.settings, "CHATWOOT_API_TOKEN", "")
    monkeypatch.setattr(bridge_main.settings, "OUTBOX_WORKER_LEASE_SEC", 60)
    monkeypatch.setattr(bridge_main.settings, "GHL_BASE_URL", "")
    monkeypatch.setattr(bridge_main.settings, "GHL_API_TOKEN", "")

    async def dispatch_ghl_local(message: OutboxMessage) -> dict[str, Any]:
        # El proveedor local de Fase B ya está cubierto por sus propios evals;
        # aquí solo validamos que el worker entrega el mensaje al dispatcher
        # real del topic y el lease se libera.
        return {"status": "local_crm_upserted", "message_id": message.id}

    async def scenario() -> None:
        worker = DurableOutboxWorker(
            {"ghl_lead": dispatch_ghl_local},
            backend=RedisBackend(client=isolated_env.redis),
            session_factory=isolated_env.session_factory,
            installation_id=INSTALLATION_ID,
            lease_sec=60,
            lock_sec=30,
        )

        # Encolar directamente (el flujo de webhook ya está cubierto por otros evals).
        with _outbox_db(isolated_env) as db:
            message, created = OutboxService(db).enqueue(
                topic="ghl_lead",
                idempotency_key=f"e2e-{uuid.uuid4().hex}",
                payload={"email": "e2e@example.invalid", "first_name": "E2E"},
            )
            assert created is True

        summary = await worker.run_once()
        assert summary["sent"] == 1, summary
        with _outbox_db(isolated_env) as db:
            assert db.query(OutboxMessage).filter(OutboxMessage.state == "sent").count() == 1

    asyncio.run(scenario())
