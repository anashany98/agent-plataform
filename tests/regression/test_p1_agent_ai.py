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

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import pytest
from app import main as bridge_main
from app.database import Base, get_db
from app.installation_context import installation_scope
from app.main import app
from app.models.models import ConversationMessage
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


# ---------------------------------------------------------------------------
# commerce_chat: naturalidad y respuesta en el fallback extractivo + polish
# ---------------------------------------------------------------------------


from app.services import agent_ai  # noqa: E402


def _product(product_id: str, category: str, price: float = 3.5) -> dict:
    return {
        "name": f"Producto {product_id}",
        "sku": f"SKU-{product_id}",
        "category": category,
        "unit_price": price,
        "available_stock": 10,
    }


# ---------------------------------------------------------------------------
# Validación de salida: el LLM nunca puede mencionar SKUs inexistentes
# ---------------------------------------------------------------------------


def test_llm_output_drops_hallucinated_skus() -> None:
    products = [_product("01", "Escritura")]
    reply = (
        "Tenemos este modelo:\n"
        "- **Cubo Skewb** | SKU=SKU-01 | Escritura | 3.50 EUR | 10 disponibles\n"
        "- **Cubo Mágico Premium** | SKU=12345 (ejemplo, revisa en catálogo) | 15.00 EUR | 10 disponibles\n"
        "¿Te interesa alguno?"
    )
    cleaned = agent_ai._enforce_verified_product_output(reply, products)
    assert "12345" not in cleaned
    assert "ejemplo" not in cleaned
    assert "Premium" not in cleaned
    # La fila cruda válida se reescribe con el nombre autoritativo del bloque.
    assert "**Producto 01** — 3.50 EUR, 10 disponibles" in cleaned
    assert "¿Te interesa alguno?" in cleaned


def test_llm_output_drops_unknown_sku_even_without_marker() -> None:
    products = [_product("01", "Escritura")]
    reply = (
        "También tenemos el **Cubo Pro** con SKU=ZZZ-999 que es estupendo.\n"
        "Y el estándar: **Producto 01** | SKU=SKU-01 | Escritura | 3.50 EUR | 10 disponibles"
    )
    cleaned = agent_ai._enforce_verified_product_output(reply, products)
    assert "ZZZ-999" not in cleaned
    assert "Cubo Pro" not in cleaned
    assert "SKU=" not in cleaned
    assert "**Producto 01** — 3.50 EUR, 10 disponibles" in cleaned


def test_llm_output_reformats_raw_rows_to_natural_bullets() -> None:
    products = [_product("01", "Escritura", price=3.5)]
    reply = (
        "Te recomiendo:\n"
        "- Producto 01 | SKU=SKU-01 | Escritura | 3.50 EUR | 10 disponibles"
    )
    cleaned = agent_ai._enforce_verified_product_output(reply, products)
    assert "SKU=" not in cleaned
    assert "| Escritura" not in cleaned
    assert "**Producto 01** — 3.50 EUR, 10 disponibles" in cleaned


def test_llm_output_leaves_plain_prose_untouched() -> None:
    products = [_product("01", "Escritura")]
    reply = "Claro, tenemos bolígrafos azules a buen precio. ¿Quieres que te prepare un presupuesto?"
    assert agent_ai._enforce_verified_product_output(reply, products) == reply


def test_commerce_chat_greeting_extractive_is_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un saludo sin LLM responde con bienvenida, nunca 'no encuentro productos'."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None, query="hola", products=[], intent="greeting"
        )
    )
    assert result["provider"] == "extractive"
    assert "¡Hola!" in result["answer"]
    assert "ayudarte" in result["answer"]
    assert "no encuentro productos" not in result["answer"].lower()


def test_commerce_persona_dedupes_store_contained_in_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la tienda ya está en el nombre del asistente, no se duplica."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Asistente de BTOP Digital")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    assistant, store = agent_ai._commerce_persona()
    assert assistant == "Asistente de BTOP Digital"
    assert store == ""


