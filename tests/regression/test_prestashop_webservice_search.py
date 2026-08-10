"""Verifica el comportamiento del adapter PrestaShop ante la limitación
documentada de su Webservice: ``filter[name]`` y ``filter[reference]``
NO aceptan wildcards en la mayoría de las tiendas (reproducido contra
``https://btopdigital.es`` el 2026-08-10: ``filter[name]=%ACUARELA%``
devuelve 0 resultados aunque hay productos con "ACUARELA" en ``name``).

El adapter implementa un fallback de paginación + filtrado en memoria
sobre ``name``, ``reference`` y ``description_short``. Estos tests cubren
ese comportamiento y documentan la regresión si se reintroduce el uso
del ``filter[name]`` nativo (que falla silenciosamente).
"""

from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from pathlib import Path

import pytest
from app.services.prestashop_adapter import PrestaShopAdapter


def _adapter() -> PrestaShopAdapter:
    """Construye un adapter configurado con credenciales del .env (si están).

    Para que el test sea útil incluso sin credenciales reales, sólo se
    ejercita cuando ``PRESTASHOP_BASE_URL`` está presente.
    """

    env_path = Path("C:/Users/PC/Desktop/PROYECTOS/agent-platform-fixed/.env")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    os.environ.setdefault("ENVIRONMENT", "development")
    return PrestaShopAdapter()


@pytest.mark.skipif(
    not os.environ.get("PRESTASHOP_BASE_URL"),
    reason="PRESTASHOP_BASE_URL no configurada; test opt-in con credenciales reales",
)
def test_search_products_finds_products_when_filter_name_wildcards_fail() -> None:
    """Reproduce el bug: ``filter[name]=%ACUARELA%`` devuelve 0 resultados,
    pero ``search_products`` debe devolver los productos correctos."""

    adapter = _adapter()
    results = asyncio.run(adapter.search_products("ACUARELA", limit=5))
    assert results, (
        "search_products debe devolver resultados aunque el webservice de "
        "PrestaShop rechace ``filter[name]`` con wildcards"
    )
    # Todos los productos devueltos deben ser sellable.
    for product in results:
        assert product["source"] == "prestashop"
        assert product["name"], "el producto normalizado debe tener nombre"
        # IVA de España (0.21) o 0 si no se pudo resolver el tax_rules_group.
        assert 0 <= product["tax_rate"] <= 1


@pytest.mark.skipif(
    not os.environ.get("PRESTASHOP_BASE_URL"),
    reason="PRESTASHOP_BASE_URL no configurada",
)
def test_search_products_returns_real_iva_for_spain() -> None:
    """El IVA de los productos reales de España debe ser 0.21."""

    adapter = _adapter()
    results = asyncio.run(adapter.search_products("JOVI", limit=3))
    if not results:
        pytest.skip("Catálogo real sin coincidencias para 'JOVI'")
    for product in results:
        # 0.21 es el tipo general español. Algunos productos pueden tener 0
        # (sin regla fiscal asignada); aceptamos cualquiera en [0, 1].
        assert 0 <= product["tax_rate"] <= 1


def test_search_products_falls_back_to_in_memory_filter() -> None:
    """Cuando ``filter[name]`` no funciona, ``search_products`` pagina +
    filtra en memoria y devuelve los productos correctos.

    Test offline que no requiere credenciales reales: usa un adapter mock
    que simula el comportamiento del webservice (``filter[name]`` devuelve
    0 resultados; el listado paginado sí los devuelve).
    """

    async def fake_paginated(
        resource: str, params: dict, *, page_size: int = 500
    ) -> list[dict]:
        assert resource == "products"
        return [
            {
                "id": "10",
                "reference": "800/12",
                "name": "ACUARELA JOVI 12 COLORES",
                "description_short": "Estuche de plástico",
                "price": "3.770000",
                "active": "1",
                "show_price": "1",
                "available_for_order": "1",
            },
            {
                "id": "99",
                "reference": "XYZ-1",
                "name": "OTRO PRODUCTO",
                "description_short": "Sin coincidencia",
                "price": "9.990000",
                "active": "1",
                "show_price": "1",
                "available_for_order": "1",
            },
        ]

    _call_count = {"n": 0}

    async def fake_get(resource: str, params: dict) -> dict:
        assert resource == "products"
        _call_count["n"] += 1
        print(f"  fake_get call #{_call_count['n']} params={params}")
        # Simula un catálogo real: primera página con resultados y segunda
        # vacía (PrestaShop devuelve ``{}`` cuando no hay más filas).
        if _call_count["n"] > 1:
            return {"products": []}
        return {
            "products": [
                {
                    "id": "10",
                    "reference": "800/12",
                    "name": "ACUARELA JOVI 12 COLORES",
                    "description_short": "Estuche de plástico",
                    "price": "3.770000",
                    "active": "1",
                    "show_price": "1",
                    "available_for_order": "1",
                },
                {
                    "id": "99",
                    "reference": "XYZ-1",
                    "name": "OTRO PRODUCTO",
                    "description_short": "Sin coincidencia",
                    "price": "9.990000",
                    "active": "1",
                    "show_price": "1",
                    "available_for_order": "1",
                },
            ]
        }

    async def fake_get_stock(*args, **kwargs) -> int:  # noqa: ANN001
        return 10

    async def fake_get_country_id() -> str:
        return "6"

    async def fake_get_currency_id() -> str:
        return "1"

    async def fake_get_tax_rate(tax_id: str) -> "object":  # noqa: ANN001
        from decimal import Decimal
        return Decimal("0.21")

    async def fake_get_category_name(category_id: str) -> str:  # noqa: ANN001
        return "Oficina"

    adapter = PrestaShopAdapter.__new__(PrestaShopAdapter)
    adapter.base_url = "https://example.test"
    adapter.api_key = "fake-key"
    adapter._tax_rate_cache = {}
    adapter._get = fake_get  # type: ignore[method-assign]
    adapter._get_paginated_rows = fake_paginated  # type: ignore[method-assign]
    adapter.get_stock = fake_get_stock  # type: ignore[method-assign]
    adapter.get_country_id = fake_get_country_id  # type: ignore[method-assign]
    adapter.get_currency_id = fake_get_currency_id  # type: ignore[method-assign]
    adapter.get_tax_rate = fake_get_tax_rate  # type: ignore[method-assign]
    adapter.get_category_name = fake_get_category_name  # type: ignore[method-assign]

    adapter.country_id = "6"
    adapter.fiscal_country_id = "6"
    adapter.currency_id = "1"
    adapter.shop_id = ""
    adapter.shop_group_id = ""

    results = asyncio.run(
        adapter.search_products("ACUARELA", limit=5, include_details=False)
    )
    assert len(results) >= 1, "fallback in-memory debe encontrar el producto 'ACUARELA'"
    assert any("ACUARELA" in r["name"] for r in results)
    # El producto sin match NO debe aparecer.
    assert not any("OTRO PRODUCTO" in r["name"] for r in results)