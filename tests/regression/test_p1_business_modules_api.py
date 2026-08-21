"""Contratos backend de módulos persistidos, draft-first y proxy-aware."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.config import settings
from app.database import SessionLocal
from app.models.models import (
    AgentDefinition,
    ApprovalRequest,
    AuditLog,
    IdempotencyRecord,
    InvoiceDraft,
    LandingPage,
    Order,
    Product,
    Quote,
    ScheduledTask,
    SEOProject,
    StockReservation,
    WikiPage,
)
from sqlalchemy import update


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _cleanup(*, ids: list[str], key_fragment: str) -> None:
    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.id.in_(ids)).delete(synchronize_session=False)
        db.query(ApprovalRequest).filter(
            (ApprovalRequest.id.in_(ids)) | (ApprovalRequest.target_key.in_(ids))
        ).delete(synchronize_session=False)
        db.query(StockReservation).filter(
            StockReservation.order_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(InvoiceDraft).filter(
            (InvoiceDraft.id.in_(ids)) | (InvoiceDraft.order_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Order).filter(
            (Order.id.in_(ids)) | (Order.quote_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(Quote).filter(Quote.id.in_(ids)).delete(synchronize_session=False)
        db.query(AgentDefinition).filter(AgentDefinition.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(WikiPage).filter(WikiPage.id.in_(ids)).delete(synchronize_session=False)
        db.query(SEOProject).filter(SEOProject.id.in_(ids)).delete(synchronize_session=False)
        db.query(LandingPage).filter(LandingPage.id.in_(ids)).delete(synchronize_session=False)
        db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids)).delete(synchronize_session=False)
        db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key.contains(key_fragment)
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_agent_registry_is_durable_draft_first_and_optimistically_versioned(
    client,
    auth_headers,
):
    marker = _key("agent")
    agent_id = f"custom_{uuid.uuid4().hex[:12]}"
    body = {
        "agent_id": agent_id,
        "name": "Agente persistente",
        "purpose": "Contrato de persistencia",
        "prompt": "Usa únicamente las herramientas autorizadas.",
        "allowed_tools": ["search_products"],
        "monthly_budget_usd": "5.00",
        "status": "active",
    }
    headers = {**auth_headers, "Idempotency-Key": marker}
    ids = [agent_id]
    try:
        created = client.post("/agents", headers=headers, json=body)
        replay = client.post("/agents", headers=headers, json=body)
        assert created.status_code == 200, created.text
        assert replay.status_code == 200
        assert replay.json() == created.json()
        assert created.json()["agent"]["status"] == "draft"
        assert created.json()["agent"]["persisted"] is True
        assert client.post(
            "/agents/run",
            headers=auth_headers,
            json={"agent_id": agent_id, "prompt": "hola"},
        ).status_code == 404

        patched = client.patch(
            f"/agents/{agent_id}",
            headers={
                **auth_headers,
                "If-Match": "1",
                "Idempotency-Key": f"{marker}-patch",
            },
            json={"purpose": "Contrato persistente actualizado"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["agent"]["version"] == 2
        assert patched.json()["agent"]["status"] == "draft"

        requested = client.post(
            f"/agents/{agent_id}/request-activation",
            headers={**auth_headers, "If-Match": "2"},
        )
        assert requested.status_code == 200, requested.text
        approval_id = requested.json()["approval_id"]
        ids.append(approval_id)
        approved = client.post(
            f"/approvals/{approval_id}/approve",
            headers=auth_headers,
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert client.get(f"/agents/{agent_id}/tools", headers=auth_headers).status_code == 200

        stale = client.post(
            "/agents",
            headers={
                **auth_headers,
                "Idempotency-Key": f"{marker}-stale",
                "If-Match": "1",
            },
            json={**body, "name": "Cambio obsoleto"},
        )
        assert stale.status_code == 409

        db = SessionLocal()
        try:
            persisted = db.query(AgentDefinition).filter(AgentDefinition.id == agent_id).one()
            assert persisted.status == "active"
            assert int(persisted.version) == 4
        finally:
            db.close()
    finally:
        _cleanup(ids=ids, key_fragment=marker)


def test_wiki_landing_seo_and_scheduler_are_real_drafts_with_approval_boundaries(
    client,
    auth_headers,
    monkeypatch,
):
    marker = _key("modules")
    ids: list[str] = []
    try:
        wiki = client.post(
            "/wiki/pages",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-wiki"},
            json={
                "slug": f"guia-{uuid.uuid4().hex[:8]}",
                "title": "Guía operativa",
                "content": "Contenido interno revisable.",
            },
        )
        assert wiki.status_code == 201, wiki.text
        wiki_id = wiki.json()["id"]
        ids.append(wiki_id)
        wiki_patch = client.patch(
            f"/wiki/pages/{wiki_id}",
            headers={
                **auth_headers,
                "If-Match": "1",
                "Idempotency-Key": f"{marker}-wiki-patch",
            },
            json={
                "content": (
                    "<p onclick='steal()'>Contenido <strong>corregido</strong></p>"
                    "<script>alert('x')</script><a href='javascript:alert(1)'>mal</a>"
                )
            },
        )
        assert wiki_patch.status_code == 200, wiki_patch.text
        assert wiki_patch.json()["version"] == 2
        assert client.get(f"/public/wiki/{wiki.json()['slug']}").status_code == 404
        wiki_preview = client.get(f"/wiki/pages/{wiki_id}/preview", headers=auth_headers)
        assert wiki_preview.status_code == 200
        assert "onclick" not in wiki_preview.text
        assert "javascript:" not in wiki_preview.text
        assert "<script>" not in wiki_preview.text
        wiki_request = client.post(
            f"/wiki/pages/{wiki_id}/request-publication",
            headers={**auth_headers, "If-Match": "2"},
        )
        assert wiki_request.status_code == 200, wiki_request.text
        wiki_approval = wiki_request.json()["approval_id"]
        ids.append(wiki_approval)
        assert client.post(
            f"/approvals/{wiki_approval}/approve",
            headers=auth_headers,
            json={},
        ).status_code == 200

        landing = client.post(
            "/landing-pages",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-landing"},
            json={
                "slug": f"oferta-{uuid.uuid4().hex[:8]}",
                "title": "Landing en revisión",
                "content": {
                    "headline": "Oferta",
                    "body": "<script>alert('x')</script>",
                    "cta": "Contactar",
                },
            },
        )
        assert landing.status_code == 201, landing.text
        landing_id = landing.json()["id"]
        ids.append(landing_id)
        assert client.get(f"/public/landing-pages/{landing.json()['slug']}").status_code == 404
        preview = client.get(f"/landing-pages/{landing_id}/preview", headers=auth_headers)
        assert preview.status_code == 200, preview.text
        assert "<script>" not in preview.text
        assert "&lt;script&gt;" in preview.text
        assert "sandbox" in preview.headers["content-security-policy"]
        landing_patch = client.patch(
            f"/landing-pages/{landing_id}",
            headers={
                **auth_headers,
                "If-Match": "1",
                "Idempotency-Key": f"{marker}-landing-patch",
            },
            json={"title": "Landing corregida"},
        )
        assert landing_patch.status_code == 200, landing_patch.text
        landing_request = client.post(
            f"/landing-pages/{landing_id}/request-approval",
            headers={**auth_headers, "If-Match": "2"},
        )
        assert landing_request.status_code == 200, landing_request.text
        landing_approval = landing_request.json()["approval_id"]
        ids.append(landing_approval)
        assert client.post(
            f"/approvals/{landing_approval}/approve",
            headers=auth_headers,
            json={},
        ).status_code == 200
        public_wiki = client.get(f"/public/wiki/{wiki.json()['slug']}")
        public_landing = client.get(f"/public/landing-pages/{landing.json()['slug']}")
        assert public_wiki.status_code == 200
        assert public_landing.status_code == 200
        assert public_wiki.headers["x-content-type-options"] == "nosniff"
        assert "<script>" not in public_wiki.text
        assert "<script>" not in public_landing.text

        seo = client.post(
            "/seo/projects",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-seo"},
            json={"name": "SEO técnico", "domain": "example.test", "configuration": {}},
        )
        assert seo.status_code == 201, seo.text
        assert seo.json()["status"] == "draft"
        assert seo.json()["analysis_engine"] == "deterministic_html_static_v1"
        seo_id = seo.json()["id"]
        ids.append(seo_id)
        seo_patch = client.patch(
            f"/seo/projects/{seo_id}",
            headers={
                **auth_headers,
                "If-Match": "1",
                "Idempotency-Key": f"{marker}-seo-patch",
            },
            json={"configuration": {"locale": "es-ES"}},
        )
        assert seo_patch.status_code == 200, seo_patch.text
        analysis = client.post(
            f"/seo/projects/{seo_id}/analyze-html",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-seo-analysis"},
            json={
                "page_url": "https://example.test/guia",
                "html": (
                    "<html><head><title>Guía técnica completa</title>"
                    "<meta name='description' content='Una descripción técnica suficientemente amplia para la prueba determinista.'>"
                    "<link rel='canonical' href='https://example.test/guia'>"
                    "<meta property='og:title' content='Guía'></head>"
                    "<body><h1>Guía</h1><img src='a.jpg'><a href='/interno'>Ir</a>"
                    "<script type='application/ld+json'>{}</script></body></html>"
                ),
            },
        )
        assert analysis.status_code == 200, analysis.text
        analysis_body = analysis.json()
        ids.append(analysis_body["analysis_id"])
        assert analysis_body["result"]["external_fetch_performed"] is False
        assert analysis_body["result"]["measured"]["images_missing_alt"] == 1
        assert {item["code"] for item in analysis_body["result"]["recommendations"]} >= {
            "images_missing_alt"
        }
        history = client.get(f"/seo/projects/{seo_id}/analyses", headers=auth_headers)
        assert history.status_code == 200
        assert any(item["analysis_id"] == analysis_body["analysis_id"] for item in history.json()["items"])

        task = client.post(
            "/scheduled-tasks",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-task"},
            json={
                "name": f"Barrido {uuid.uuid4().hex[:8]}",
                "task_type": "automation_sweep",
                "payload": {},
                "interval_seconds": 3600,
            },
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["id"]
        ids.append(task_id)
        task_patch = client.patch(
            f"/scheduled-tasks/{task_id}",
            headers={
                **auth_headers,
                "If-Match": "1",
                "Idempotency-Key": f"{marker}-task-patch",
            },
            json={"interval_seconds": 1800},
        )
        assert task_patch.status_code == 200, task_patch.text
        task_request = client.post(
            f"/scheduled-tasks/{task_id}/request-activation",
            headers={**auth_headers, "If-Match": "2"},
        )
        task_approval = task_request.json()["approval_id"]
        ids.append(task_approval)
        assert client.post(
            f"/approvals/{task_approval}/approve",
            headers=auth_headers,
            json={},
        ).status_code == 200

        db = SessionLocal()
        try:
            scheduled = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).one()
            scheduled.next_run_at = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        monkeypatch.setattr(
            "app.services.automations.run_automation_sweep",
            lambda _db, **_kwargs: {"quote_expiry": {}, "dunning": {}, "ran_at": "test"},
        )
        ran = client.post("/scheduled-tasks/run-due", headers=auth_headers)
        assert ran.status_code == 200, ran.text
        assert ran.json()["processed"] == 1

        wiki_rows = client.get("/wiki/pages", headers=auth_headers).json()["items"]
        landing_rows = client.get("/landing-pages", headers=auth_headers).json()["items"]
        assert next(row for row in wiki_rows if row["id"] == wiki_id)["status"] == "published"
        approved_landing = next(row for row in landing_rows if row["id"] == landing_id)
        assert approved_landing["status"] == "approved"
        assert approved_landing["external_publication"] == "not_implemented"
    finally:
        _cleanup(ids=ids, key_fragment=marker)


def test_commerce_api_recalculates_server_side_and_is_idempotent(client, auth_headers):
    marker = _key("commerce-api")
    ids: list[str] = []
    try:
        tampered = client.post(
            "/quotes",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-tampered"},
            json={
                "customer_id": "cust-004",
                "items": [{"product_id": "fixture-industrial-1", "qty": 1}],
                "grand_total": 0,
            },
        )
        assert tampered.status_code == 422

        quote_headers = {**auth_headers, "Idempotency-Key": f"{marker}-quote"}
        payload = {
            "customer_id": "cust-004",
            "items": [{"product_id": "fixture-industrial-1", "qty": 1}],
        }
        quote = client.post("/quotes", headers=quote_headers, json=payload)
        quote_replay = client.post("/quotes", headers=quote_headers, json=payload)
        assert quote.status_code == 201, quote.text
        assert quote_replay.json() == quote.json()
        quote_id = quote.json()["quote_id"]
        ids.append(quote_id)
        assert quote.json()["grand_total"] > 0

        confirm_headers = {**auth_headers, "Idempotency-Key": f"{marker}-confirm"}
        confirmation = client.post(
            f"/quotes/{quote_id}/confirm",
            headers=confirm_headers,
            json={"confirmation_token": quote.json()["confirmation_token"]},
        )
        confirmation_replay = client.post(
            f"/quotes/{quote_id}/confirm",
            headers=confirm_headers,
            json={"confirmation_token": quote.json()["confirmation_token"]},
        )
        assert confirmation.status_code == 200, confirmation.text
        assert confirmation_replay.json() == confirmation.json()
        ids.extend(
            [
                confirmation.json()["order_id"],
                confirmation.json()["invoice_draft_id"],
                confirmation.json()["approval_id"],
            ]
        )
        approval_id = confirmation.json()["approval_id"]
        rejected = client.post(
            f"/approvals/{approval_id}/reject",
            headers=auth_headers,
            json={"rejection_reason": "Corregir datos fiscales"},
        )
        assert rejected.status_code == 200, rejected.text
        invoice_id = confirmation.json()["invoice_draft_id"]
        assert client.get(f"/invoices/{invoice_id}", headers=auth_headers).json()["status"] == "draft"
        assert client.post(
            f"/invoices/{invoice_id}/request-approval",
            headers=auth_headers,
        ).status_code == 428
        resubmitted = client.post(
            f"/invoices/{invoice_id}/request-approval",
            headers={**auth_headers, "Idempotency-Key": f"{marker}-invoice-resubmit"},
        )
        assert resubmitted.status_code == 200, resubmitted.text
        assert resubmitted.json()["approval_id"] == approval_id
        assert resubmitted.json()["status"] == "pending"
        assert client.post(
            f"/approvals/{approval_id}/approve",
            headers=auth_headers,
            json={},
        ).status_code == 200
        assert client.get("/quotes", headers=auth_headers).status_code == 200
        assert client.get("/orders", headers=auth_headers).status_code == 200
        assert client.get("/invoices", headers=auth_headers).status_code == 200
    finally:
        db = SessionLocal()
        try:
            reservations = db.query(StockReservation).filter(
                StockReservation.order_id.in_(ids)
            ).all()
            for reservation in reservations:
                product = db.query(Product).filter(Product.id == reservation.product_id).first()
                if product is not None:
                    product.reserved_stock = max(
                        0,
                        int(product.reserved_stock) - int(reservation.quantity_reserved),
                    )
            db.commit()
        finally:
            db.close()
        _cleanup(ids=ids, key_fragment=marker)


def test_proxy_stripped_and_legacy_aliases_share_the_same_contract(
    client,
    auth_headers,
    monkeypatch,
):
    canonical_import = client.post(
        "/import/products",
        headers=auth_headers,
        json={
            "dry_run": True,
            "items": [
                {
                    "sku": f"DRY-{uuid.uuid4().hex[:8]}",
                    "name": "Producto dry-run",
                    "base_price": "10.00",
                    "tax_rate": "0.21",
                    "stock_quantity": 1,
                }
            ],
        },
    )
    assert canonical_import.status_code == 200, canonical_import.text
    assert client.get("/agents", headers=auth_headers).status_code == 200
    assert client.get("/api/bridge/agents", headers=auth_headers).status_code == 200

    async def fake_trigger(_path, payload):
        return {"executionId": f"exec-{payload['bridge_idempotency_key'][-12:]}"}

    monkeypatch.setattr("app.main.activepieces_adapter.trigger_webhook", fake_trigger)
    marker = _key("proxy-workflow")
    response = client.post(
        "/workflows/trigger",
        headers={**auth_headers, "Idempotency-Key": marker},
        json={
            "webhook_path": "/contract",
            "workflow_name": "proxy-contract",
            "event_type": "test",
            "payload": {},
        },
    )
    try:
        assert response.status_code == 200, response.text
    finally:
        _cleanup(ids=[response.json().get("execution_id", "")], key_fragment=marker)


def test_approval_resource_compare_and_swap_rejects_a_concurrent_edit(
    client,
    auth_headers,
    monkeypatch,
):
    from app import main as bridge_main

    marker = _key("approval-race")
    ids: list[str] = []
    page = client.post(
        "/wiki/pages",
        headers={**auth_headers, "Idempotency-Key": marker},
        json={
            "slug": f"race-{uuid.uuid4().hex[:8]}",
            "title": "Contrato de carrera",
            "content": "Versión inicial",
        },
    )
    assert page.status_code == 201, page.text
    page_id = page.json()["id"]
    ids.append(page_id)
    requested = client.post(
        f"/wiki/pages/{page_id}/request-publication",
        headers={**auth_headers, "If-Match": "1"},
    )
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()["approval_id"]
    ids.append(approval_id)
    original = bridge_main._approval_resource
    raced = False

    def load_then_concurrently_edit(db, approval):
        nonlocal raced
        resource = original(db, approval)
        if approval.id == approval_id and not raced:
            raced = True
            concurrent = SessionLocal()
            try:
                concurrent.execute(
                    update(WikiPage)
                    .where(WikiPage.id == page_id, WikiPage.version == 2)
                    .values(version=3, status="draft", updated_by="concurrent-editor")
                )
                concurrent.commit()
            finally:
                concurrent.close()
        return resource

    monkeypatch.setattr(bridge_main, "_approval_resource", load_then_concurrently_edit)
    try:
        decision = client.post(
            f"/approvals/{approval_id}/approve",
            headers=auth_headers,
            json={},
        )
        assert decision.status_code == 409, decision.text
        db = SessionLocal()
        try:
            approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).one()
            persisted = db.query(WikiPage).filter(WikiPage.id == page_id).one()
            assert approval.status == "pending"
            assert persisted.status == "draft"
            assert int(persisted.version) == 3
        finally:
            db.close()
    finally:
        _cleanup(ids=ids, key_fragment=marker)


@pytest.mark.parametrize(
    ("setting_name", "path"),
    [
        ("ENABLE_QUOTES", "/quotes"),
        ("ENABLE_ORDERS", "/orders"),
        ("ENABLE_INVOICES", "/invoices"),
    ],
)
def test_commerce_feature_flags_fail_closed_and_are_real(
    client,
    auth_headers,
    monkeypatch,
    setting_name,
    path,
):
    monkeypatch.setattr(settings, setting_name, False)
    disabled = client.get(path, headers=auth_headers)
    assert disabled.status_code == 503
    assert "deshabilitado" in disabled.json()["detail"]
    monkeypatch.setattr(settings, setting_name, True)
    assert client.get(path, headers=auth_headers).status_code == 200


def test_structured_module_payloads_are_size_and_shape_bounded(client, auth_headers) -> None:
    marker = _key("bounded-payload")
    landing = client.post(
        "/landing-pages",
        headers={**auth_headers, "Idempotency-Key": f"{marker}-landing"},
        json={
            "slug": f"oversize-{uuid.uuid4().hex[:8]}",
            "title": "Payload rechazado",
            "content": {"body": "x" * 200_001, "onclick": "alert(1)"},
        },
    )
    assert landing.status_code == 422

    seo = client.post(
        "/seo/projects",
        headers={**auth_headers, "Idempotency-Key": f"{marker}-seo"},
        json={
            "name": "SEO profundo",
            "domain": f"{uuid.uuid4().hex[:8]}.example.test",
            "configuration": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},
        },
    )
    assert seo.status_code == 422

    task = client.post(
        "/scheduled-tasks",
        headers={**auth_headers, "Idempotency-Key": f"{marker}-task"},
        json={
            "name": f"Tarea {uuid.uuid4().hex[:8]}",
            "task_type": "automation_sweep",
            "payload": {"oversize": "x" * 50_001},
            "interval_seconds": 60,
        },
    )
    assert task.status_code == 422
