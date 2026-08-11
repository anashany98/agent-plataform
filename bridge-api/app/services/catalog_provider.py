"""Proveedores de catálogo (Fase B, T-022).

Introduce el contrato ``CatalogProvider`` y dos implementaciones reales:

- ``LocalCatalogProvider`` — proveedor **por defecto**: sirve el catálogo
  local de confianza (orígenes ``local``/``import``) sin dependencias
  externas. Es el corazón del core sin PrestaShop (RA-04 / PR-27).
- ``PrestaShopCatalogProvider`` — sirve exclusivamente productos
  sincronizados desde la tienda (origen ``prestashop``), que es la fuente
  autoritativa cuando PrestaShop está configurado.

``active_catalog_provider`` decide cuál usar según ``CATALOG_PROVIDER``
(``auto`` = PrestaShop si está configurado, si no local) y la configuración
real del adaptador. El chat comercial y los helpers de catálogo consumen
siempre el proveedor activo en lugar de hardcodear ``source``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.config import settings
from app.services.deterministic_tools import DeterministicToolsService

LOCAL_CATALOG_SOURCES = frozenset({"local", "import"})
PRESTASHOP_CATALOG_SOURCES = frozenset({"prestashop"})


@runtime_checkable
class CatalogProvider(Protocol):
    """Contrato de un proveedor de catálogo.

    Un proveedor declara los orígenes que sirve (``sources``) y devuelve
    productos visibles del catálogo de confianza para una consulta. La
    búsqueda es determinista y nunca expone demo ni productos sintéticos.
    """

    sources: frozenset[str]

    def search(
        self,
        query: str = "",
        limit: int = 50,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]: ...


class LocalCatalogProvider:
    """Catálogo local de confianza (orígenes ``local``/``import``).

    Es el proveedor real por defecto: sin PrestaShop configurado, el chat
    responde con estos productos (RA-04). Toda búsqueda pasa por
    ``DeterministicToolsService.search_products`` con el filtro de fuentes,
    de modo que nunca aparecen demo ni productos de otras fuentes.
    """

    sources: frozenset[str] = LOCAL_CATALOG_SOURCES

    def __init__(self, db: Session) -> None:
        self._tools = DeterministicToolsService(db)

    def search(
        self,
        query: str = "",
        limit: int = 50,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_query = category if (category and not query) else query
        return self._tools.search_products(
            effective_query,
            limit=limit,
            sources=self.sources,
        )


class PrestaShopCatalogProvider:
    """Catálogo sincronizado desde PrestaShop (origen ``prestashop``)."""

    sources: frozenset[str] = PRESTASHOP_CATALOG_SOURCES

    def __init__(self, db: Session) -> None:
        self._tools = DeterministicToolsService(db)

    def search(
        self,
        query: str = "",
        limit: int = 50,
        *,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_query = category if (category and not query) else query
        return self._tools.search_products(
            effective_query,
            limit=limit,
            sources=self.sources,
        )


def _prestashop_is_configured() -> bool:
    try:
        from app.main import prestashop_adapter

        return bool(prestashop_adapter.configured())
    except Exception:
        return False


def active_catalog_provider(db: Session) -> CatalogProvider:
    """Devuelve el proveedor de catálogo activo según configuración.

    ``CATALOG_PROVIDER`` acepta ``auto`` (PrestaShop si está configurado,
    si no local), ``local`` (fuerza LocalCatalogProvider) o ``prestashop``
    (fuerza PrestaShopCatalogProvider). Ante un valor inválido se cae a
    ``auto`` con log, nunca a un proveedor inexistente.
    """

    choice = str(settings.CATALOG_PROVIDER or "auto").strip().lower()
    if choice == "local":
        return LocalCatalogProvider(db)
    if choice == "prestashop":
        return PrestaShopCatalogProvider(db)
    if choice == "auto" and _prestashop_is_configured():
        return PrestaShopCatalogProvider(db)
    return LocalCatalogProvider(db)
