"""Endurecimiento del buscador contra tokens cortos (2 caracteres).

Tokens como ``de``, ``es``, ``un`` matcheaban SKUs y nombres por
subcadena (``de`` → ``demo``, ``es`` → ``mesa``, ``un`` → ``unidad``)
con peso alto de SKU (+12), produciendo falsos positivos en preguntas no
relacionadas. ``_search_tokens`` ahora exige un mínimo de 3 caracteres.

Los productos se eliminan al final y las aserciones comparan solo el
conjunto propio: la BD de sesión es compartida por todo el corpus y otros
tests pueden haber dejado productos con nombres similares.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.models.models import Product
from app.services.deterministic_tools import DeterministicToolsService

MARKER = uuid.uuid4().hex[:6]

OWN_NAMES = {
    "Escritorio Modelo Demo",
    "Mesa de Reuniones",
    "Silla Ergonómica",
    "Unidad de Almacenaje",
}


def _make_product(sku: str, name: str, *, category: str = "Oficina") -> Product:
    return Product(
        id=f"prod-{uuid.uuid4().hex[:12]}",
        sku=f"{MARKER}-{sku}",
        name=f"{name}",
        category=category,
        source="local",
        base_price=Decimal("10.00"),
        tax_rate=Decimal("0.21"),
        stock_quantity=5,
        reserved_stock=0,
    )


def _own_hits(names: set[str]) -> set[str]:
    return names & OWN_NAMES


def test_two_character_tokens_do_not_match_by_substring() -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            # "de" está en "desk demo"; "es" en "mesa"/"escritorio";
            # "un" en "unidad". Sin el endurecimiento, todos estos
            # productos serían falsos positivos para consultas "de"/"es"/"un".
            _make_product("DESK-DEMO-001", "Escritorio Modelo Demo"),
            _make_product("MESA-ESCR-002", "Mesa de Reuniones"),
            _make_product("SILLA-ERG-003", "Silla Ergonómica"),
            _make_product("UNIDAD-ALU-004", "Unidad de Almacenaje"),
        ]
        db.add_all(created)
        db.commit()

        tools = DeterministicToolsService(db)
        # Tokens de 2 caracteres: jamás producen resultados.
        assert tools.search_products("de", limit=20) == []
        assert tools.search_products("es", limit=20) == []
        assert tools.search_products("un", limit=20) == []

        # Mezcla: solo el término significativo participa y no arrastra
        # falsos positivos propios (ni "de" ni "un" deben sumar).
        names = {row["name"] for row in tools.search_products("de un escritorio", limit=20)}
        assert _own_hits(names) == {"Escritorio Modelo Demo"}, f"falsos positivos: {_own_hits(names)}"

        # Los tokens de 3+ caracteres siguen funcionando.
        names = {row["name"] for row in tools.search_products("silla", limit=20)}
        assert _own_hits(names) == {"Silla Ergonómica"}, names
        names = {row["name"] for row in tools.search_products("mesa", limit=20)}
        assert _own_hits(names) == {"Mesa de Reuniones"}, names
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()
