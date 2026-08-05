from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.config import settings
from app.services.resilience import CircuitOpenError, guarded_request_with_retry


class PrestaShopIntegrationError(RuntimeError):
    pass


class PrestaShopAdapter:
    """Adaptador de solo lectura para PrestaShop Webservice.

    PrestaShop conserva la autoridad sobre catálogo, combinaciones, precio y
    existencias. El Bridge mantiene únicamente una caché local de lectura para
    búsqueda, trazabilidad y recomendaciones. Ningún método escribe en la
    tienda.
    """

    _PAGE_SIZE = 500
    _MAX_PAGES = 200
    _COMMERCE_FLAGS = ("active", "show_price", "available_for_order")

    def __init__(self) -> None:
        self.base_url = settings.PRESTASHOP_BASE_URL.rstrip("/")
        self.api_key = settings.PRESTASHOP_API_KEY
        self.shop_id = settings.PRESTASHOP_SHOP_ID
        self.shop_group_id = settings.PRESTASHOP_SHOP_GROUP_ID
        self.country_id = settings.PRESTASHOP_COUNTRY_ID
        self.fiscal_country_id = settings.PRESTASHOP_COUNTRY_ID
        self.currency_id = settings.PRESTASHOP_CURRENCY_ID
        self._tax_rate_cache: dict[tuple[str, str], Decimal] = {}

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _get(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured():
            raise PrestaShopIntegrationError("PrestaShop no está configurado")
        request_params = {**params, "output_format": "JSON"}
        if self.shop_id:
            request_params["id_shop"] = self.shop_id
        if self.shop_group_id:
            request_params["id_group_shop"] = self.shop_group_id
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                auth=(self.api_key, ""),
                follow_redirects=False,
                headers={"Accept": "application/json"},
            ) as client:
                response = await guarded_request_with_retry(
                    "prestashop",
                    lambda: client.get(f"{self.base_url}/api/{resource}", params=request_params),
                )
                response.raise_for_status()
                payload = response.json()
                # PrestaShop devuelve [] (array vacío) cuando no hay resultados;
                # lo tratamos como colección vacía, no como error de formato.
                if isinstance(payload, list):
                    if not payload:
                        return {}
                    raise PrestaShopIntegrationError("PrestaShop devolvió un formato inesperado")
                if not isinstance(payload, dict):
                    raise PrestaShopIntegrationError("PrestaShop devolvió un formato inesperado")
                return payload
        except PrestaShopIntegrationError:
            raise
        except CircuitOpenError as exc:
            raise PrestaShopIntegrationError(
                f"Circuito hacia PrestaShop abierto; la llamada se rechazó sin tocar la red: {exc}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise PrestaShopIntegrationError(f"Error de PrestaShop: {exc}") from exc

    @staticmethod
    def _rows(payload: Dict[str, Any], resource: str) -> List[Dict[str, Any]]:
        rows = payload.get(resource) or []
        if isinstance(rows, dict):
            rows = [rows]
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _enabled_flag(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true"}

    @classmethod
    def _is_sellable_product(cls, product: Dict[str, Any]) -> bool:
        return all(cls._enabled_flag(product.get(field)) for field in cls._COMMERCE_FLAGS)

    @classmethod
    def _require_sellable_product(cls, product: Dict[str, Any], product_id: str) -> None:
        if not cls._is_sellable_product(product):
            raise PrestaShopIntegrationError(
                f"El producto {product_id} no está activo, visible y disponible para pedidos"
            )

    async def _get_paginated_rows(
        self,
        resource: str,
        params: Dict[str, Any],
        *,
        page_size: int = _PAGE_SIZE,
    ) -> List[Dict[str, Any]]:
        """Read a stable remote collection without accepting silent truncation."""

        base_params = dict(params)
        base_params.pop("limit", None)
        rows: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page_number in range(self._MAX_PAGES):
            offset = page_number * page_size
            payload = await self._get(
                resource,
                {**base_params, "limit": f"{offset},{page_size}"},
            )
            page = self._rows(payload, resource)
            if len(page) > page_size:
                raise PrestaShopIntegrationError(
                    f"Respuesta inválida durante la paginación de {resource}"
                )

            page_ids: set[str] = set()
            for row in page:
                row_id = str(row.get("id") or "").strip()
                if not row_id or row_id in page_ids or row_id in seen_ids:
                    raise PrestaShopIntegrationError(
                        f"Respuesta inestable durante la paginación de {resource}"
                    )
                page_ids.add(row_id)

            rows.extend(page)
            seen_ids.update(page_ids)
            if len(page) < page_size:
                return rows

        raise PrestaShopIntegrationError(
            f"Se superó el límite seguro de paginación de {resource}"
        )

    async def _get_rows_by_ids(
        self,
        resource: str,
        ids: Iterable[Any],
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        normalized_ids = [str(value).strip() for value in ids]
        if not normalized_ids or any(not value for value in normalized_ids):
            raise PrestaShopIntegrationError(
                f"Asociaciones inválidas al recuperar {resource}"
            )
        unique_ids = list(dict.fromkeys(normalized_ids))
        result: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for offset in range(0, len(unique_ids), self._PAGE_SIZE):
            chunk = unique_ids[offset : offset + self._PAGE_SIZE]
            payload = await self._get(
                resource,
                {
                    **params,
                    "filter[id]": self._filter_ids(chunk),
                    "limit": f"0,{self._PAGE_SIZE}",
                },
            )
            page = self._rows(payload, resource)
            page_ids = [str(row.get("id") or "").strip() for row in page]
            expected_ids = set(chunk)
            if (
                any(not row_id for row_id in page_ids)
                or len(page_ids) != len(set(page_ids))
                or set(page_ids) != expected_ids
                or seen_ids.intersection(page_ids)
            ):
                raise PrestaShopIntegrationError(
                    f"Respuesta incompleta durante la paginación de {resource}"
                )
            result.extend(page)
            seen_ids.update(page_ids)
        return result

    @staticmethod
    def _filter_ids(values: Iterable[Any]) -> str:
        ids = [str(value).strip() for value in values if value is not None and str(value).strip()]
        return "[" + "|".join(dict.fromkeys(ids)) + "]"

    @staticmethod
    def _decimal(value: Any, *, field: str, product_id: str) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PrestaShopIntegrationError(
                f"{field} inválido para el producto {product_id}"
            ) from exc

    async def search_products(
        self,
        query: str,
        limit: int = 20,
        *,
        include_details: bool = True,
    ) -> List[Dict[str, Any]]:
        query = query.strip()
        if not query:
            raise PrestaShopIntegrationError("La búsqueda no puede estar vacía")
        safe_limit = max(1, min(limit, 100))
        search_terms = [query]
        normalized_tokens = [
            token
            for token in self._clean_html_text(query).lower().replace("?", " ").split()
            if len(token) >= 3
            and token not in {"con", "para", "una", "uno", "que", "del", "las", "los", "por", "necesito", "quiero", "busco"}
        ]
        search_terms.extend(token for token in normalized_tokens if token not in search_terms)

        found: Dict[str, Dict[str, Any]] = {}
        for term in search_terms[:8]:
            payload = await self._get(
                "products",
                {
                    "display": (
                        "[id,reference,name,description_short,price,id_category_default,"
                        "id_tax_rules_group,id_default_combination,id_shop_default,active,"
                        "manufacturer_name,available_for_order,show_price]"
                    ),
                    "filter[name]": f"%{term}%",
                    "filter[active]": "[1]",
                    "limit": f"0,{safe_limit}",
                    "sort": "[name_ASC]",
                },
            )
            for item in self._rows(payload, "products"):
                product_id = str(item.get("id") or "").strip()
                if product_id and self._is_sellable_product(item):
                    found.setdefault(product_id, item)
            if len(found) >= safe_limit:
                break

        return [
            await self._normalize_product(item, include_details=include_details)
            for item in list(found.values())[:safe_limit]
        ]

    async def list_products(
        self,
        limit: int = 300,
        offset: int = 0,
        *,
        include_details: bool = False,
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(limit, 1_000))
        payload = await self._get(
            "products",
            {
                "display": (
                    "[id,reference,name,description_short,price,id_category_default,"
                    "id_tax_rules_group,id_default_combination,id_shop_default,active,"
                    "manufacturer_name,available_for_order,show_price]"
                ),
                "filter[active]": "[1]",
                "limit": f"{max(0, offset)},{safe_limit}",
                "sort": "[id_ASC]",
            },
        )
        return [
            await self._normalize_product(item, include_details=include_details)
            for item in self._rows(payload, "products")
            if str(item.get("id") or "").strip() and self._is_sellable_product(item)
        ]

    async def _normalize_product(
        self,
        item: Dict[str, Any],
        *,
        include_details: bool,
    ) -> Dict[str, Any]:
        product_id = str(item.get("id") or "").strip()
        if not product_id:
            raise PrestaShopIntegrationError("Producto sin identificador")
        self._require_sellable_product(item, product_id)

        details: Dict[str, Any] = {}
        if include_details:
            details = await self.get_product_details(product_id)

        stock = await self.get_stock(product_id)
        base_price = self._decimal(item.get("price"), field="Precio", product_id=product_id)
        category_id = str(item.get("id_category_default") or "").strip()
        category_name = await self.get_category_name(category_id) if include_details and category_id else ""
        features = details.get("features", [])
        combinations = details.get("combinations", [])
        specific_prices = details.get("specific_prices", [])
        tax_rules_group_id = str(
            details.get("id_tax_rules_group")
            or item.get("id_tax_rules_group")
            or "0"
        )
        default_combination_id = str(
            details.get("id_default_combination")
            or item.get("id_default_combination")
            or "0"
        )
        shop_id = str(
            self.shop_id
            or details.get("id_shop_default")
            or item.get("id_shop_default")
            or "0"
        )
        tax_rate = await self.get_tax_rate(tax_rules_group_id)
        country_id = await self.get_country_id()
        currency_id = await self.get_currency_id()

        return {
            "external_id": product_id,
            "sku": str(item.get("reference") or f"PS-{product_id}").strip(),
            "name": self._localized(item.get("name")) or f"Producto {product_id}",
            "description": self._clean_html_text(self._localized(item.get("description_short"))),
            "base_price": float(base_price),
            "tax_rate": float(tax_rate),
            "stock_quantity": stock,
            "category": category_name or category_id or "PrestaShop",
            "attributes": {
                "active": self._enabled_flag(item.get("active")),
                "available_for_order": self._enabled_flag(item.get("available_for_order")),
                "show_price": self._enabled_flag(item.get("show_price")),
                "manufacturer": self._localized(item.get("manufacturer_name")),
                "id_category_default": item.get("id_category_default"),
                "tax_rules_group_id": tax_rules_group_id,
                "default_combination_id": default_combination_id,
                "shop_id": shop_id,
                "shop_group_id": str(self.shop_group_id or "0"),
                "country_id": country_id,
                "currency_id": currency_id,
                "features": features,
                "combinations": combinations,
                "specific_prices": specific_prices,
            },
            "source": "prestashop",
            "source_url": f"{self.base_url}/index.php?id_product={product_id}&controller=product",
        }

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        payload = await self._get("products", {"filter[id]": f"[{product_id}]", "display": "full"})
        products = self._rows(payload, "products")
        if not products:
            raise PrestaShopIntegrationError("Producto no encontrado en PrestaShop")
        product = products[0]
        self._require_sellable_product(product, product_id)
        product["stock_quantity"] = await self.get_stock(product_id)
        product["features"] = await self.get_features(product)
        product["combinations"] = await self.get_combinations(product_id, product)
        product["specific_prices"] = await self.get_specific_prices(product_id)
        return product

    async def get_product_details(self, product_id: str) -> Dict[str, Any]:
        payload = await self._get("products", {"filter[id]": f"[{product_id}]", "display": "full"})
        products = self._rows(payload, "products")
        if not products:
            raise PrestaShopIntegrationError("Producto no encontrado en PrestaShop")
        product = products[0]
        self._require_sellable_product(product, product_id)
        return {
            "id_tax_rules_group": str(product.get("id_tax_rules_group") or "0"),
            "id_default_combination": str(product.get("id_default_combination") or "0"),
            "id_shop_default": str(product.get("id_shop_default") or "0"),
            "features": await self.get_features(product),
            "combinations": await self.get_combinations(product_id, product),
            "specific_prices": await self.get_specific_prices(product_id),
        }

    async def get_features(self, product: Dict[str, Any]) -> List[Dict[str, Any]]:
        associations = product.get("associations") or {}
        entries = associations.get("product_features") or []
        if isinstance(entries, dict):
            entries = [entries]
        entries = [entry for entry in entries if isinstance(entry, dict)]
        if not entries:
            return []

        feature_ids = [entry.get("id") or entry.get("id_feature") for entry in entries]
        value_ids = [entry.get("id_feature_value") for entry in entries]
        try:
            feature_payload = await self._get(
                "product_features",
                {"filter[id]": self._filter_ids(feature_ids), "display": "[id,name]", "limit": "0,1000"},
            )
            value_payload = await self._get(
                "product_feature_values",
                {"filter[id]": self._filter_ids(value_ids), "display": "[id,id_feature,custom,value]", "limit": "0,1000"},
            )
        except PrestaShopIntegrationError:
            # Algunas tiendas restringen estos recursos. Mantener IDs es más
            # seguro que inventar etiquetas o impedir todo el catálogo.
            return [
                {
                    "feature_id": str(entry.get("id") or entry.get("id_feature") or ""),
                    "value_id": str(entry.get("id_feature_value") or ""),
                    "name": "",
                    "value": "",
                }
                for entry in entries
            ]

        feature_map = {
            str(row.get("id")): self._localized(row.get("name"))
            for row in self._rows(feature_payload, "product_features")
        }
        value_map = {
            str(row.get("id")): row
            for row in self._rows(value_payload, "product_feature_values")
        }
        result: List[Dict[str, Any]] = []
        for entry in entries:
            feature_id = str(entry.get("id") or entry.get("id_feature") or "")
            value_id = str(entry.get("id_feature_value") or "")
            value_row = value_map.get(value_id, {})
            result.append(
                {
                    "feature_id": feature_id,
                    "value_id": value_id,
                    "name": feature_map.get(feature_id, ""),
                    "value": self._localized(value_row.get("value")),
                    "custom": str(value_row.get("custom", "0")).lower() in {"1", "true"},
                }
            )
        return result

    async def get_combinations(
        self,
        product_id: str,
        product: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        association_rows: List[Dict[str, Any]] = []
        if product:
            associations = product.get("associations") or {}
            if not isinstance(associations, dict):
                raise PrestaShopIntegrationError(
                    f"Asociaciones de combinaciones inválidas para el producto {product_id}"
                )
            association_rows = associations.get("combinations") or []
            if isinstance(association_rows, dict):
                association_rows = [association_rows]
            if not isinstance(association_rows, list):
                raise PrestaShopIntegrationError(
                    f"Asociaciones de combinaciones inválidas para el producto {product_id}"
                )

        params: Dict[str, Any] = {
            "filter[id_product]": f"[{product_id}]",
            "display": "full",
            "sort": "[id_ASC]",
        }
        if association_rows:
            if not all(isinstance(row, dict) for row in association_rows):
                raise PrestaShopIntegrationError(
                    f"Asociaciones de combinaciones inválidas para el producto {product_id}"
                )
            params.pop("filter[id_product]", None)
            rows = await self._get_rows_by_ids(
                "combinations",
                (row.get("id") for row in association_rows),
                params,
            )
        else:
            rows = await self._get_paginated_rows("combinations", params)
        if not rows:
            return []

        option_value_ids: List[str] = []
        for row in rows:
            associations = row.get("associations") or {}
            option_values = associations.get("product_option_values") or []
            if isinstance(option_values, dict):
                option_values = [option_values]
            option_value_ids.extend(
                str(item.get("id"))
                for item in option_values
                if isinstance(item, dict) and item.get("id")
            )

        option_values_map: Dict[str, Dict[str, Any]] = {}
        group_names: Dict[str, str] = {}
        if option_value_ids:
            try:
                option_payload = await self._get(
                    "product_option_values",
                    {
                        "filter[id]": self._filter_ids(option_value_ids),
                        "display": "[id,id_attribute_group,name]",
                        "limit": "0,1000",
                    },
                )
                option_values_map = {
                    str(row.get("id")): row
                    for row in self._rows(option_payload, "product_option_values")
                }
                group_ids = [row.get("id_attribute_group") for row in option_values_map.values()]
                if group_ids:
                    group_payload = await self._get(
                        "product_options",
                        {"filter[id]": self._filter_ids(group_ids), "display": "[id,name]", "limit": "0,1000"},
                    )
                    group_names = {
                        str(row.get("id")): self._localized(row.get("name"))
                        for row in self._rows(group_payload, "product_options")
                    }
            except PrestaShopIntegrationError:
                option_values_map = {}
                group_names = {}

        result: List[Dict[str, Any]] = []
        for row in rows:
            combination_id = str(row.get("id") or "")
            associations = row.get("associations") or {}
            option_values = associations.get("product_option_values") or []
            if isinstance(option_values, dict):
                option_values = [option_values]
            normalized_options: List[Dict[str, str]] = []
            for item in option_values:
                if not isinstance(item, dict):
                    continue
                option_id = str(item.get("id") or "")
                option_row = option_values_map.get(option_id, {})
                group_id = str(option_row.get("id_attribute_group") or "")
                normalized_options.append(
                    {
                        "id": option_id,
                        "group_id": group_id,
                        "group": group_names.get(group_id, ""),
                        "value": self._localized(option_row.get("name")),
                    }
                )
            result.append(
                {
                    "id": combination_id,
                    "reference": str(row.get("reference") or ""),
                    "price_impact": float(
                        self._decimal(row.get("price"), field="Impacto de precio", product_id=product_id)
                    ),
                    "stock_quantity": await self.get_stock(product_id, combination_id),
                    "default": str(row.get("default_on", "0")).lower() in {"1", "true"},
                    "minimal_quantity": int(row.get("minimal_quantity") or 1),
                    "ean13": str(row.get("ean13") or ""),
                    "upc": str(row.get("upc") or ""),
                    "mpn": str(row.get("mpn") or ""),
                    "options": normalized_options,
                }
            )
        return result

    async def get_specific_prices(self, product_id: str) -> List[Dict[str, Any]]:
        rows = await self._get_paginated_rows(
            "specific_prices",
            {
                "filter[id_product]": f"[{product_id}]",
                "display": "[id,id_shop_group,id_shop,id_cart,id_currency,id_country,id_group,id_customer,id_product_attribute,id_specific_price_rule,price,from_quantity,reduction,reduction_tax,reduction_type,from,to]",
                "sort": "[id_ASC]",
            },
        )
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": str(row.get("id") or ""),
                    "shop_group_id": str(row.get("id_shop_group") or "0"),
                    "combination_id": str(row.get("id_product_attribute") or "0"),
                    "shop_id": str(row.get("id_shop") or "0"),
                    "cart_id": str(row.get("id_cart") or "0"),
                    "currency_id": str(row.get("id_currency") or "0"),
                    "country_id": str(row.get("id_country") or "0"),
                    "group_id": str(row.get("id_group") or "0"),
                    "customer_id": str(row.get("id_customer") or "0"),
                    "specific_price_rule_id": str(
                        row.get("id_specific_price_rule") or "0"
                    ),
                    "price": float(self._decimal(row.get("price"), field="Precio específico", product_id=product_id)),
                    "from_quantity": int(row.get("from_quantity") or 1),
                    "reduction": float(self._decimal(row.get("reduction"), field="Reducción", product_id=product_id)),
                    "reduction_type": str(row.get("reduction_type") or ""),
                    "reduction_tax": str(row.get("reduction_tax", "0")).lower() in {"1", "true"},
                    "from": str(row.get("from") or ""),
                    "to": str(row.get("to") or ""),
                }
            )
        return result

    async def get_country_id(self) -> str:
        explicit = str(self.fiscal_country_id or self.country_id or "").strip()
        if explicit:
            self.country_id = explicit
            self.fiscal_country_id = explicit
            return explicit
        iso_code = settings.COUNTRY.strip().upper()
        if not iso_code:
            raise PrestaShopIntegrationError(
                "Falta el contexto de país requerido para resolver impuestos"
            )
        payload = await self._get(
            "countries",
            {
                "filter[iso_code]": f"[{iso_code}]",
                "filter[active]": "[1]",
                "display": "[id,iso_code,active]",
                "limit": "0,2",
            },
        )
        rows = [
            row
            for row in self._rows(payload, "countries")
            if str(row.get("active", "1")).lower() in {"1", "true"}
        ]
        if len(rows) != 1 or not str(rows[0].get("id") or "").strip():
            raise PrestaShopIntegrationError(
                f"No se pudo resolver un país PrestaShop único para {iso_code}"
            )
        resolved = str(rows[0]["id"]).strip()
        self.country_id = resolved
        self.fiscal_country_id = resolved
        return resolved

    async def get_currency_id(self) -> str:
        explicit = str(self.currency_id or "").strip()
        if explicit:
            return explicit
        iso_code = settings.CURRENCY.strip().upper()
        if not iso_code:
            raise PrestaShopIntegrationError(
                "Falta el contexto de moneda requerido para calcular precios"
            )
        payload = await self._get(
            "currencies",
            {
                "filter[iso_code]": f"[{iso_code}]",
                "filter[active]": "[1]",
                "display": "[id,iso_code,active]",
                "limit": "0,2",
            },
        )
        rows = [
            row
            for row in self._rows(payload, "currencies")
            if str(row.get("active", "1")).lower() in {"1", "true"}
        ]
        if len(rows) != 1 or not str(rows[0].get("id") or "").strip():
            raise PrestaShopIntegrationError(
                f"No se pudo resolver una moneda PrestaShop única para {iso_code}"
            )
        self.currency_id = str(rows[0]["id"]).strip()
        return self.currency_id

    async def get_tax_rate(self, tax_rules_group_id: str) -> Decimal:
        group_id = str(tax_rules_group_id or "0").strip()
        if group_id in {"", "0"}:
            return Decimal("0")
        country_id = await self.get_country_id()
        cache_key = (group_id, country_id)
        if cache_key in self._tax_rate_cache:
            return self._tax_rate_cache[cache_key]

        rule_payload = await self._get(
            "tax_rules",
            {
                "filter[id_tax_rules_group]": f"[{group_id}]",
                "filter[id_country]": f"[{country_id}]",
                "display": (
                    "[id,id_tax_rules_group,id_state,id_country,zipcode_from,"
                    "zipcode_to,id_tax,behavior,description]"
                ),
                "limit": "0,100",
            },
        )
        rules = [
            row
            for row in self._rows(rule_payload, "tax_rules")
            if str(row.get("id_state") or "0") in {"", "0"}
            and str(row.get("zipcode_from") or "0") in {"", "0"}
            and str(row.get("zipcode_to") or "0") in {"", "0"}
        ]
        if len(rules) != 1:
            raise PrestaShopIntegrationError(
                "Las reglas fiscales son inexistentes o ambiguas para el país configurado"
            )
        tax_id = str(rules[0].get("id_tax") or "").strip()
        if not tax_id:
            raise PrestaShopIntegrationError("La regla fiscal no referencia un impuesto")

        tax_payload = await self._get(
            "taxes",
            {
                "filter[id]": f"[{tax_id}]",
                "display": "[id,rate,active,deleted]",
                "limit": "0,2",
            },
        )
        taxes = [
            row
            for row in self._rows(tax_payload, "taxes")
            if str(row.get("active", "1")).lower() in {"1", "true"}
            and str(row.get("deleted", "0")).lower() in {"0", "false", ""}
        ]
        if len(taxes) != 1:
            raise PrestaShopIntegrationError("El impuesto de la regla no está activo o es ambiguo")
        rate_percent = self._decimal(
            taxes[0].get("rate"),
            field="Tipo impositivo",
            product_id=f"tax-rule-group-{group_id}",
        )
        if rate_percent < 0 or rate_percent > 100:
            raise PrestaShopIntegrationError("El tipo impositivo está fuera de rango")
        rate = rate_percent / Decimal("100")
        self._tax_rate_cache[cache_key] = rate
        return rate

    async def get_category_name(self, category_id: str) -> str:
        if not category_id:
            return ""
        try:
            payload = await self._get(
                "categories",
                {"filter[id]": f"[{category_id}]", "display": "[id,name]", "limit": "0,1"},
            )
        except PrestaShopIntegrationError:
            return ""
        rows = self._rows(payload, "categories")
        return self._localized(rows[0].get("name")) if rows else ""

    async def get_stock(self, product_id: str, combination_id: Optional[str] = None) -> int:
        params: Dict[str, Any] = {
            "filter[id_product]": f"[{product_id}]",
            "display": "[id_product,id_product_attribute,quantity]",
            "limit": "0,1000",
        }
        if combination_id:
            params["filter[id_product_attribute]"] = f"[{combination_id}]"
        payload = await self._get("stock_availables", params)
        rows = self._rows(payload, "stock_availables")
        if self.shop_id:
            rows = [
                row
                for row in rows
                if str(row.get("id_shop") or self.shop_id) == str(self.shop_id)
            ]
        if not combination_id:
            variant_rows = [
                row for row in rows if str(row.get("id_product_attribute") or "0") != "0"
            ]
            if variant_rows:
                rows = variant_rows
        try:
            return sum(int(row.get("quantity") or 0) for row in rows)
        except (TypeError, ValueError) as exc:
            raise PrestaShopIntegrationError(f"Stock inválido para el producto {product_id}") from exc

    @staticmethod
    def _localized(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            for item in value:
                if isinstance(item, dict) and item.get("value"):
                    return str(item["value"])
        if isinstance(value, dict):
            if value.get("value"):
                return str(value["value"])
            languages = value.get("language")
            if isinstance(languages, list):
                for item in languages:
                    if isinstance(item, dict) and item.get("value"):
                        return str(item["value"])
            if isinstance(languages, dict) and languages.get("value"):
                return str(languages["value"])
        return ""

    @staticmethod
    def _clean_html_text(value: str) -> str:
        # PrestaShop devuelve habitualmente description_short en HTML. Se
        # conserva el texto sin etiquetas para que el agente no reciba scripts
        # ni marcado arbitrario desde el catálogo.
        if not value:
            return ""
        import re
        from html import unescape

        without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
        without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
        return " ".join(unescape(without_tags).split())
