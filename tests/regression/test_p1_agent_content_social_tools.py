"""Mejoras de agentes: contenido/SEO/wiki/landing y SLA social.

Cubre las herramientas read-only nuevas (search_wiki, get_seo_overview,
list_landing_pages, list_social_sla_breaches): funcionalidad determinista,
deny-by-default entre módulos y la integración del SLA social con las
alertas durables (SS-07) vía el worker de entrega.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from app.database import SessionLocal


@pytest.fixture(autouse=True)
def _clean_tool_audits():
    """La BD es compartida por toda la sesión: deja cero auditorías de
    herramientas al terminar, para que los tests de supervisión que exigen
    agentes ociosos no hereden actividad de este módulo."""

    yield

    from app.models.models import AuditLog

    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.event_type == "tool_call").delete()
        db.commit()
    finally:
        db.close()


def _invoke(client, headers, agent_id, tool, arguments=None):
    return client.post(
        "/agents/tools/invoke",
        headers=headers,
        json={"agent_id": agent_id, "tool": tool, "arguments": arguments or {}},
    )


def _seed_wiki(**overrides):
    from app.models.models import WikiPage

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        page = WikiPage(
            slug=overrides.pop("slug", f"wiki-{suffix}"),
            title=overrides.pop("title", f"Página {suffix}"),
            content=overrides.pop("content", "Contenido sintético de prueba."),
            created_by="test",
            updated_by="test",
            **overrides,
        )
        db.add(page)
        db.commit()
        return page.id
    finally:
        db.close()


def _seed_seo_project(status: str) -> str:
    from app.models.models import SEOProject

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        project = SEOProject(
            name=f"Proyecto SEO {suffix}",
            domain=f"{suffix}.example.invalid",
            status=status,
            created_by="test",
            updated_by="test",
        )
        db.add(project)
        db.commit()
        return project.id
    finally:
        db.close()


def _seed_landing(status: str) -> str:
    from app.models.models import LandingPage

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        page = LandingPage(
            slug=f"landing-{suffix}",
            title=f"Landing {suffix}",
            content={"sections": []},
            status=status,
            created_by="test",
            updated_by="test",
        )
        db.add(page)
        db.commit()
        return page.id
    finally:
        db.close()


def _seed_social_breach(*, minutes_old: int, intent: str, channel_type: str):
    """Crea canal+mensaje+triaje con ``created_at`` retrocedido."""

    from app.models.models import SocialChannel, SocialMessage, SocialTriage

    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        channel = SocialChannel(
            channel=channel_type,
            name=f"Canal {uuid.uuid4().hex[:6]}",
            webhook_secret=f"secreto-{uuid.uuid4().hex[:16]}",
        )
        db.add(channel)
        db.flush()
        message = SocialMessage(
            channel_id=channel.id,
            source_message_id=f"src-{uuid.uuid4().hex[:12]}",
            sender_handle=f"@user{uuid.uuid4().hex[:6]}",
            body="Mensaje de prueba para SLA",
            status="new",
            created_at=now - datetime.timedelta(minutes=minutes_old),
        )
        db.add(message)
        db.flush()
        triage = SocialTriage(
            message_id=message.id,
            intent=intent,
            score_social=50,
        )
        db.add(triage)
        db.commit()
        return message.id
    finally:
        db.close()


def test_search_wiki_finds_published_and_hides_draft(client, auth_headers):
    published_id = _seed_wiki(
        title="Guía oficial de devoluciones",
        content="Pasos para solicitar una devolución en 14 días.",
        status="published",
    )
    draft_id = _seed_wiki(title="Borrador interno devoluciones", status="draft")

    response = _invoke(client, auth_headers, "content_agent", "search_wiki", {"query": "devoluciones"})
    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    found_ids = {item["id"] for item in items}
    assert published_id in found_ids
    assert draft_id not in found_ids


def test_get_seo_overview_counts_by_status(client, auth_headers):
    _seed_seo_project("active")
    _seed_landing("pending_approval")

    response = _invoke(client, auth_headers, "content_agent", "get_seo_overview")
    assert response.status_code == 200, response.text
    overview = response.json()["result"]
    assert overview["seo_projects_by_status"].get("active", 0) >= 1
    assert overview["landing_pages_by_status"].get("pending_approval", 0) >= 1
    assert overview["wiki_pages_by_status"], "debe reflejar las páginas sembradas por otros tests"


def test_list_landing_pages_filters_status(client, auth_headers):
    approved_id = _seed_landing("approved")
    draft_id = _seed_landing("draft")

    response = _invoke(
        client, auth_headers, "content_agent", "list_landing_pages", {"status": "approved"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    ids = {item["id"] for item in items}
    assert approved_id in ids
    assert draft_id not in ids


def test_list_social_sla_breaches_detects_overdue_complaint(client, auth_headers):
    breached_id = _seed_social_breach(minutes_old=60, intent="queja", channel_type="whatsapp")
    fresh_id = _seed_social_breach(minutes_old=1, intent="consulta", channel_type="whatsapp")

    response = _invoke(
        client, auth_headers, "social_agent", "list_social_sla_breaches", {"limit": 200}
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    ids = {item["id"] for item in result["items"]}
    assert breached_id in ids, "la queja de hace 60 min debe estar fuera de SLA"
    assert fresh_id not in ids, "el mensaje reciente NO debe estar fuera de SLA"
    item = next(item for item in result["items"] if item["id"] == breached_id)
    assert item["sla_minutes"] == 15  # queja pública: SLA mínimo
    assert item["overdue_minutes"] >= 45


def test_cross_module_allowlist_is_denied(client, auth_headers):
    # content_agent NO puede leer CRM; social_agent NO puede leer wiki.
    assert (
        _invoke(client, auth_headers, "content_agent", "list_leads", {}).status_code == 403
    )
    assert (
        _invoke(client, auth_headers, "social_agent", "search_wiki", {"query": "x"}).status_code
        == 403
    )
    # ceo_agent sí puede supervisar el SLA social (visión global).
    ok = _invoke(client, auth_headers, "ceo_agent", "list_social_sla_breaches", {})
    assert ok.status_code == 200, ok.text


def test_worker_fires_social_sla_durable_alert_with_dedup(monkeypatch):
    from app.models.models import AlertDelivery
    from app.services.alert_delivery_worker import DurableAlertDeliveryWorker

    _seed_social_breach(minutes_old=120, intent="queja", channel_type="whatsapp")

    monkeypatch.setattr("app.config.settings.ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr("app.config.settings.ALERT_EMAIL_TO", "")

    db = SessionLocal()
    try:
        db.query(AlertDelivery).delete()
        db.commit()

        worker = DurableAlertDeliveryWorker(session_factory=lambda: db)
        first = worker.evaluate_and_enqueue(db)
        assert first["fired"] >= 1
        assert first["enqueued"] >= 1

        social_rows = (
            db.query(AlertDelivery)
            .filter(AlertDelivery.rule_id == "social_sla_breach")
            .all()
        )
        assert len(social_rows) == 1, "la ventana de dedup colapsa repeticiones"

        second = worker.evaluate_and_enqueue(db)
        assert second["duplicates"] >= 1
        still_one = (
            db.query(AlertDelivery)
            .filter(AlertDelivery.rule_id == "social_sla_breach")
            .count()
        )
        assert still_one == 1
    finally:
        db.close()
