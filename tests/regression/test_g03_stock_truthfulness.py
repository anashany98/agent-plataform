"""G-03: el chat nunca afirma disponibilidad de un producto agotado.

Cubre el post-filtro determinista ``_scrub_unavailable_stock_claims``:
las menciones de productos verificados sin stock reciben siempre una nota
correctora veraz; con stock positivo o sin menciones la respuesta sale
intacta. Residual documentado de T-038/T-040 (LLM-as-judge).
"""

from __future__ import annotations

from app.main import _scrub_unavailable_stock_claims


def test_appends_note_for_out_of_stock_mention():
    reply = "El router TP-Link AX3000 está disponible ahora mismo."
    products = [
        {"name": "Router TP-Link AX3000", "sku": "TPL-AX3", "stock_quantity": 0},
    ]
    result = _scrub_unavailable_stock_claims(reply, products)
    assert result.startswith(reply)
    assert "Actualización de disponibilidad" in result
    assert "Router TP-Link AX3000" in result
    assert "sin stock disponible ahora mismo." in result


def test_keeps_reply_when_stock_positive():
    reply = "Tenemos el Router AX3000 listo para enviar."
    products = [{"name": "Router AX3000", "sku": "R1", "stock_quantity": 7}]
    assert _scrub_unavailable_stock_claims(reply, products) == reply


def test_untouched_when_product_not_mentioned():
    reply = "¿Buscabas algo en concreto?"
    products = [{"name": "Producto X", "sku": "PX", "stock_quantity": 0}]
    assert _scrub_unavailable_stock_claims(reply, products) == reply


def test_available_false_counts_as_no_stock():
    reply = "La Webcam Pro tiene unidades."
    products = [
        {
            "name": "Webcam Pro",
            "sku": "WC-1",
            "stock_quantity": None,
            "available": False,
        },
    ]
    result = _scrub_unavailable_stock_claims(reply, products)
    assert "Webcam Pro" in result
    assert "sin stock disponible" in result


def test_sku_mention_triggers_note_with_sku_label():
    reply = "El modelo TPL-AX3 es una gran opción con envío hoy."
    products = [{"name": "", "sku": "TPL-AX3", "stock_quantity": 0}]
    result = _scrub_unavailable_stock_claims(reply, products)
    assert "TPL-AX3 sin stock disponible" in result


def test_lists_multiple_capped_at_five():
    reply = "Disponibles ahora: Prod A, Prod B, Prod C, Prod D, Prod E, Prod F y Prod G."
    products = [
        {"name": f"Prod {letter}", "sku": letter, "stock_quantity": 0}
        for letter in "ABCDEFG"
    ]
    result = _scrub_unavailable_stock_claims(reply, products)
    suffix = result.split("Actualización de disponibilidad: ", 1)[1]
    for letter in "ABCDE":
        assert f"Prod {letter}" in suffix
    assert "Prod F" not in suffix
    assert "Prod G" not in suffix


def test_idempotent_when_note_already_present():
    reply = (
        "Hay stock del Widget.\n\n"
        "Actualización de disponibilidad: Widget "
        "sin stock disponible ahora mismo."
    )
    products = [{"name": "Widget", "sku": "W1", "stock_quantity": 0}]
    assert _scrub_unavailable_stock_claims(reply, products) == reply


def test_tolerates_malformed_entries():
    reply = "Hablando del ABC-1 en general."
    products = [
        "no-es-un-dict",
        {"name": "ABC-1", "stock_quantity": "no-numérico"},
        {"sku": None},
    ]
    result = _scrub_unavailable_stock_claims(reply, products)
    assert "ABC-1" in result
    assert "sin stock disponible" in result


def test_noop_guards():
    assert _scrub_unavailable_stock_claims("", [{"name": "X", "stock_quantity": 0}]) == ""
    assert _scrub_unavailable_stock_claims("texto", []) == "texto"
    assert _scrub_unavailable_stock_claims("texto", None) == "texto"
