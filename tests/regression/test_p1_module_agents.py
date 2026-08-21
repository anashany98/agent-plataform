"""Evals T-057: agentes de IA especializados por módulo.

Cubre la capa de agentes que gestionan cada módulo de la app:

- Registro: cada módulo de negocio tiene su agente built-in con metadatos
  (`module`, `module_label`, `scope`, tier, presupuesto) y tools honestas.
- Tool policy deny-by-default: las herramientas read-only por módulo están
  declaradas (kind `read`); ninguna allowlist de agente autoriza herramientas
  prohibidas (financieras/contables); herramienta desconocida o fuera de la
  allowlist → denied auditado.
- Executor por módulo: `crm_agent` lee leads/actividades/pipeline,
  `social_agent` lee el inbox social, `marketing_agent` lee campañas; todo
  determinista, sin mutación y con auditoría `tool_call`.

Hermeticidad D-032: SQLite de test, seeds por ORM con ids únicos y limpieza
en `finally`.
"""

from __future__ import annotations

import uuid

import pytest
from app.database import SessionLocal
from app.models.models import (
    AuditLog,
    Campaign,
    CampaignRecipient,
    EmailTrackingEvent,
    Lead,
    SocialMessage,
    SocialTriage,
    User,
)
from app.security import Principal
from app.services.tool_policy import ToolPolicyError

PORTAL_TEST_PASSWORD = "Portal-Test-123!"

