"""Unit tests: _plain_chat_preserve_bold limpia el markdown del chat comercial.

El asistente comercial responde como un chat de mensajería, pero conserva la
negrita ``**Nombre de producto**`` (la única excepción: el widget la
renderiza). Este archivo fija ese contrato: se quitan cursivas, código,
encabezados y viñetas; los ``**...**`` quedan intactos.
"""

from __future__ import annotations

import asyncio

import pytest
from app.services import agent_ai


def test_strips_artifacts_but_keeps_bold() -> None:
    raw = (
        "**Resumen de ventas**\n"
        "- **Cubo Mágico**: 3.50 EUR, 10 disponibles\n"
        "* *Cursiva* y `código`\n"
        "## Oferta\n"
        "· **Lápiz** — 1.20 EUR"
    )
    out = agent_ai._plain_chat_preserve_bold(raw)
    lines = out.splitlines()
    # La negrita es la única excepción: se conserva intacta (los productos la
    # usan y el widget la renderiza); todo lo demás se limpia.
    assert lines[0] == "**Resumen de ventas**"
    assert lines[1] == "**Cubo Mágico**: 3.50 EUR, 10 disponibles"
    assert lines[2] == "Cursiva y código"
    assert lines[3] == "Oferta"
    assert lines[4] == "**Lápiz** — 1.20 EUR"
    for artifact in ("`", "##", "- **", "* *"):
        assert artifact not in out


def test_keeps_plain_sentences_untouched() -> None:
    text = "¡Claro! Tenemos bolis azules.\n\n¿Te preparo un presupuesto?"
    assert agent_ai._plain_chat_preserve_bold(text) == text


def test_single_star_emphasis_stripped_bold_pair_survives() -> None:
    out = agent_ai._plain_chat_preserve_bold(
        "Te recomiendo *este* y también **Producto Premium**."
    )
    assert out == "Te recomiendo este y también **Producto Premium**."


def test_extractive_fallback_uses_bold_names_and_no_bullets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El fallback extractivo usa el mismo estilo: nombre en negrita, sin •."""

    monkeypatch.setattr(agent_ai, "_real_llm_configured", lambda: False)
    products = [
        {
            "name": "Cubo Mágico",
            "sku": "SKU-01",
            "category": "Escritura",
            "unit_price": 3.5,
            "available_stock": 10,
        },
        {
            "name": "Lápiz",
            "sku": "SKU-02",
            "category": "Escritura",
            "unit_price": 1.2,
            "available_stock": 0,
        },
    ]
    result = asyncio.run(
        agent_ai.commerce_chat(
            db=None, query="cubos", products=products, intent="search"
        )
    )
    answer = result["answer"]
    assert "**Cubo Mágico** (SKU-01): 3.50 EUR, 10 disponibles." in answer
    assert "**Lápiz** (SKU-02): 1.20 EUR, sin existencias disponibles." in answer
    assert "• " not in answer
    assert "| SKU=" not in answer
