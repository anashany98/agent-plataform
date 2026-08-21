"""Agregación SQL por categorías para el resumen 'ver todo el catálogo'.

Las funciones ``_build_catalog_categories_summary`` y
``_build_categories_brief`` cargaban hasta 10.000 productos en memoria
(``search_products("", limit=10_000)``) para agrupar por categoría en
Python. Ahora agregan con SQL ``GROUP BY`` (una consulta por conteo, otra
por ejemplo representativo con ``ROW_NUMBER``) y el resumen se reactivó en
el chat para responder 'ver todo el catálogo' sin volcar productos cuando
el catálogo supera el cap. Este test verifica el agregado, los filtros
(no-demo, fuentes del proveedor, disponibilidad comercial) y el texto del
resumen.

Los productos insertados se eliminan al final: la BD de sesión es
compartida por todo el corpus y los productos ``prestashop`` des-saltarían
los E2E de catálogo que dependen de la ausencia de catálogo sincronizado.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.main import (
    _build_catalog_categories_summary,
    _build_categories_brief,
    _catalog_category_counts,
)
from app.models.models import Product


def _make_product(category: str, *, source: str = "local", **overrides: object) -> Product:
    values: dict[str, object] = {
        "id": f"prod-{uuid.uuid4().hex[:12]}",
        "sku": f"SKU-{uuid.uuid4().hex[:8].upper()}",
        "name": f"Producto {category} {uuid.uuid4().hex[:6]}",
        "category": category,
        "source": source,
        "base_price": Decimal("10.00"),
        "tax_rate": Decimal("0.21"),
        "stock_quantity": 5,
        "reserved_stock": 0,
    }
    values.update(overrides)
    return Product(**values)  # type: ignore[arg-type]


def test_catalog_category_counts_aggregates_by_category() -> None:
    marker = uuid.uuid4().hex[:6]
    category_a = f"Cat-A-{marker}"
    category_b = f"Cat-B-{marker}"
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product(category_a, name=f"Alpha Uno {marker}"),
            _make_product(category_a, name=f"Alpha Dos {marker}"),
            _make_product(category_a, name=f"Alpha Tres {marker}"),
            _make_product(category_b, name=f"Beta Uno {marker}"),
            _make_product(category_b, name=f"Beta Dos {marker}"),
            _make_product("", name=f"Sin categoría {marker}"),
        ]
        db.add_all(created)
        db.commit()

        counts = _catalog_category_counts(db)
        by_category = dict(counts)
        # Categorías vacías se agrupan en "Otros"; el agregado es exacto.
        assert by_category[category_a] == 3
        assert by_category[category_b] == 2
        assert by_category["Otros"] == 1
        # Orden: count desc (con empate, nombre asc).
        positions = {category: index for index, (category, _) in enumerate(counts)}
        assert positions[category_a] < positions[category_b]
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_categories_summary_builds_breakdown_with_examples() -> None:
    marker = uuid.uuid4().hex[:6]
    category = f"Cat-Sum-{marker}"
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product(category, name=f"Portátil {marker}"),
            _make_product(category, name=f"Ratón {marker}"),
        ]
        db.add_all(created)
        db.commit()

        summary = _build_catalog_categories_summary(db, max_categories=100)
        assert summary["total"] >= 2
        assert summary["n_categories"] >= 1
        # El desglose muestra la categoría, su conteo y un ejemplo
        # representativo (el primer producto alfabético).
        assert category in summary["breakdown"]
        assert f"{category}: 2 producto(s)" in summary["breakdown"]
        assert f"Portátil {marker}" in summary["breakdown"]
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_categories_brief_returns_counts() -> None:
    marker = uuid.uuid4().hex[:6]
    category = f"Cat-Brief-{marker}"
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product(category, name=f"Uno {marker}"),
            _make_product(category, name=f"Dos {marker}"),
        ]
        db.add_all(created)
        db.commit()

        brief = _build_categories_brief(db)
        assert brief["by_category"][category] == 2
        assert brief["total"] >= 2
        assert brief["n_categories"] >= 1
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_counts_exclude_unavailable_prestashop_products() -> None:
    marker = uuid.uuid4().hex[:6]
    category = f"Cat-PS-{marker}"
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            # Sin flags de comercio activos: no es comercializable.
            _make_product(
                category,
                name=f"Oculto {marker}",
                source="prestashop",
                attributes={"active": False, "show_price": False, "available_for_order": False},
            ),
            # Con los tres flags activos: sí es visible.
            _make_product(
                category,
                name=f"Visible {marker}",
                source="prestashop",
                attributes={"active": True, "show_price": True, "available_for_order": True},
            ),
        ]
        db.add_all(created)
        db.commit()

        # Fuentes que incluyen prestashop para aislar la disponibilidad.
        counts = _catalog_category_counts(db, sources={"prestashop"})
        assert dict(counts).get(category) == 1
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()