def test_commerce_system_prompt_includes_persona_and_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La identidad y el cierre de compra del prompt usan la tienda del cliente."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    prompt = agent_ai._commerce_system_prompt()
    assert "Eres Carmen de BTOP Digital" in prompt
    assert "presupuesto de BTOP Digital" in prompt
    assert "presupuesto de BTOP Digital: se prepara y confirma en este mismo chat." in prompt


def test_commerce_system_prompt_falls_back_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin tienda configurada, el prompt genérico no menciona ninguna."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Asistente de la tienda")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "")
    prompt = agent_ai._commerce_system_prompt()
    assert "Eres Asistente de la tienda" in prompt
    assert "presupuesto: se prepara y confirma en este mismo chat." in prompt


def test_commerce_greeting_extractive_uses_store_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El saludo determinista se presenta con la persona y la tienda del cliente."""

    import asyncio

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None, query="hola", products=[], intent="greeting"
        )
    )
    assert result["provider"] == "extractive"
    assert "Carmen de BTOP Digital" in result["answer"]
    assert "presupuesto" in result["answer"]


def test_detect_language_register_english() -> None:
    directive = agent_ai._detect_language_register(
        "Hello! Do you have Rubik's cubes in your catalog?"
    )
    assert "inglés" in directive
    assert "responde íntegramente en inglés" in directive


def test_detect_language_register_formal_spanish() -> None:
    directive = agent_ai._detect_language_register(
        "Buenas tardes. Me gustaría saber si tienen cubos de Rubik en su catálogo, por favor."
    )
    assert "español" in directive
    assert "formal" in directive
    assert "sin tuteo" in directive


def test_detect_language_register_tuteo() -> None:
    directive = agent_ai._detect_language_register("hola! tienes cubos de rubik baratos?")
    assert "español" in directive
    assert "cercano" in directive
    assert "tuteo" in directive


def test_detect_language_register_neutral() -> None:
    # Sin tokens fiables no se impone idioma ni registro (el prompt general
    # ya pide adaptarse).
    assert agent_ai._detect_language_register("...") == ""
    assert "español" in agent_ai._detect_language_register("¿tenéis cubos de rubik?")


def test_commerce_chat_system_prompt_includes_language_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La directiva de idioma/registro llega al prompt de sistema del router."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)
    captured: dict = {}

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            captured["system_prompt"] = system_prompt or ""
            return {
                "content": "Sure, we have several Rubik's cubes available.",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="Hello! Do you have Rubik's cubes in your catalog?",
            products=[_product("01", "Escritura")],
            intent="search",
        )
    )
    assert result["provider"] == "ollama"
    assert "El cliente escribe en inglés" in captured["system_prompt"]
    assert "responde íntegramente en inglés" in captured["system_prompt"]


def test_commerce_chat_extractive_groups_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """El fallback extractivo agrupa por categoría, acota y ofrece filtrar."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    products = [_product(f"{i:02d}", "Escritura" if i < 6 else "Papel") for i in range(15)]
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None, query="bolis y papel", products=products, intent="search"
        )
    )
    answer = result["answer"]
    assert "15 producto(s)" in answer
    assert "Escritura:" in answer and "Papel:" in answer, "Agrupa por categoría"
    assert "y 3 más" in answer, "Acota con nota de los restantes"
    assert "| SKU=" not in answer, "No vuelca el bloque crudo de contexto"
    assert answer.count("• ") <= 12