MODULES = {
    "catalog": "catalog_agent",
    "crm": "crm_agent",
    "social": "social_agent",
    "marketing": "marketing_agent",
    "content": "content_agent",
}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_user(client, auth_headers, username: str, role: str) -> None:
    response = client.post(
        "/users",
        json={
            "username": username,
            "password": PORTAL_TEST_PASSWORD,
            "role": role,
            "must_change_password": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text


def _login(client, username: str) -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": PORTAL_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _principal(token: str) -> Principal:
    from app.security import decode_access_token

    return decode_access_token(token)


@pytest.fixture()
def agent_env(client, auth_headers):
    admin = _unique("admin-mod")
    _create_user(client, auth_headers, admin, "client_admin")
    token = _login(client, admin)
    env = {
        "client": client,
        "auth_headers": auth_headers,
        "token": token,
        "principal": _principal(token),
    }
    try:
        yield env
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == admin).delete()
            db.commit()
        finally:
            db.close()


def _executor(env, agent_config):
    from app.services.tool_policy import ToolExecutor

    return ToolExecutor(
        SessionLocal(), env["principal"], agent_config
    )


def _invoke(executor, tool: str, args=None):
    import asyncio

    return asyncio.run(executor.invoke(tool, args or {}))


# ---------------------------------------------------------------------------
# Registro: un agente por módulo
# ---------------------------------------------------------------------------


def test_registry_has_an_agent_per_module(agent_env):
    from app.main import AGENT_REGISTRY

    for module, expected_agent in MODULES.items():
        agent = AGENT_REGISTRY.get(expected_agent)
        assert agent is not None, f"falta el agente del módulo {module}"
        assert agent.get("module") == module
        assert agent.get("module_label")
        assert agent.get("scope")
        assert agent.get("autonomy_level")
        assert agent.get("monthly_budget_usd", 0) >= 0
        assert agent.get("status") == "active"


def test_all_registry_agents_have_known_and_allowed_tools(agent_env):
    from app.main import AGENT_REGISTRY
    from app.services.tool_policy import (
        _FORBIDDEN_AGENT_TOOLS,
        authorized_tools_for,
        known_tool_names,
    )

    known = set(known_tool_names())
    for agent_id, config in AGENT_REGISTRY.items():
        declared = config.get("allowed_tools") or []
        assert declared, f"{agent_id} sin tools"
        assert set(declared) <= known, f"{agent_id} declara tools desconocidas"
        # La allowlist efectiva es la intersección estricta (fail-closed).
        authorized = set(authorized_tools_for(config))
        assert authorized == set(declared)
        # Ninguna herramienta prohibida puede quedar autorizada.
        assert not (authorized & set(_FORBIDDEN_AGENT_TOOLS))


def test_module_tools_are_read_only(agent_env):
    from app.services.tool_policy import TOOL_SPECS

    module_tools = [
        "list_leads",
        "list_activities",
        "get_pipeline_report",
        "list_social_inbox",
        "get_social_stats",
        "list_campaigns",
        "get_campaign_stats",
    ]
    for tool in module_tools:
        assert tool in TOOL_SPECS, f"falta {tool} en TOOL_SPECS"
        assert TOOL_SPECS[tool]["kind"] == "read", f"{tool} no es read-only"


def test_agents_exposed_by_api_with_module_metadata(agent_env):
    response = agent_env["client"].get("/agents", headers=agent_env["auth_headers"])
    assert response.status_code == 200
    agents = response.json()["agents"]
    by_id = {agent["agent_id"]: agent for agent in agents}
    for module, agent_id in MODULES.items():
        assert agent_id in by_id
        assert by_id[agent_id]["module"] == module
        assert by_id[agent_id]["module_label"]


# ---------------------------------------------------------------------------
# Executor por módulo (read-only, auditado)
# ---------------------------------------------------------------------------


def test_crm_agent_lists_leads_and_report(agent_env):
    from app.main import AGENT_REGISTRY

    db = SessionLocal()
    lead_email = f"{_unique('mod-lead')}@example.com"
    lead_id = f"lead-{uuid.uuid4().hex[:12]}"
    try:
        db.add(
            Lead(
                id=lead_id,
                email=lead_email,
                first_name="Agente CRM",
                source="web",
                status="new",
            )
        )
        db.commit()
    finally:
        db.close()

    executor = _executor(agent_env, AGENT_REGISTRY["crm_agent"])
    try:
        result = _invoke(executor, "list_leads", {"status": "new", "limit": 10})
        assert result["total"] >= 1
        assert any(item["id"] == lead_id for item in result["items"])
        report = _invoke(executor, "get_pipeline_report")
        assert "by_stage" in report and "weighted_pipeline_value" in report
        # Una herramienta de otro módulo → denied.
        with pytest.raises(ToolPolicyError):
            _invoke(executor, "search_products", {"query": "talonario"})
    finally:
        db = SessionLocal()
        try:
            db.query(Lead).filter(Lead.id == lead_id).delete()
            db.commit()
        finally:
            db.close()


def test_social_agent_reads_inbox_and_stats(agent_env):
    from app.main import AGENT_REGISTRY

    db = SessionLocal()
    message_id = f"msg-{uuid.uuid4().hex[:12]}"
    lead_id = f"lead-{uuid.uuid4().hex[:12]}"
    try:
        db.add(
            Lead(
                id=lead_id,
                email=f"{_unique('soc')}@example.com",
                first_name="Carlos Social",
                source="social",
                status="new",
            )
        )
        db.add(
            SocialMessage(
                id=message_id,
                channel_id="ch-mod",
                source_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
                body="Quiero un presupuesto urgente",
                sender_name="Carlos",
                status="triaged",
                lead_id=lead_id,
            )
        )
        db.flush()
        db.add(
            SocialTriage(
                message_id=message_id,
                intent="lead",
                language="es",
                register="formal",
                urgency=70,
                score_social=60,
                summary="Lead de Carlos",
                decided_by="deterministic",
            )
        )
        db.commit()
    finally:
        db.close()

    executor = _executor(agent_env, AGENT_REGISTRY["social_agent"])
    try:
        inbox = _invoke(executor, "list_social_inbox", {"intent": "lead"})
        assert any(item["id"] == message_id for item in inbox["items"])
        stats = _invoke(executor, "get_social_stats")
        assert stats["by_intent"].get("lead", 0) >= 1
    finally:
        db = SessionLocal()
        try:
            db.query(SocialTriage).filter(SocialTriage.message_id == message_id).delete()
            db.query(SocialMessage).filter(SocialMessage.id == message_id).delete()
            db.query(Lead).filter(Lead.id == lead_id).delete()
            db.commit()
        finally:
            db.close()


def test_marketing_agent_reads_campaign_stats(agent_env):
    from app.main import AGENT_REGISTRY

    db = SessionLocal()
    campaign_id = f"cmp-{uuid.uuid4().hex[:12]}"
    recipient_id = f"rc-{uuid.uuid4().hex[:12]}"
    token = f"tk-{uuid.uuid4().hex[:12]}"
    try:
        db.add(
            Campaign(
                id=campaign_id,
                name=_unique("campaña mod"),
                template_name="tpl",
                segment={},
                status="sent",
            )
        )
        db.add(
            CampaignRecipient(
                id=recipient_id,
                campaign_id=campaign_id,
                lead_id=f"lead-{uuid.uuid4().hex[:12]}",
                email=f"{_unique('rc')}@example.com",
                status="sent",
                tracking_token=token,
            )
        )
        db.add(
            EmailTrackingEvent(
                token=token,
                event_type="open",
            )
        )
        db.commit()
    finally:
        db.close()

    executor = _executor(agent_env, AGENT_REGISTRY["marketing_agent"])
    try:
        campaigns = _invoke(executor, "list_campaigns")
        assert any(item["id"] == campaign_id for item in campaigns["items"])
        stats = _invoke(executor, "get_campaign_stats", {"campaign_id": campaign_id})
        assert stats["recipients"] == 1
        assert stats["opened"] == 1
    finally:
        db = SessionLocal()
        try:
            db.query(EmailTrackingEvent).filter(EmailTrackingEvent.token == token).delete()
            db.query(CampaignRecipient).filter(CampaignRecipient.id == recipient_id).delete()
            db.query(Campaign).filter(Campaign.id == campaign_id).delete()
            db.commit()
        finally:
            db.close()


def test_unknown_and_forbidden_tools_are_denied_and_audited(agent_env):
    from app.main import AGENT_REGISTRY

    executor = _executor(agent_env, AGENT_REGISTRY["crm_agent"])
    with pytest.raises(ToolPolicyError):
        _invoke(executor, "tool_inexistente")
    with pytest.raises(ToolPolicyError):
        _invoke(executor, "confirm_quote")

    db = SessionLocal()
    try:
        denied = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "tool_call", AuditLog.status == "denied")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert denied is not None
        assert denied.agent_id == "crm_agent"
        assert denied.details.get("policy") == "deny-by-default"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# T-059: panel de supervisión por módulo (GET /agents/supervision)
