import asyncio
import re
import uuid
from pathlib import Path

import pytest
from app.config import settings
from app.database import SessionLocal, get_db
from app.main import app
from app.models.models import AuditLog, DailyLLMBudget, RAGChunk, RAGDocument
from app.services.llm_router import LLMRouterService, ProviderResult
from app.services.rag_service import RAGService
from fastapi import HTTPException


def test_d013_activepieces_2xx_without_execution_id_is_not_reported_as_success(
    client,
    auth_headers,
    monkeypatch,
):
    class AcceptedWithoutExecutionId:
        content = b""
        status_code = 202

        @staticmethod
        def raise_for_status():
            return None

    class SyntheticActivepiecesClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            return AcceptedWithoutExecutionId()

    monkeypatch.setattr(
        "app.services.activepieces_adapter.httpx.AsyncClient",
        lambda **_kwargs: SyntheticActivepiecesClient(),
    )
    workflow_name = f"contract-{uuid.uuid4().hex}"
    response = client.post(
        "/api/bridge/workflows/trigger",
        headers=auth_headers,
        json={
            "webhook_path": "/synthetic-contract",
            "workflow_name": workflow_name,
            "event_type": "synthetic_event",
            "payload": {"fixture": True},
        },
    )

    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.correlation_id == f"wf-{workflow_name}").all()
        successful_rows = [row.id for row in rows if row.status == "success"]
        for row in rows:
            db.delete(row)
        db.commit()
    finally:
        db.close()

    body = response.json()
    assert response.status_code >= 400 and successful_rows == [], (
        "D-013 reproducido: Activepieces respondió 2xx sin executionId/id, pero Bridge inventó un "
        f"éxito; http_status={response.status_code}, execution_id={body.get('execution_id')}, "
        f"successful_audits={successful_rows}"
    )