def test_commerce_chat_llm_answer_is_polished(monkeypatch: pytest.MonkeyPatch) -> None:
    """La respuesta del LLM se recorta y colapsa líneas en blanco."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            return {
                "content": "\n\n  ¡Claro! Tenemos bolis azules.\n\n\n\n  \n¿Te preparo un presupuesto?  \n\n",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="tienes bolis azules?",
            products=[_product("01", "Escritura")],
            intent="search",
        )
    )
    assert result["provider"] == "ollama"
    # El polish conserva UNA línea en blanco entre párrafos (natural) y
    # colapsa los saltos múltiples y el exceso de espacio.
    assert result["answer"] == "¡Claro! Tenemos bolis azules.\n\n¿Te preparo un presupuesto?"
    assert "\n\n\n" not in result["answer"]


def test_commerce_chat_category_empty_extractive_is_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Categoría ausente: reconoce que no la tiene y ofrece alternativas reales."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="portátiles",
            products=[_product("01", "Escritura"), _product("02", "Papel")],
            intent="category_empty",
        )
    )
    answer = result["answer"]
    assert "esa categoría" in answer
    assert "Algunas opciones que sí tenemos" in answer
    assert "He encontrado 2" not in answer, "No finge tener lo que no tiene"


def test_commerce_chat_no_products_extractive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin productos: responde honesto y ofrece alternativas."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None, query="teclados mecánicos", products=[], intent="search"
        )
    )
    assert "no encuentro productos" in result["answer"].lower()


# ---------------------------------------------------------------------------
# Memoria de conversación: append/history acotados + prompt con historial
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_CHAT_MEMORY_MESSAGES", 4)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def test_append_and_history_are_ordered_and_pruned(memory_env) -> None:
    with installation_scope(INSTALLATION):
        with memory_env() as db:
            for index in range(6):
                agent_ai.append_conversation_message(
                    db,
                    account_id=1,
                    conversation_id=2,
                    role="client" if index % 2 == 0 else "assistant",
                    content=f"msg-{index}",
                    commit=False,
                )
            db.commit()
            history = agent_ai.conversation_history(db, account_id=1, conversation_id=2)
            assert [m["content"] for m in history] == ["msg-2", "msg-3", "msg-4", "msg-5"]
            assert [m["role"] for m in history] == ["client", "assistant", "client", "assistant"]
            assert db.query(ConversationMessage).count() == 4, "La memoria poda los antiguos"


def test_append_ignores_empty_or_missing_scope(memory_env) -> None:
    with installation_scope(INSTALLATION):
        with memory_env() as db:
            agent_ai.append_conversation_message(
                db, account_id="", conversation_id="x", role="client", content="hola", commit=False
            )
            agent_ai.append_conversation_message(
                db, account_id="a", conversation_id="b", role="client", content="   ", commit=False
            )
            agent_ai.append_conversation_message(
                db, account_id="a", conversation_id="b", role="otro", content="hola", commit=False
            )
            db.commit()
            assert db.query(ConversationMessage).count() == 0


def test_commerce_chat_prompt_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """El prompt incluye la conversación reciente como contexto de continuidad."""

    import asyncio

    captured: dict[str, str] = {}

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            captured["prompt"] = prompt
            return {"content": "Perfecto, te ayudo con eso.", "simulated": False, "provider": "ollama"}

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)
    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    history = [
        {"role": "client", "content": "tienes bolis azules?"},
        {"role": "assistant", "content": "Sí, tengo el boli azul a 1.35 EUR."},
    ]
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="y el rojo?",
            products=[_product("01", "Escritura")],
            intent="search",
            history=history,
        )
    )
    prompt = captured["prompt"]
    assert "Conversación reciente" in prompt
    assert "tienes bolis azules?" in prompt
    assert "Sí, tengo el boli azul a 1.35 EUR." in prompt
    assert "PRODUCTOS DISPONIBLES" in prompt
    assert "nunca fuente de datos" in prompt.lower()
    assert result["answer"] == "Perfecto, te ayudo con eso."


def test_webhook_registers_conversation_memory(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dos mensajes del cliente registran cliente+asistente en la memoria."""

    def signed(payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"test-chatwoot-secret",
            timestamp.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        return env.client.post(
            "/webhooks/chatwoot",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Chatwoot-Timestamp": timestamp,
                "X-Chatwoot-Signature": f"sha256={signature}",
            },
        )

    conversation_id = 7654321  # conversación única para no colisionar
    # El webhook del TestClient corre en un hilo distinto; el scope de
    # instalación se copia al hilo nuevo, así que toda la sesión (incluidas
    # las llamadas HTTP) debe ejecutarse dentro de ``installation_scope``
    # para que los registros se sellen con la instalación correcta.
    with installation_scope(INSTALLATION):
        with env.session_factory() as db:
            agent_ai.append_conversation_message(
                db, account_id="1", conversation_id=str(conversation_id), role="client", content="directo", commit=True
            )
        for content in ("hola", "buenas"):
            response = signed(
                {
                    "event": "message_created",
                    "id": f"mem-{uuid.uuid4().hex}",
                    "message_type": "incoming",
                    "content": content,
                    "conversation": {"id": conversation_id},
                    "account": {"id": 1},
                    "sender": {"email": "cliente@example.com", "name": "Cliente"},
                }
            )
            assert response.status_code == 200, response.text
            assert response.json()["action"] == "greeting"
        with env.session_factory() as db:
            rows = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == str(conversation_id))
                .order_by(ConversationMessage.sequence.asc())
                .all()
            )
            # 1 seed directo + 2 turnos completos (cliente + asistente).
            assert len(rows) == 5
            assert [row.role for row in rows] == ["client", "client", "assistant", "client", "assistant"]
            assert [row.content for row in rows][0] == "directo"
            assert rows[1].content == "hola"
            assert rows[3].content == "buenas"