# ---------------------------------------------------------------------------


def _seed_supervision_logs(env, agent_id: str, tool: str) -> list[str]:
    """Crea tres `tool_call` auditados (success/denied/error) y devuelve sus ids.

    Timestamps explícitos y crecientes relativos a ahora para que el orden
    cronológico descendente del endpoint sea determinista (mismo segundo →
    SQLite no garantiza el desempate). Usar una fecha fija en el pasado
    haría que otros logs en vivo del corpus (tests anteriores del módulo)
    desplazaran estas filas fuera del top-5 de ``recent_actions``.
    """

    import datetime

    db = SessionLocal()
    ids: list[str] = []
    base = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    try:
        for offset, status in enumerate(("success", "denied", "error"), start=1):
            log = AuditLog(
                installation_id=env["principal"].installation_id,
                agent_id=agent_id,
                event_type="tool_call",
                status=status,
                timestamp=base + datetime.timedelta(seconds=offset),
                details={"tool": tool, "policy": "deny-by-default"},
            )
            db.add(log)
            db.flush()
            ids.append(log.id)
        db.commit()
    finally:
        db.close()
    return ids


def _delete_supervision_logs(ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()


def _supervision(env) -> dict:
    response = env["client"].get(
        "/agents/supervision", headers={"Authorization": f"Bearer {env['token']}"}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    return data


def test_supervision_lists_every_module_agent_with_tools(agent_env):
    from app.main import AGENT_REGISTRY

    data = _supervision(agent_env)
    by_id = {row["agent_id"]: row for row in data["agents"]}
    for module, agent_id in MODULES.items():
        row = by_id.get(agent_id)
        assert row is not None, f"falta {agent_id} en la supervisión"
        assert row["module"] == module
        assert row["module_label"]
        assert row["scope"]
        assert row["status"] == "active"
        assert row["summary"]["calls"] >= 0
        assert isinstance(row["recent_actions"], list)
        # Cada tool autorizada del registro aparece con su estado y kind read
        expected = set(AGENT_REGISTRY[agent_id]["allowed_tools"])
        tool_names = {tool["name"] for tool in row["tools"]}
        assert expected <= tool_names, f"faltan tools de {agent_id}"
        for tool in row["tools"]:
            if tool["name"] in expected:
                assert tool["authorized"] is True
                assert tool["kind"] == "read"
                assert tool["declared"] is True
    assert data["totals"]["agents"] >= len(MODULES)
    assert data["generated_at"]


def test_supervision_aggregates_tool_calls_and_recent_actions(agent_env):
    tool = f"probe_sup_{uuid.uuid4().hex[:8]}"
    ids = _seed_supervision_logs(agent_env, "crm_agent", tool)
    try:
        data = _supervision(agent_env)
        row = next(r for r in data["agents"] if r["agent_id"] == "crm_agent")
        bucket = next(t for t in row["tools"] if t["name"] == tool)
        assert bucket["calls"] == 3
        assert bucket["success"] == 1
        assert bucket["denied"] == 1
        assert bucket["errors"] == 1
        assert bucket["last_status"] == "error"
        assert bucket["declared"] is False
        assert bucket["authorized"] is False
        assert row["summary"]["calls"] >= 3
        statuses = [action["status"] for action in row["recent_actions"] if action["tool"] == tool]
        assert set(statuses) == {"success", "denied", "error"}
        # Orden cronológico descendente: la última acción va primero
        timestamps = [action["timestamp"] for action in row["recent_actions"]]
        assert timestamps == sorted(timestamps, reverse=True)
    finally:
        _delete_supervision_logs(ids)


def test_supervision_idle_agent_has_zero_calls_and_no_actions(agent_env):
    data = _supervision(agent_env)
    row = next(r for r in data["agents"] if r["agent_id"] == "content_agent")
    # content_agent no se ejecuta en este corpus: aparece ocioso, con su
    # allowlist declarada y sin actuaciones (la ausencia también es señal)
    assert row["summary"]["calls"] == 0
    assert row["summary"]["last_activity_at"] is None
    assert row["recent_actions"] == []
    assert set(row["authorized_tools"]) == {"rag_search"}


def test_supervision_requires_auth_and_accepts_viewer(agent_env):
    assert agent_env["client"].get("/agents/supervision").status_code == 401
    viewer = _unique("viewer-sup")
    _create_user(agent_env["client"], agent_env["auth_headers"], viewer, "viewer")
    try:
        token = _login(agent_env["client"], viewer)
        response = agent_env["client"].get(
            "/agents/supervision", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == viewer).delete()
            db.commit()
        finally:
            db.close()
