"""Evals D-012 (lote 2): port de ``docs-chat`` de FlowWink sobre el RAG del Bridge.

Cobertura:

- Respuesta extractiva con citas verificables cuando el rol tiene ACL.
- Abstención por ACL denegada (deny-by-default): mismo dato, rol sin permiso.
- Abstención por falta de evidencia (consulta irrelevante).
- Honestidad: ``provider="extractive"`` y nunca un LLM simulado disfrazado.

Hermetismo: SQLite efímero, RAG con ``local_tfidf`` (permitido fuera de
producción), fixtures sintéticos y sin red.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.security import Principal, get_current_principal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

INSTALLATION = "agent-ai-instalacion"


class Env:
    def __init__(self, engine, session_factory):
        self.engine = engine
        self.session_factory = session_factory
        self.client = TestClient(app, raise_server_exceptions=False)

    def set_role(self, role: str) -> None:
        def isolated_db():
            with installation_scope(INSTALLATION):
                db = self.session_factory()
                try:
                    yield db
                finally:
                    db.close()

        principal = Principal(
            user_id=f"agent-ai-{role}",
            username=f"agent-ai-{role}",
            role=role,
            installation_id=INSTALLATION,
            token_version=0,
            jti=f"agent-ai-{role}",
        )
        app.dependency_overrides[get_db] = isolated_db
        app.dependency_overrides[get_current_principal] = lambda: principal

    def close(self) -> None:
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_principal, None)
        self.engine.dispose()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    monkeypatch.setattr(bridge_main.settings, "EMBEDDING_PROVIDER", "local_tfidf")
    monkeypatch.setattr(bridge_main.settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(bridge_main.settings, "RAG_MIN_SCORE", 0.05)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    environment = Env(engine, session_factory)
    environment.set_role("provider_admin")
    try:
        yield environment
    finally:
        environment.close()


def _ingest(env: Env, tmp_path: Path) -> None:
    document = tmp_path / "garantia.txt"
    document.write_text(
        "La silla Ergo 500 dispone de soporte lumbar regulable y una garantía de cinco años.",
        encoding="utf-8",
    )
    response = env.client.post(
        "/rag/ingest",
        json={
            "doc_id": "garantia-doc",
            "file_path": str(document),
            "metadata": {"classification": "confidential", "allowed_roles": ["provider_admin"]},
        },
    )
    assert response.status_code == 200, response.text


def test_docs_chat_returns_extractive_answer_with_citations(env: Env, tmp_path: Path) -> None:
    _ingest(env, tmp_path)
    response = env.client.post(
        "/agents/docs-chat", json={"query": "¿Qué garantía tiene la silla Ergo 500?"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is False
    assert body["provider"] == "extractive", "Sin LLM real debe responder de forma extractiva"
    assert "garantía" in body["answer"].lower()
    assert len(body["citations"]) >= 1
    assert body["citations"][0]["doc_id"] == "garantia-doc"


def test_docs_chat_abstains_when_acl_denied(env: Env, tmp_path: Path) -> None:
    _ingest(env, tmp_path)
    # Mismo dato, pero un rol sin ACL sobre el documento debe abstenerse.
    env.set_role("viewer")
    response = env.client.post(
        "/agents/docs-chat", json={"query": "¿Qué garantía tiene la silla Ergo 500?"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is True, "Sin ACL autorizada el sistema debe abstenerse"
    assert body["citations"] == []


def test_docs_chat_abstains_on_irrelevant_query(env: Env, tmp_path: Path) -> None:
    _ingest(env, tmp_path)
    response = env.client.post(
        "/agents/docs-chat",
        json={"query": "cuál es el sentido de la vida", "min_score": 0.2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is True, "Sin evidencia suficiente no se inventa respuesta"