# ---------------------------------------------------------------------------
# Filtro determinista de repetición de saludo (hallazgo LLM-as-judge)


def test_strip_greeting_repeat_no_history_keeps_greeting() -> None:
    """Sin historial el saludo se conserva (es el primer mensaje)."""

    reply = "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas hoy?"
    assert agent_ai._strip_greeting_repeat(reply, has_history=False) == reply
    assert agent_ai._strip_greeting_repeat(reply, has_history=False, intent="search") == reply


def test_strip_greeting_repeat_spanish_with_history() -> None:
    """Con historial se elimina el saludo+presentación y queda el contenido."""

    reply = "¡Hola! Soy Carmen de BTOP Digital. Tenemos el cubo con llavero por 3,50 EUR."
    stripped = agent_ai._strip_greeting_repeat(reply, has_history=True)
    assert stripped == "Tenemos el cubo con llavero por 3,50 EUR."
    assert "Hola" not in stripped and "Soy Carmen" not in stripped


def test_strip_greeting_repeat_english_with_history() -> None:
    """Mismo comportamiento con saludo en inglés (``Hello! I'm ...``)."""

    reply = "Hello! I'm Carmen from BTOP Digital. We have the Rubik's cube with keychain."
    stripped = agent_ai._strip_greeting_repeat(reply, has_history=True)
    assert stripped == "We have the Rubik's cube with keychain."
    assert "Hello" not in stripped and "I'm Carmen" not in stripped


def test_strip_greeting_repeat_variants_with_history() -> None:
    """Variantes: saludo sin presentación, buenas tardes, ofrecimiento."""

    assert agent_ai._strip_greeting_repeat("Hola, tenemos el cubo.", has_history=True) == "Tenemos el cubo."
    assert agent_ai._strip_greeting_repeat("Buenas tardes, aquí está su presupuesto.", has_history=True) == "Aquí está su presupuesto."
    assert agent_ai._strip_greeting_repeat("Hi! How can I help you? We have cubes.", has_history=True) == "We have cubes."
    # Sin saludo al inicio: no se toca nada.
    reply = "Tenemos el cubo con llavero a 3,50 EUR."
    assert agent_ai._strip_greeting_repeat(reply, has_history=True) == reply
    # Saludo en medio de la frase (no prefijo): intacto.
    reply2 = "El cubo de display, hola, es el más caro."
    assert agent_ai._strip_greeting_repeat(reply2, has_history=True) == reply2


def test_strip_greeting_repeat_pure_greeting_becomes_empty() -> None:
    """Una respuesta que es SOLO saludo repetido devuelve vacío (fallback)."""

    assert agent_ai._strip_greeting_repeat(
        "¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo ayudarte?", has_history=True
    ) == ""
    assert agent_ai._strip_greeting_repeat("¡Hola! ¿Qué tal?", has_history=True) == ""
    assert agent_ai._strip_greeting_repeat("Hello! How can I help you today?", has_history=True) == ""


def test_strip_greeting_repeat_greeting_intent_kept() -> None:
    """Si el cliente vuelve a saludar (intent greeting) el saludo se conserva."""

    reply = "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas hoy?"
    assert agent_ai._strip_greeting_repeat(reply, has_history=True, intent="greeting") == reply


def test_ensure_greeting_persona_inserts_after_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primer saludo sin nombre: se inserta la presentación tras el saludo."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    reply = "¡Hola! ¿En qué puedo ayudarle hoy?"
    ensured = agent_ai._ensure_greeting_persona(reply, has_history=False)
    assert ensured == "¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo ayudarle hoy?"