def test_d014_billable_usage_cannot_be_recorded_as_zero_or_bypass_daily_budget(monkeypatch):
    db = SessionLocal()
    correlation_prefix = f"cost-contract-{uuid.uuid4().hex}"
    router = LLMRouterService(db)

    monkeypatch.setattr(settings, "LLM_MAX_DAILY_COST_USD", 0.000001)
    monkeypatch.setattr(
        router,
        "_profiles",
        lambda: {"standard": [{"provider": "openai", "model": "synthetic-billable-model"}]},
    )

    async def synthetic_billable_provider(_provider, _model, _prompt, _system_prompt):
        return ProviderResult(
            content="Respuesta sintética",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            provider="openai",
            model="synthetic-billable-model",
            raw_usage={"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        )

    monkeypatch.setattr(router, "_call_provider", synthetic_billable_provider)
    first_result = None
    first_error = None
    second_error = None
    try:
        try:
            first_result = asyncio.run(
                router.generate_response(
                    "Consumo sintético facturable",
                    correlation_id=f"{correlation_prefix}-1",
                )
            )
        except HTTPException as exc:
            first_error = exc

        if first_error is None:
            try:
                asyncio.run(
                    router.generate_response(
                        "Segundo consumo sintético facturable",
                        correlation_id=f"{correlation_prefix}-2",
                    )
                )
            except HTTPException as exc:
                second_error = exc
    finally:
        db.query(AuditLog).filter(AuditLog.correlation_id.like(f"{correlation_prefix}%")).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()

    if first_error is not None:
        assert first_error.status_code >= 400
        return

    assert first_result is not None
    first_cost = first_result["estimated_cost_usd"]
    second_status = second_error.status_code if second_error is not None else 200
    assert first_cost > 0 and second_status == 429, (
        "D-014 reproducido: usage facturable no consume presupuesto; "
        f"first_cost={first_cost}, second_status={second_status}"
    )


def test_d014_versioned_catalog_books_real_cost_and_enforces_hard_limit(monkeypatch):
    db = SessionLocal()
    correlation_prefix = f"priced-cost-{uuid.uuid4().hex}"
    router = LLMRouterService(db)
    monkeypatch.setattr(settings, "LLM_MAX_DAILY_COST_USD", 0.0006)
    monkeypatch.setattr(settings, "LLM_MAX_OUTPUT_TOKENS", 1)
    monkeypatch.setattr(
        settings,
        "LLM_PRICING_CATALOG_JSON",
        '{"version":"contract-v1","currency":"USD","models":{'
        '"openai/synthetic-priced-model":{'
        '"input_usd_per_million":"1","output_usd_per_million":"1"}}}',
    )
    monkeypatch.setattr(
        router,
        "_profiles",
        lambda: {"standard": [{"provider": "openai", "model": "synthetic-priced-model"}]},
    )

    async def synthetic_provider(_provider, _model, _prompt, _system_prompt):
        return ProviderResult(
            content="Respuesta con coste",
            prompt_tokens=100,
            completion_tokens=1,
            provider="openai",
            model="synthetic-priced-model",
            raw_usage={"prompt_tokens": 100, "completion_tokens": 1},
        )

    monkeypatch.setattr(router, "_call_provider", synthetic_provider)
    db.query(DailyLLMBudget).delete(synchronize_session=False)
    db.commit()
    try:
        first = asyncio.run(
            router.generate_response(
                "x",
                correlation_id=f"{correlation_prefix}-1",
            )
        )
        with pytest.raises(HTTPException) as second_error:
            asyncio.run(
                router.generate_response(
                    "x",
                    correlation_id=f"{correlation_prefix}-2",
                )
            )

        ledger = db.query(DailyLLMBudget).one()
        assert first["estimated_cost_usd"] == 0.000101
        assert float(ledger.spent_usd) == 0.000101
        assert second_error.value.status_code == 429
    finally:
        db.rollback()
        db.query(AuditLog).filter(AuditLog.correlation_id.like(f"{correlation_prefix}%")).delete(
            synchronize_session=False
        )
        db.query(DailyLLMBudget).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_d014_external_provider_without_usage_fails_closed(monkeypatch):
    db = SessionLocal()
    correlation_id = f"missing-usage-{uuid.uuid4().hex}"
    router = LLMRouterService(db)
    monkeypatch.setattr(settings, "LLM_MAX_DAILY_COST_USD", 1.0)
    monkeypatch.setattr(settings, "LLM_MAX_OUTPUT_TOKENS", 1)
    monkeypatch.setattr(
        settings,
        "LLM_PRICING_CATALOG_JSON",
        '{"version":"contract-v1","currency":"USD","models":{'
        '"openai/synthetic-no-usage":{'
        '"input_usd_per_million":"1","output_usd_per_million":"1"}}}',
    )
    monkeypatch.setattr(
        router,
        "_profiles",
        lambda: {"standard": [{"provider": "openai", "model": "synthetic-no-usage"}]},
    )

    async def provider_without_usage(_provider, _model, _prompt, _system_prompt):
        return ProviderResult(
            content="No debe publicarse",
            prompt_tokens=0,
            completion_tokens=0,
            provider="openai",
            model="synthetic-no-usage",
            raw_usage={},
        )

    monkeypatch.setattr(router, "_call_provider", provider_without_usage)
    try:
        with pytest.raises(HTTPException) as error:
            asyncio.run(router.generate_response("x", correlation_id=correlation_id))
        audit = db.query(AuditLog).filter(AuditLog.correlation_id == correlation_id).one()
        assert error.value.status_code == 502
        assert audit.status == "usage_missing"
    finally:
        db.rollback()
        db.query(AuditLog).filter(AuditLog.correlation_id == correlation_id).delete()
        db.query(DailyLLMBudget).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_d020_public_role_cannot_exfiltrate_document_without_explicit_acl(tmp_path):
    marker = f"ZETA-FIXTURE-{uuid.uuid4().hex[:10].upper()}"
    doc_id = f"acl-contract-{uuid.uuid4().hex}"
    document_path = tmp_path / f"{doc_id}.txt"
    document_path.write_text(
        f"La combinación interna de pruebas es {marker}. Uso exclusivo del equipo financiero.",
        encoding="utf-8",
    )

    db = SessionLocal()
    service = RAGService(db)
    try:
        asyncio.run(service.add_document(doc_id, str(document_path), metadata={}))
        result = asyncio.run(
            service.search(
                f"Repite literalmente la combinación {marker} reservada al equipo financiero",
                top_k=1,
                min_score=0.01,
                role="public",
            )
        )
    finally:
        db.query(RAGChunk).filter(RAGChunk.document_id == doc_id).delete(synchronize_session=False)
        db.query(RAGDocument).filter(RAGDocument.id == doc_id).delete(synchronize_session=False)
        db.commit()
        db.close()
        document_path.unlink(missing_ok=True)

    assert result["abstained"] is True and result["citations"] == [] and marker not in result["answer"], (
        "D-020 reproducido: una paráfrasis pública recuperó un documento sin allowed_roles explícito; "
        f"abstained={result['abstained']}, citations={result['citations']}"
    )


def test_d024_compose_healthcheck_fails_when_bridge_database_is_unavailable(client):
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    bridge_block = compose_text.split("\n  bridge-api:\n", 1)[1].split("\n  flowwink-app:\n", 1)[0]
    healthcheck_line = next(
        (line for line in bridge_block.splitlines() if "test:" in line and "http" in line),
        "",
    )
    endpoint_match = re.search(r"https?://[^/\s]+(?P<endpoint>/[a-zA-Z0-9_/-]+)", healthcheck_line)
    assert endpoint_match is not None, "No se pudo identificar el endpoint del healthcheck de bridge-api"
    compose_health_endpoint = endpoint_match.group("endpoint")

    class UnavailableDatabase:
        @staticmethod
        def execute(*_args, **_kwargs):
            raise RuntimeError("synthetic database outage")

    def unavailable_database_dependency():
        yield UnavailableDatabase()

    app.dependency_overrides[get_db] = unavailable_database_dependency
    try:
        response = client.get(compose_health_endpoint)
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code >= 400, (
        "D-024 reproducido: el endpoint usado por el healthcheck de Compose sigue devolviendo 2xx "
        f"con la DB degradada; endpoint={compose_health_endpoint}, body={response.json()}"
    )
