"""Unit tests: _plain_chat_text convierte respuestas del LLM a chat plano.

El chat del CEO agent renderiza en un ``<p>`` plano, así que los artefactos
de markdown (negritas, viñetas, encabezados, código) que los modelos locales
emiten pese al prompt deben limpiarse de forma determinista (observado con
Qwen3 14B, docs/LLM_MODEL_COMPARISON.md).

También cubre ``_humanize_target``: las claves objetivo de las propuestas
(UUID, ``inv-…``) se traducen al nombre humano del lead/cliente/producto
para que el chat del dueño no muestre identificadores técnicos.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.models import Customer, InvoiceDraft, Lead, Opportunity, Product, ScheduledTask
from app.services import ceo_agent


class _FakeQuery:
    """Mini query falsa: filter() es no-op y first() devuelve lo sembrado."""

    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    """DB falsa para _humanize_target: devuelve por modelo lo que se siembre."""

    def __init__(self, entities: dict):
        self._entities = entities

    def query(self, model):
        return _FakeQuery(self._entities.get(model))


def test_strips_bold_italic_backticks_headers_and_bullets() -> None:
    raw = (
        "**Resumen de ventas**\n"
        "- Oportunidades abiertas: 25\n"
        "* Ganadas: 3\n"
        "`sku-123` en stock\n"
        "## Pipeline\n"
        "*Etapa nueva*"
    )
    out = ceo_agent._plain_chat_text(raw)
    assert "**" not in out
    assert "`" not in out
    assert "#" not in out
    lines = out.splitlines()
    assert lines[0] == "Resumen de ventas"
    assert lines[1] == "Oportunidades abiertas: 25"
    assert lines[2] == "Ganadas: 3"
    assert "sku-123 en stock" in lines[3]
    assert lines[4] == "Pipeline"
    assert lines[5] == "Etapa nueva"


def test_keeps_numbers_decimals_and_underscores() -> None:
    out = ceo_agent._plain_chat_text(
        "Hay 25 oportunidades por 1.104,2 EUR y el win_rate es 0%."
    )
    assert "1.104,2" in out
    assert "win_rate" in out


def test_keeps_inline_separators_inside_sentences() -> None:
    out = ceo_agent._plain_chat_text(
        "Oportunidades por etapa:\n· nueva: 25 · won: 3"
    )
    # La viñeta al inicio de línea se quita; el separador interno se conserva.
    assert out == "Oportunidades por etapa:\nnueva: 25 · won: 3"


def test_proposal_labels_are_plain_language() -> None:
    # Los tipos de acción técnicos se traducen a frases humanas para el chat;
    # los desconocidos se dejan intactos (nunca se inventa una traducción).
    assert (
        ceo_agent._plain_proposal_label("agent_proposal:ceo_follow_up")
        == "seguimiento a un lead frío"
    )
    assert ceo_agent._plain_proposal_label("issue_invoice") == "emitir una factura"
    assert (
        ceo_agent._plain_proposal_label("agent_proposal:automation_toggle")
        == "activar o pausar una automatización"
    )
    assert ceo_agent._plain_proposal_label("algo_desconocido") == "algo_desconocido"
    assert ceo_agent._plain_requester("ceo_agent") == "el asistente de dirección"
    assert ceo_agent._plain_requester("sales_agent") == "el agente comercial"


def test_approvals_template_uses_plain_labels() -> None:
    data = {
        "pending": 3,
        "items": [
            {
                "action_type": "agent_proposal:ceo_follow_up",
                "target_key": "lead-uuid-1",
                "requested_by": "ceo_agent",
            },
            {
                "action_type": "issue_invoice",
                "target_key": "inv-123",
                "requested_by": "sales_agent",
            },
            {
                "action_type": "agent_proposal:automation_toggle",
                "target_key": "task-456",
                "requested_by": "ceo_agent",
            },
        ],
    }
    answer = ceo_agent._template_answer("approvals_pending", data)
    assert "seguimiento a un lead frío" in answer
    assert "emitir una factura" in answer
    assert "activar o pausar una automatización" in answer
    assert "el asistente de dirección" in answer
    assert "el agente comercial" in answer
    assert "agent_proposal:" not in answer
    assert "issue_invoice" not in answer


def test_approvals_facts_block_uses_plain_labels() -> None:
    data = {
        "pending": 2,
        "items": [
            {
                "action_type": "issue_invoice",
                "target_key": "inv-123",
                "requested_by": "sales_agent",
            },
            {
                "action_type": "issue_invoice",
                "target_key": "inv-456",
                "requested_by": "sales_agent",
            },
        ],
    }
    facts = ceo_agent._facts_block("approvals_pending", data)
    assert "emitir una factura: 2" in facts
    assert "pedida por el agente comercial" in facts
    assert "issue_invoice" not in facts


def test_approvals_template_shows_humanized_targets() -> None:
    data = {
        "pending": 2,
        "items": [
            {
                "action_type": "agent_proposal:ceo_follow_up",
                "target_key": "lead-uuid-1",
                "target_label": "María García",
                "requested_by": "ceo_agent",
            },
            {
                "action_type": "issue_invoice",
                "target_key": "inv-123",
                "target_label": "Acme SL (INV-2026-0001)",
                "requested_by": "sales_agent",
            },
        ],
    }
    answer = ceo_agent._template_answer("approvals_pending", data)
    assert "María García" in answer
    assert "Acme SL (INV-2026-0001)" in answer
    # La clave técnica nunca aparece: el target ya viene humanizado.
    assert "lead-uuid-1" not in answer
    assert "inv-123" not in answer


def test_humanize_target_resolves_lead_by_id() -> None:
    db = _FakeDB(
        {
            Lead: SimpleNamespace(id="lead-1", first_name="María", email="m@example.com"),
        }
    )
    item = {
        "action_type": "agent_proposal:ceo_follow_up",
        "target_key": "lead-1",
        "payload": None,
    }
    assert ceo_agent._humanize_target(db, item) == "María"


def test_humanize_target_resolves_opportunity_and_product() -> None:
    db = _FakeDB(
        {
            Opportunity: SimpleNamespace(id="opp-1", name="Ampliación contrato"),
            Product: SimpleNamespace(id="p-1", name="LOTE 19 DISPENSADORES", sku="20020"),
        }
    )
    assert (
        ceo_agent._humanize_target(
            db,
            {
                "action_type": "agent_proposal:ceo_move_opportunity",
                "target_key": "opp-1",
                "payload": None,
            },
        )
        == "Ampliación contrato"
    )
    assert (
        ceo_agent._humanize_target(
            db,
            {
                "action_type": "agent_proposal:ceo_adjust_stock",
                "target_key": "p-1",
                "payload": None,
            },
        )
        == "LOTE 19 DISPENSADORES (SKU 20020)"
    )


def test_humanize_target_resolves_invoice_client() -> None:
    db = _FakeDB(
        {
            InvoiceDraft: SimpleNamespace(
                id="inv-1", invoice_number="INV-2026-0042", customer_id="cust-1"
            ),
            Customer: SimpleNamespace(id="cust-1", name="Acme SL"),
        }
    )
    item = {
        "action_type": "issue_invoice",
        "target_key": "inv-1",
        "payload": None,
    }
    assert ceo_agent._humanize_target(db, item) == "Acme SL (INV-2026-0042)"


def test_humanize_target_falls_back_to_payload_and_raw_key() -> None:
    empty = _FakeDB({})
    # Sin entidad en BD, el nombre ya guardado en el payload es el recurso.
    with_payload = {
        "action_type": "agent_proposal:ghl_send_message",
        "target_key": "lead-1:sms:abc123",
        "payload": {"lead_name": "Carlos Pérez"},
    }
    assert ceo_agent._humanize_target(empty, with_payload) == "Carlos Pérez"
    # Ni entidad ni payload: la clave tal cual (nunca se inventa ni rompe).
    raw = {
        "action_type": "agent_proposal:ceo_follow_up",
        "target_key": "lead-inexistente",
        "payload": None,
    }
    assert ceo_agent._humanize_target(empty, raw) == "lead-inexistente"


def test_humanize_target_automation_and_task_composite() -> None:
    db = _FakeDB(
        {
            ScheduledTask: SimpleNamespace(id="t-1", name="Sync PrestaShop"),
            Lead: SimpleNamespace(id="lead-9", first_name="Ana", email="ana@example.com"),
        }
    )
    assert (
        ceo_agent._humanize_target(
            db,
            {
                "action_type": "agent_proposal:automation_toggle",
                "target_key": "t-1",
                "payload": None,
            },
        )
        == "Sync PrestaShop"
    )
    # target_key compuesta "{lead_id}:{título}": el lead se resuelve por nombre.
    assert (
        ceo_agent._humanize_target(
            db,
            {
                "action_type": "agent_proposal:ceo_create_task",
                "target_key": "lead-9:Llamar para presupuesto",
                "payload": None,
            },
        )
        == "Llamar para presupuesto (lead Ana)"
    )


def test_template_answers_are_plain_chat_text() -> None:
    # Las plantillas deterministas pasan por el mismo filtro: nada de viñetas
    # al inicio de línea ni asteriscos en las respuestas del chat del dueño.
    data = {
        "open_count": 2,
        "open_value": "120.00",
        "won_count": 1,
        "won_value": "300.00",
        "lost_count": 0,
        "win_rate": "33.3",
        "ticket_medio": "150.00",
        "orders_count": 3,
    }
    answer = ceo_agent._plain_chat_text(
        ceo_agent._template_answer("sales_summary", data)
    )
    assert "**" not in answer and "*" not in answer
    assert not answer.lstrip().startswith(("-", "·", "*", "#"))
    assert "oportunidades" in answer.lower()
