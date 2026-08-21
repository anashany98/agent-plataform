"""Evals D-029: ciclo de vida de datos por instalación (export/erase/retención/legal hold).

Cobertura:

- Export completo: el volcado incluye clientes, catálogo, presupuestos,
  RAG, idempotencia y outbox con conteos correctos, sin credenciales de
  usuario ni AuditLog.
- Export sin datos: conteos a cero sin error.
- Erase inmediato (retention_days=0): elimina todos los datos operativos,
  preserva AuditLog y usuarios, y registra ``lifecycle.erase``.
- Erase con retención: los datos sobreviven hasta el vencimiento y
  ``process_due_erases`` completa el borrado.
- Legal hold: bloquea la solicitud de erase y el procesamiento de
  borrados vencidos (``lifecycle.erase_skipped`` auditado).
- Aislamiento: el ciclo de vida de una instalación no toca los datos de
  otra instalación en la misma base de datos.

Hermetismo: SQLite efímero por test, fixtures sintéticos y sin red.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from app.database import Base
from app.installation_context import installation_scope
from app.models.models import (
    AuditLog,
    Customer,
    IdempotencyRecord,
    InstallationLifecycle,
    OutboxMessage,
    Product,
    Quote,
    RAGChunk,
    RAGDocument,
)
from app.services.lifecycle import LegalHoldActive, LifecycleService
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION_A = "lifecycle-instalacion-a"
INSTALLATION_B = "lifecycle-instalacion-b"
ACTOR = "operador-lifecycle"


@dataclass
class LifecycleEnv:
    engine: Engine
    session_factory: sessionmaker


@pytest.fixture
def lifecycle_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LifecycleEnv:
    from app import main as bridge_main

    monkeypatch.setattr(bridge_main.settings, "RAG_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        bridge_main.settings,
        "AUTOMATION_EMAIL_DIR",
        str(tmp_path / "emails"),
    )
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield LifecycleEnv(engine=engine, session_factory=session_factory)
    finally:
        engine.dispose()


@contextmanager
def _session(env: LifecycleEnv, installation_id: str):
    with installation_scope(installation_id):
        db = env.session_factory()
        try:
            yield db
        finally:
            db.close()


def _seed_operational_data(env: LifecycleEnv, installation_id: str, *, tmp_path: Path) -> dict[str, str]:
    """Crea un fixture operativo completo dentro de la instalación dada."""

    upload_dir = Path(str(tmp_path)) / installation_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    document_path = upload_dir / "manual-operativo.txt"
    document_path.write_text("Contenido operativo de la instalación.", encoding="utf-8")
    spool_dir = tmp_path / "emails"
    spool_dir.mkdir(parents=True, exist_ok=True)
    tenant_key = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()[:16]
    spool_path = spool_dir / f"{tenant_key}__queued-for-manual-delivery-{uuid.uuid4().hex[:12]}.json"
    spool_path.write_text(
        json.dumps(
            {
                "provider": "local_spool",
                "delivery_status": "queued_for_manual_delivery",
                "installation_id": installation_id,
                "to": f"cliente-{installation_id}@example.invalid",
                "subject": "Recordatorio pendiente",
                "body": "Entrega manual pendiente.",
                "retention_days": 30,
            }
        ),
        encoding="utf-8",
    )

    ids = {
        "customer": f"cust-{installation_id}",
        "product": f"prod-{installation_id}",
        "quote": f"quote-{installation_id}",
        "document": f"doc-{installation_id}",
        "idempotency": f"idem-{installation_id}",
        "outbox": f"outbox-{installation_id}",
    }
    with _session(env, installation_id) as db:
        db.add(
            Customer(
                id=ids["customer"],
                name=f"Cliente {installation_id}",
                email=f"cliente-{installation_id}@example.invalid",
            )
        )
        db.add(
            Product(
                id=ids["product"],
                external_id=ids["product"],
                sku=f"SKU-{installation_id.upper()}",
                name=f"Producto {installation_id}",
                description="Fixture sintético de ciclo de vida.",
                category="Industrial",
                attributes={},
                source="local",
                base_price=Decimal("50.00"),
                tax_rate=Decimal("0.21"),
                stock_quantity=10,
                reserved_stock=0,
            )
        )
        db.add(
            Quote(
                id=ids["quote"],
                customer_id=ids["customer"],
                confirmation_token=uuid.uuid4().hex,
                confirmation_payload_hash=uuid.uuid4().hex,
                confirmation_expires_at=dt.datetime.now(dt.UTC).replace(tzinfo=None)
                + dt.timedelta(hours=1),
                items=[{"sku": f"SKU-{installation_id.upper()}", "quantity": 1}],
                subtotal=Decimal("50.00"),
                tax_total=Decimal("10.50"),
                shipping_total=Decimal("0.00"),
                grand_total=Decimal("60.50"),
                currency="EUR",
                status="draft",
            )
        )
        db.add(
            RAGDocument(
                id=ids["document"],
                file_path=str(document_path),
                file_name=document_path.name,
                mime_type="text/plain",
                sha256=uuid.uuid4().hex,
                metadata_json={"classification": "internal"},
            )
        )
        db.add(
            RAGChunk(
                id=f"{ids['document']}-chunk-0",
                document_id=ids["document"],
                chunk_index=0,
                text="Contenido operativo de la instalación.",
                embedding=[0.1] * 8,
                metadata_json={},
            )
        )
        db.add(
            IdempotencyRecord(
                idempotency_key=ids["idempotency"],
                state="completed",
                status_code=200,
                attempt_count=1,
                response_body={"status": "success"},
            )
        )
        db.add(
            OutboxMessage(
                id=ids["outbox"],
                topic="lifecycle.test",
                idempotency_key=ids["outbox"],
                payload={"fixture": True},
                state="pending",
                attempt_count=0,
                max_attempts=3,
            )
        )
        db.commit()
    return ids


def _counts(env: LifecycleEnv, installation_id: str) -> dict[str, int]:
    with _session(env, installation_id) as db:
        return {
            "customers": db.query(Customer).count(),
            "products": db.query(Product).count(),
            "quotes": db.query(Quote).count(),
            "rag_documents": db.query(RAGDocument).count(),
            "rag_chunks": db.query(RAGChunk).count(),
            "idempotency_records": db.query(IdempotencyRecord).count(),
            "outbox_messages": db.query(OutboxMessage).count(),
            "audit_logs": db.query(AuditLog).count(),
        }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_includes_all_operational_data_without_credentials(
    lifecycle_env: LifecycleEnv, tmp_path: Path
) -> None:
    ids = _seed_operational_data(lifecycle_env, INSTALLATION_A, tmp_path=tmp_path)

    with _session(lifecycle_env, INSTALLATION_A) as db:
        export = LifecycleService(db, installation_id=INSTALLATION_A).export_installation(
            actor=ACTOR
        )

    assert export["installation_id"] == INSTALLATION_A
    assert export["actor"] == ACTOR
    assert export["counts"]["customers"] == 1
    assert export["counts"]["products"] == 1
    assert export["counts"]["quotes"] == 1
    assert export["counts"]["rag_documents"] == 1
    assert export["counts"]["rag_chunks"] == 1
    assert export["counts"]["idempotency_records"] == 1
    assert export["counts"]["outbox_messages"] == 1
    assert export["counts"]["automation_email_spool"] == 1
    assert export["data"]["automation_email_spool"][0]["installation_id"] == INSTALLATION_A

    assert "users" not in export["data"], "El export nunca incluye credenciales"
    assert "audit_logs" not in export["data"], "El AuditLog queda fuera del volcado"

    customer_row = export["data"]["customers"][0]
    assert customer_row["id"] == ids["customer"]
    assert customer_row["installation_id"] == INSTALLATION_A
    # Los Decimal deben serializarse como string portable.
    quote_row = export["data"]["quotes"][0]
    assert quote_row["grand_total"] == "60.50"

    with _session(lifecycle_env, INSTALLATION_A) as db:
        audits = db.query(AuditLog).filter(AuditLog.event_type == "lifecycle.export").all()
        assert len(audits) == 1, "El export debe quedar auditado"
        state = (
            db.query(InstallationLifecycle)
            .filter(InstallationLifecycle.installation_id == INSTALLATION_A)
            .one()
        )
        assert state.last_export_at is not None


def test_export_without_data_returns_zero_counts(lifecycle_env: LifecycleEnv) -> None:
    with _session(lifecycle_env, INSTALLATION_A) as db:
        export = LifecycleService(db, installation_id=INSTALLATION_A).export_installation(
            actor=ACTOR
        )
    assert all(count == 0 for count in export["counts"].values())
    assert export["data"]["customers"] == []


# ---------------------------------------------------------------------------
# Erase inmediato y con retención
# ---------------------------------------------------------------------------


def test_immediate_erase_removes_operational_data_and_keeps_audit(
    lifecycle_env: LifecycleEnv, tmp_path: Path
) -> None:
    _seed_operational_data(lifecycle_env, INSTALLATION_A, tmp_path=tmp_path)
    document_path = Path(str(tmp_path)) / INSTALLATION_A / "manual-operativo.txt"
    assert document_path.exists()

    with _session(lifecycle_env, INSTALLATION_A) as db:
        result = LifecycleService(db, installation_id=INSTALLATION_A).request_erase(
            actor=ACTOR, reason="solicitud de baja del cliente", retention_days=0
        )

    assert result["executed"] is not None
    tables = result["executed"]["tables"]
    assert tables["customers"] == 1
    assert tables["quotes"] == 1
    assert tables["rag_documents"] == 1
    assert tables["rag_chunks"] == 1
    assert result["executed"]["files_removed"] == 2

    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 0
    assert counts["products"] == 0
    assert counts["quotes"] == 0
    assert counts["rag_documents"] == 0
    assert counts["rag_chunks"] == 0
    assert counts["idempotency_records"] == 0
    assert counts["outbox_messages"] == 0
    assert counts["audit_logs"] >= 1, "El AuditLog nunca se borra"

    assert not document_path.exists(), "El archivo RAG debe eliminarse del disco"
    assert not list((tmp_path / "emails").glob("*.json")), (
        "El erase debe eliminar también el spool de email del tenant"
    )

    with _session(lifecycle_env, INSTALLATION_A) as db:
        erase_audits = db.query(AuditLog).filter(AuditLog.event_type == "lifecycle.erase").all()
        assert len(erase_audits) == 1
        state = (
            db.query(InstallationLifecycle)
            .filter(InstallationLifecycle.installation_id == INSTALLATION_A)
            .one()
        )
        assert state.erase_executed_at is not None
        assert state.erase_after is None


def test_erase_with_retention_keeps_data_until_due(
    lifecycle_env: LifecycleEnv, tmp_path: Path
) -> None:
    _seed_operational_data(lifecycle_env, INSTALLATION_A, tmp_path=tmp_path)

    with _session(lifecycle_env, INSTALLATION_A) as db:
        service = LifecycleService(db, installation_id=INSTALLATION_A)
        result = service.request_erase(
            actor=ACTOR, reason="baja programada", retention_days=30
        )
        assert result["executed"] is None, "Con retención el borrado no es inmediato"
        assert service.process_due_erases(actor=ACTOR) == [], (
            "Antes del vencimiento no se ejecuta ningún borrado"
        )

    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 1 and counts["quotes"] == 1, (
        "Los datos deben sobrevivir durante la ventana de retención"
    )

    with _session(lifecycle_env, INSTALLATION_A) as db:
        state = (
            db.query(InstallationLifecycle)
            .filter(InstallationLifecycle.installation_id == INSTALLATION_A)
            .one()
        )
        # Simulación del vencimiento de la retención.
        state.erase_after = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(
            seconds=1
        )
        db.commit()

    with _session(lifecycle_env, INSTALLATION_A) as db:
        processed = LifecycleService(db, installation_id=INSTALLATION_A).process_due_erases(
            actor=ACTOR
        )
    assert len(processed) == 1
    assert processed[0]["tables"]["customers"] == 1

    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 0
    assert counts["quotes"] == 0


# ---------------------------------------------------------------------------
# Legal hold
# ---------------------------------------------------------------------------


def test_legal_hold_blocks_erase_request_and_due_processing(
    lifecycle_env: LifecycleEnv, tmp_path: Path
) -> None:
    _seed_operational_data(lifecycle_env, INSTALLATION_A, tmp_path=tmp_path)

    with _session(lifecycle_env, INSTALLATION_A) as db:
        service = LifecycleService(db, installation_id=INSTALLATION_A)
        state = service.set_legal_hold(
            active=True, actor=ACTOR, reason="investigación regulatoria"
        )
        assert state["legal_hold"] is True

        with pytest.raises(LegalHoldActive):
            service.request_erase(actor=ACTOR, reason="baja", retention_days=0)

    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 1, "El legal hold impide el borrado inmediato"

    # Simulación: erase programado antes del hold que vence durante el hold.
    with _session(lifecycle_env, INSTALLATION_A) as db:
        row = (
            db.query(InstallationLifecycle)
            .filter(InstallationLifecycle.installation_id == INSTALLATION_A)
            .one()
        )
        row.erase_requested_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        row.erase_after = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(
            seconds=1
        )
        db.commit()

    with _session(lifecycle_env, INSTALLATION_A) as db:
        service = LifecycleService(db, installation_id=INSTALLATION_A)
        assert service.process_due_erases(actor=ACTOR) == []
        skipped = db.query(AuditLog).filter(
            AuditLog.event_type == "lifecycle.erase_skipped"
        ).all()
        assert any(
            (row.details or {}).get("reason") == "legal_hold" for row in skipped
        ), "El bloqueo por legal hold debe quedar auditado"

    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 1, "El borrado vencido no se ejecuta con legal hold"

    # Al levantar el hold, el borrado pendiente se ejecuta.
    with _session(lifecycle_env, INSTALLATION_A) as db:
        service = LifecycleService(db, installation_id=INSTALLATION_A)
        state = service.set_legal_hold(active=False, actor=ACTOR, reason="fin de investigación")
        assert state["legal_hold"] is False
        processed = service.process_due_erases(actor=ACTOR)
    assert len(processed) == 1
    counts = _counts(lifecycle_env, INSTALLATION_A)
    assert counts["customers"] == 0


# ---------------------------------------------------------------------------
# Aislamiento entre instalaciones
# ---------------------------------------------------------------------------


def test_lifecycle_is_isolated_between_installations(
    lifecycle_env: LifecycleEnv, tmp_path: Path
) -> None:
    _seed_operational_data(lifecycle_env, INSTALLATION_A, tmp_path=tmp_path)
    _seed_operational_data(lifecycle_env, INSTALLATION_B, tmp_path=tmp_path)

    with _session(lifecycle_env, INSTALLATION_B) as db:
        export = LifecycleService(db, installation_id=INSTALLATION_B).export_installation(
            actor=ACTOR
        )
        assert export["counts"]["customers"] == 1
        assert all(
            row["installation_id"] == INSTALLATION_B
            for row in export["data"]["customers"]
        ), "El export no puede contener datos de otra instalación"

        result = LifecycleService(db, installation_id=INSTALLATION_B).request_erase(
            actor=ACTOR, reason="baja de la instalación B", retention_days=0
        )
        assert result["executed"]["tables"]["customers"] == 1

    counts_b = _counts(lifecycle_env, INSTALLATION_B)
    assert counts_b["customers"] == 0

    counts_a = _counts(lifecycle_env, INSTALLATION_A)
    assert counts_a["customers"] == 1, (
        "El ciclo de vida de la instalación B no puede tocar los datos de la A"
    )
    assert counts_a["quotes"] == 1
    assert counts_a["rag_documents"] == 1
    tenant_a_key = hashlib.sha256(INSTALLATION_A.encode("utf-8")).hexdigest()[:16]
    tenant_b_key = hashlib.sha256(INSTALLATION_B.encode("utf-8")).hexdigest()[:16]
    assert list((tmp_path / "emails").glob(f"{tenant_a_key}__*.json"))
    assert not list((tmp_path / "emails").glob(f"{tenant_b_key}__*.json"))
