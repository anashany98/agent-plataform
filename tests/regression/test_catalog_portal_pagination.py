"""Catálogo del portal paginado: ``GET /catalog/products`` (pendiente de la
remediación de auditoría 2026-08-10).

El portal operativo no puede volcar catálogos de decenas de miles de
productos (41.652 sincronizados en vivo). Este endpoint devuelve un
envelope ``{items, total, limit, offset}`` con:

- Paginación SQL estable (``sort``/``order`` whitelisted) sin query.
- Búsqueda léxica con la misma relevancia que el chat cuando hay query
  (la paginación recorre el ranking y ``sort`` se ignora).
- Filtro opcional por origen y exclusión fail-closed de demo/productos
  no disponibles comercialmente.
- ``created_at``/``updated_at`` en cada fila para mostrar frescura.

Hermeticidad D-032: los productos de prueba se crean con SKUs marcados y
se eliminan al final; las aserciones comparan solo el conjunto propio
(la BD de sesión es compartida por todo el corpus).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.models.models import Product

MARKER = f"CPP-{uuid.uuid4().hex[:6]}"


def _make_product(
    sku: str,
    name: str,
    *,
    category: str = "Oficina",
    source: str = "local",
    price: str = "10.00",
    stock: int = 5,
    attributes: dict | None = None,
) -> Product:
    return Product(
        id=f"prod-{uuid.uuid4().hex[:12]}",
        sku=f"{MARKER}-{sku}",
        name=name,
        category=category,
        source=source,
        attributes=attributes,
        base_price=Decimal(price),
        tax_rate=Decimal("0.21"),
        stock_quantity=stock,
        reserved_stock=0,
    )


def _own_ids(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows if row["sku"].startswith(f"{MARKER}-")}


def _own_names(rows: list[dict]) -> set[str]:
    return {row["name"] for row in rows if row["sku"].startswith(f"{MARKER}-")}


def test_catalog_products_envelope_and_freshness(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product("AAA-001", "Lapiz Grafito 2B", price="1.20"),
            _make_product("AAA-002", "Goma de Borrar Blanca", price="0.80"),
            _make_product("AAA-003", "Regla Metalica 30cm", price="2.50"),
        ]
        db.add_all(created)
        db.commit()

        response = client.get("/catalog/products?limit=50", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"items", "total", "limit", "offset"}
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert body["total"] >= len(created)

        own = [row for row in body["items"] if row["sku"].startswith(f"{MARKER}-")]
        assert len(own) == len(created)
        for row in own:
            # Frescura: la fila expone cuándo se creó/actualizó.
            assert row["created_at"] and row["updated_at"]
            assert row["created_at"].endswith("Z")
            assert row["unit_price"] > 0
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_pagination_is_disjoint_and_stable(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        for index in range(7):
            created.append(
                _make_product(
                    f"PAGE-{index:03d}",
                    f"Articulo Paginado {index:02d}",
                    price=f"{1.0 + index:.2f}",
                )
            )
        db.add_all(created)
        db.commit()

        page_one = client.get(
            "/catalog/products?limit=3&offset=0&sort=name&order=asc",
            headers=auth_headers,
        ).json()
        page_two = client.get(
            "/catalog/products?limit=3&offset=3&sort=name&order=asc",
            headers=auth_headers,
        ).json()

        ids_one = _own_ids(page_one["items"])
        ids_two = _own_ids(page_two["items"])
        assert len(ids_one) == 3 and len(ids_two) == 3
        assert ids_one.isdisjoint(ids_two)
        assert page_one["total"] == page_two["total"]
        assert page_two["offset"] == 3

        # Sin cambios en el catálogo, la misma página es idéntica (estable).
        again = client.get(
            "/catalog/products?limit=3&offset=0&sort=name&order=asc",
            headers=auth_headers,
        ).json()
        assert [row["id"] for row in again["items"]] == [
            row["id"] for row in page_one["items"]
        ]
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_sort_and_order(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product("SORT-001", "Zeta Ultimo", price="3.00"),
            _make_product("SORT-002", "Alfa Primero", price="1.00"),
            _make_product("SORT-003", "Media Precio", price="2.00"),
        ]
        db.add_all(created)
        db.commit()

        descending = client.get(
            "/catalog/products?limit=10&sort=unit_price&order=desc",
            headers=auth_headers,
        ).json()
        own_desc = [row for row in descending["items"] if row["sku"].startswith(f"{MARKER}-")]
        assert [row["unit_price"] for row in own_desc] == [3.0, 2.0, 1.0]

        by_name = client.get(
            "/catalog/products?limit=10&sort=name&order=asc",
            headers=auth_headers,
        ).json()
        own_names = [row for row in by_name["items"] if row["sku"].startswith(f"{MARKER}-")]
        assert [row["name"] for row in own_names] == [
            "Alfa Primero",
            "Media Precio",
            "Zeta Ultimo",
        ]

        by_freshness = client.get(
            "/catalog/products?limit=10&sort=updated_at&order=desc",
            headers=auth_headers,
        ).json()
        assert isinstance(by_freshness, dict) and "items" in by_freshness
        assert by_freshness["total"] >= len(created)
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_source_filter_and_demo_exclusion(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product("SRC-001", "Producto Local Uno", source="local"),
            _make_product("SRC-002", "Producto Importado", source="import"),
            _make_product(
                "SRC-003",
                "Producto Tienda",
                source="prestashop",
                attributes={"active": True, "show_price": True, "available_for_order": True},
            ),
            _make_product("SRC-004", "Producto Demo Oculto", source="demo"),
        ]
        db.add_all(created)
        db.commit()

        all_rows = client.get("/catalog/products?limit=100", headers=auth_headers).json()
        assert "Producto Demo Oculto" not in _own_names(all_rows["items"])

        prestashop = client.get(
            "/catalog/products?limit=100&source=prestashop",
            headers=auth_headers,
        ).json()
        own_ps = [row for row in prestashop["items"] if row["sku"].startswith(f"{MARKER}-")]
        assert [row["name"] for row in own_ps] == ["Producto Tienda"]
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_hides_non_sellable_prestashop(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product(
                "HID-001",
                "Visibilidad Oculta",
                source="prestashop",
                attributes={"active": True, "show_price": False, "available_for_order": True},
            ),
            _make_product(
                "HID-002",
                "Visibilidad Correcta",
                source="prestashop",
                attributes={"active": True, "show_price": True, "available_for_order": True},
            ),
        ]
        db.add_all(created)
        db.commit()

        rows = client.get("/catalog/products?limit=100&source=prestashop", headers=auth_headers).json()
        own = [row for row in rows["items"] if row["sku"].startswith(f"{MARKER}-")]
        assert _own_names(own) == {"Visibilidad Correcta"}
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_query_pages_relevance_ranking(client, auth_headers) -> None:
    db = SessionLocal()
    created: list[Product] = []
    try:
        created = [
            _make_product("QRY-001", "Silla Ergonómica Negra", category="Sillas"),
            _make_product("QRY-002", "Silla de Oficina Azul", category="Sillas"),
            _make_product("QRY-003", "Mesa de Reuniones", category="Mobiliario"),
        ]
        db.add_all(created)
        db.commit()

        first = client.get(
            "/catalog/products?query=silla&limit=2&offset=0",
            headers=auth_headers,
        ).json()
        assert first["total"] >= 2
        assert len(first["items"]) == 2
        assert "Silla Ergonómica Negra" in _own_names(first["items"])

        second = client.get(
            "/catalog/products?query=silla&limit=2&offset=2",
            headers=auth_headers,
        ).json()
        assert _own_ids(first["items"]).isdisjoint(_own_ids(second["items"]))
        # "Mesa" no matchea "silla": queda fuera del ranking propio.
        assert "Mesa de Reuniones" not in _own_names(first["items"])
        assert "Mesa de Reuniones" not in _own_names(second["items"])
    finally:
        for product in created:
            db.delete(product)
        db.commit()
        db.close()


def test_catalog_products_rejects_invalid_params(client, auth_headers) -> None:
    invalid_sort = client.get("/catalog/products?sort=stock_quantity", headers=auth_headers)
    assert invalid_sort.status_code == 422, invalid_sort.text

    invalid_order = client.get("/catalog/products?order=sideways", headers=auth_headers)
    assert invalid_order.status_code == 422, invalid_order.text

    too_big_limit = client.get("/catalog/products?limit=500", headers=auth_headers)
    assert too_big_limit.status_code == 422, too_big_limit.text

    negative_offset = client.get("/catalog/products?offset=-5", headers=auth_headers)
    assert negative_offset.status_code == 422, negative_offset.text
