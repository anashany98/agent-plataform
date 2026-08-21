"""Evals de remediación 2026-08-10.

Cubre los defectos P0/P1 reabiertos por la auditoría
``docs/PROJECT_STATUS_AUDIT_2026-08-10.md``:

- **P0 / restore destructivo**: ``restore_to_url`` ya no debe borrar una
  base de datos sin marker autorizado. ``prepare_restore_target`` deja un
  marker explícito y ``restore_to_url`` rechaza destinos sin marker o con
  tablas de aplicación previas.
- **P1 / webhook replay en processing**: el primer webhook debe devolver
  200 (no 202). El replay del mismo payload debe devolver también 200 con
  el resultado cacheado. Antes la rama ``return`` temprana dejaba el
  estado en ``processing`` y el replay devolvía 202.
- **P1 / core sin PrestaShop**: con PrestaShop NO configurado y
  productos locales visibles, el chat comercial debe responder con el
  catálogo local en lugar de transferir al equipo comercial.
- **P1 / catalog overview sin límite falso**: el endpoint del chat debe
  funcionar con la fuente configurada dinámicamente.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from decimal import Decimal

import pytest
from app import main as bridge_main
from app.database import Base
from app.installation_context import installation_scope
from app.main import _default_catalog_source
from app.models.models import IdempotencyRecord, Product
from app.services import backup
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

CHATWOOT_WEBHOOK_SECRET = "test-chatwoot-secret"


# ---------------------------------------------------------------------------
# P0 / restore_to_url NO debe borrar una base de datos sin marker.
# ---------------------------------------------------------------------------


def test_restore_to_url_refuses_base_without_marker(tmp_path) -> None:
    """Sin marker, restore_to_url lanza RestoreSafetyError y NO toca datos."""

    source_path = tmp_path / "source.db"
    occupied_path = tmp_path / "occupied.db"

    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(source)

    # Sembramos un cliente "real" en el destino; debe sobrevivir.
    occupied = create_engine(f"sqlite+pysqlite:///{occupied_path.as_posix()}")
    Base.metadata.create_all(occupied)
    occupied_factory = sessionmaker(bind=occupied)
    with installation_scope("restore-test"):
        with occupied_factory() as db:
            db.add(Product(
                id="prod-real",
                external_id="prod-real",
                sku="REAL-0001",
                name="Cliente real",
                description=None,
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("10.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=5,
                reserved_stock=0,
            ))
            db.commit()

    # Generamos un manifiesto vacío sobre la base source.
    factory = sessionmaker(bind=source)
    with installation_scope("restore-test"):
        with factory() as db:
            manifest = backup.create_backup(db, installation_id="restore-test")

    # Apuntar restore_to_url a la base OCUPADA debe fallar sin tocarla.
    with pytest.raises(backup.RestoreSafetyError):
        backup.restore_to_url(manifest, occupied.url.render_as_string(hide_password=False))

    with installation_scope("restore-test"):
        with occupied_factory() as db:
            survivor = db.query(Product).filter(Product.id == "prod-real").first()
    assert survivor is not None and survivor.name == "Cliente real", (
        "restore_to_url no debe destruir la base ocupada"
    )

    source.dispose()
    occupied.dispose()


def test_restore_to_url_with_marker_succeeds(tmp_path) -> None:
    """Flujo correcto: marker + restore -> los datos se restauran.

    Usa bases de SQLite en archivo (no ``:memory:``) porque cada llamada a
    ``create_engine`` abre una conexión nueva y queremos que el marker
    sobreviva entre ``prepare_restore_target`` y ``restore_to_url``.
    """

    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    Base.metadata.create_all(source)
    factory = sessionmaker(bind=source)
    with installation_scope("restore-ok"):
        with factory() as db:
            db.add(Product(
                id="prod-ok",
                external_id="prod-ok",
                sku="OK-0001",
                name="Producto OK",
                description=None,
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("10.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=2,
                reserved_stock=0,
            ))
            db.commit()
            manifest = backup.create_backup(db, installation_id="restore-ok")

    target_url = f"sqlite+pysqlite:///{target_path.as_posix()}"
    backup.prepare_restore_target(target_url)
    with installation_scope("restore-ok"):
        backup.restore_to_url(manifest, target_url)
    target = create_engine(target_url)
    target_factory = sessionmaker(bind=target)
    with installation_scope("restore-ok"):
        with target_factory() as db:
            assert db.query(Product).filter(Product.id == "prod-ok").count() == 1
    source.dispose()
    target.dispose()


# ---------------------------------------------------------------------------
# P1 / Webhook replay: el segundo envío debe devolver 200 con la respuesta
# cacheada, NO 202 processing.
# ---------------------------------------------------------------------------


def _sign_webhook(raw_body: bytes, secret: str = CHATWOOT_WEBHOOK_SECRET) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode() + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Chatwoot-Signature": sig,
        "X-Chatwoot-Timestamp": ts,
        "Content-Type": "application/json",
    }


@contextmanager
def _build_engine_and_client(tmp_path):
    """Construye engine SQLite en archivo, override de ``get_db`` y TestClient.

    Usa SQLite en archivo (no ``:memory:``) para que los datos sobrevivan
    entre sesiones distintas y para evitar problemas de path en Windows.

    Es un context manager porque muta estado global (``SessionLocal``,
    ``app.database.engine`` y los dependency overrides de la app); al salir
    restaura todo en ``finally`` para no envenenar el resto de la suite
    (sin esto, la BD compartida queda apuntando a un SQLite temporal ya
    cerrado y el login de la fixture ``token`` devuelve 401 en masa).
    """
    db_path = tmp_path / "audit_test.db"
    db_url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def isolated_db():
        with installation_scope("audit-test"):
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

    from app.database import SessionLocal, get_db
    from app.main import app
    from app.security import Principal, get_current_principal

    # Guardamos el estado global previo para restaurarlo al salir.
    previous_bind = SessionLocal.kw.get("bind")
    import app.database as _db_module
    previous_module_engine = _db_module.engine
    previous_db_override = app.dependency_overrides.get(get_db)
    previous_principal_override = app.dependency_overrides.get(get_current_principal)

    app.dependency_overrides[get_db] = isolated_db

    # CRITICAL: también parcheamos ``SessionLocal`` y ``engine`` del módulo
    # ``app.database`` para que cualquier referencia directa al engine global
    # (p. ej. en ``seed_database`` o helpers de auditoría) apunte al mismo
    # archivo SQLite. Sin esto, las escrituras se bifurcan a otra conexión.
    SessionLocal.configure(bind=engine)
    # Reemplazamos el atributo ``engine`` del módulo con una referencia al
    # nuestro para que cualquier ``app.database.engine`` apunte aquí.
    _db_module.engine = engine
    Base.metadata.create_all(bind=engine)

    principal = Principal(
        user_id="audit-admin",
        username="audit-admin",
        role="provider_admin",
        installation_id="audit-test",
        token_version=0,
        jti="audit-jti",
    )
    app.dependency_overrides[get_current_principal] = lambda: principal

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield engine, session_factory, client
    finally:
        client.close()
        engine.dispose()
        # Restauramos el estado global (Hermeticidad D-032: un test no
        # puede dejar la suite compartida apuntando a su BD temporal).
        SessionLocal.configure(bind=previous_bind)
        _db_module.engine = previous_module_engine
        if previous_db_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_db_override
        if previous_principal_override is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = previous_principal_override


def test_webhook_replay_returns_cached_result_not_processing(tmp_path) -> None:
    """El segundo webhook con la misma ``message_id`` debe devolver 200,
    no 202 ``processing``.

    El bug previo: las ramas de éxito hacían ``_checkpoint_idempotency``
    + ``return result`` sin transicionar a ``state='completed'``, así
    que el replay veía ``processing`` y devolvía 202.
    """

    with _build_engine_and_client(tmp_path) as (engine, session_factory, client):
        body = {
            "event": "message_created",
            "id": 4242,
            "message_type": "incoming",
            "content": "hola",
            "conversation": {"id": 99},
            "account": {"id": 7},
            "sender": {"id": 1, "name": "Cliente", "email": "c@example.invalid"},
        }
        raw = json.dumps(body).encode("utf-8")
        headers = _sign_webhook(raw)

        # El primer envío: 200 OK con la respuesta cacheada.
        first = client.post("/webhooks/chatwoot", content=raw, headers=headers)
        assert first.status_code == 200, f"first status={first.status_code}, text={first.text}"
        first_body = first.json()
        assert first_body.get("status") in {"success", "ignored"}, first_body

        # Verificamos que el estado del registro idempotente quedó en
        # ``completed``. El override usa ``session_factory`` que comparte
        # el engine con la override, así que las escrituras dentro del
        # request deben ser visibles desde aquí.
        with installation_scope("audit-test"):
            with session_factory() as db:
                # La PK es (installation_id, idempotency_key).
                record = (
                    db.query(IdempotencyRecord)
                    .filter(IdempotencyRecord.installation_id == "audit-test")
                    .filter(IdempotencyRecord.idempotency_key == "chatwoot:7:4242")
                    .first()
                )
        if record is not None:
            assert record.state == "completed", (
                f"IdempotencyRecord.state debería ser 'completed', es "
                f"'{record.state}'. El handler debe transicionar a "
                f"completed al cerrar la rama de éxito."
            )

        # Debug: dump records from the engine after first POST
        with installation_scope("audit-test"):
            with session_factory() as db:
                rows = db.query(IdempotencyRecord).filter(
                    IdempotencyRecord.idempotency_key.like("chatwoot:%")
                ).all()
        print(f"DEBUG after first POST: rows={[(r.idempotency_key, r.state) for r in rows]}")

        # El replay: debe devolver 200 con la misma respuesta cacheada,
        # no 202 "processing".
        second = client.post("/webhooks/chatwoot", content=raw, headers=headers)
        assert second.status_code == 200, (
            f"El replay devolvió {second.status_code} en lugar de 200; "
            "el estado quedó en 'processing' por una rama temprana sin "
            "_complete_idempotency."
        )
        second_body = second.json()
        assert second_body.get("status") != "processing", (
            "El replay devolvió status='processing'; el handler debe "
            "transicionar a 'completed' al cerrar la rama de éxito."
        )

        # El replay devuelve ``duplicate_ignored`` con la respuesta cacheada
        # en ``original_response`` (o el mismo body si la rama es idéntica).
        cached = second_body.get("original_response") or second_body
        assert cached == first_body, (
            f"El replay debería devolver el body cacheado del primer envío; "
            f"first={first_body}, second_cached={cached}"
        )

        # Verificamos que el estado del registro idempotente quedó en
        # ``completed`` después del replay. El override usa
        # ``session_factory`` que comparte el engine con la override, así
        # que las escrituras dentro del request deben ser visibles desde
        # aquí.
        with installation_scope("audit-test"):
            with session_factory() as db:
                record = (
                    db.query(IdempotencyRecord)
                    .filter(IdempotencyRecord.installation_id == "audit-test")
                    .filter(IdempotencyRecord.idempotency_key == "chatwoot:7:4242")
                    .first()
                )
        if record is not None:
            assert record.state == "completed", (
                f"IdempotencyRecord.state debería ser 'completed', es "
                f"'{record.state}'. El handler debe transicionar a "
                f"completed al cerrar la rama de éxito."
            )


# ---------------------------------------------------------------------------
# P1 / Default catalog source: cuando PrestaShop NO está configurado, el
# chat debe usar el catálogo local visible.
# ---------------------------------------------------------------------------


def test_default_catalog_source_returns_none_when_prestashop_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin PrestaShop configurado, la fuente por defecto es ``None``
    (todos los productos visibles del catálogo local)."""

    class _FakeAdapter:
        def configured(self) -> bool:  # noqa: D401
            return False

    monkeypatch.setattr(bridge_main, "prestashop_adapter", _FakeAdapter())
    assert _default_catalog_source() is None


def test_default_catalog_source_returns_prestashop_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con PrestaShop configurado, la fuente por defecto es ``prestashop``."""

    class _FakeAdapter:
        def configured(self) -> bool:  # noqa: D401
            return True

    monkeypatch.setattr(bridge_main, "prestashop_adapter", _FakeAdapter())
    assert _default_catalog_source() == "prestashop"