def test_ensure_greeting_persona_keeps_when_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el LLM ya se presentó, no se duplica nada."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    reply = "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas hoy?"
    assert agent_ai._ensure_greeting_persona(reply, has_history=False) == reply


def test_ensure_greeting_persona_prepends_without_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saludo sin prefijo de saludo: se antepone la presentación completa."""

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    ensured = agent_ai._ensure_greeting_persona("¿Qué necesitas?", has_history=False)
    assert ensured == "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas?"


def test_ensure_greeting_persona_ignores_followups() -> None:
    """Con historial o turno no-saludo no toca nada (ahí rige el strip)."""

    reply = "¡Hola! ¿En qué puedo ayudarle?"
    assert agent_ai._ensure_greeting_persona(reply, has_history=True) == reply
    assert agent_ai._ensure_greeting_persona(reply, has_history=False, intent="search") == reply


def test_commerce_chat_webhook_first_greeting_gets_persona(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El webhook persiste el mensaje actual antes de responder: el primer
    saludo sigue contando como primer mensaje y se le garantiza la persona."""

    import asyncio

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            return {
                "content": "¡Hola! ¿En qué puedo ayudarle?",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    # El historial ya incluye el mensaje actual (el webhook hace append antes
    # de generar la respuesta) — no debe contar como contexto previo.
    history = [{"role": "client", "content": "hola buenas tardes"}]
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="hola buenas tardes",
            products=[],
            intent="greeting",
            history=history,
        )
    )
    assert "Soy Carmen de BTOP Digital" in result["answer"]
    assert result["answer"] == "¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo ayudarle?"


def test_commerce_chat_llm_greeting_repeat_stripped_with_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integración: con historial el saludo repetido del LLM se elimina."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            return {
                "content": "¡Hola! Soy Carmen de BTOP Digital. Tenemos el cubo con llavero a 3,50 EUR.",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    history = [
        {"role": "client", "content": "¿tenéis cubos de rubik?"},
        {"role": "assistant", "content": "Sí, tenemos varias opciones."},
    ]
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="¿y el que tiene llavero cuánto cuesta?",
            products=[_product("01", "Escritura")],
            intent="search",
            history=history,
        )
    )
    assert result["provider"] == "ollama"
    assert result["answer"] == "Tenemos el cubo con llavero a 3,50 EUR."
    assert "Soy Carmen" not in result["answer"]


def test_commerce_chat_llm_greeting_kept_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin historial el saludo del LLM se conserva (primer mensaje)."""

    import asyncio

    monkeypatch.setattr(agent_ai.settings, "COMMERCE_ASSISTANT_NAME", "Carmen")
    monkeypatch.setattr(agent_ai.settings, "COMMERCE_STORE_NAME", "BTOP Digital")
    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            return {
                "content": "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas hoy?",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="hola",
            products=[],
            intent="greeting",
        )
    )
    assert result["answer"] == "¡Hola! Soy Carmen de BTOP Digital. ¿Qué necesitas hoy?"


def test_commerce_chat_greeting_only_with_history_falls_back_extractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Respuesta que es solo saludo repetido cae al fallback extractivo real."""

    import asyncio

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: True)

    class FakeRouter:
        def __init__(self, db):
            pass

        async def generate_response(self, prompt, profile="standard", system_prompt=None, **kwargs):
            return {
                "content": "¡Hola! Soy Carmen de BTOP Digital. ¿En qué puedo ayudarte?",
                "simulated": False,
                "provider": "ollama",
            }

    monkeypatch.setattr(agent_ai, "LLMRouterService", FakeRouter)
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None,
            query="¿y el que tiene llavero cuánto cuesta?",
            products=[_product("01", "Escritura")],
            intent="search",
            history=[{"role": "client", "content": "¿tenéis cubos?"}],
        )
    )
    # El saludo repetido sin contenido no pasa: cae al extractivo honesto.
    assert result["provider"] == "extractive"
    assert "Hola" not in result["answer"]
    assert "Soy Carmen" not in result["answer"]
