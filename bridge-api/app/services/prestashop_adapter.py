from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.config import settings


class PrestaShopIntegrationError(RuntimeError):
    pass


class PrestaShopAdapter:
    """Adaptador de solo lectura para PrestaShop Webservice.

    PrestaShop conserva la autoridad sobre catálogo, combinaciones, precio y
    existencias. El Bridge mantiene únicamente una caché local de lectura para
    búsqueda, trazabilidad y recomendaciones. Ningún método escribe en la
    tienda.
    """

    def __init__(self) -> None:
        self.base_url = settings.PRESTASHOP_BASE_URL.rstrip("/")
        self.api_key = settings.PRESTASHOP_API_KEY
        self.shop_id = settings.PRESTASHOP_SHOP_ID

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _get(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured():
            raise PrestaShopIntegrationError("PrestaShop no está configurado")
        request_params = {**params, "output_format": "JSON"}
        if self.shop_id:
            request_params["id_shop"] = self.shop_id
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                auth=(self.api_key, ""),
                follow_redirects=False,
                headers={"Accept": "application/json"},
            ) as client:
                response = await client.get(f"{self.base_url}/api/{resource}", params=request_params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise PrestaShopIntegrationError("PrestaShop devolvió un formato inesperado")
                return payload
        except PrestaShopIntegrationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise PrestaShopIntegrationError(f"Error de PrestaShop: {exc}") from exc

    @staticmethod
    def _rows(payload: Dict[str, Any], resource: str) -> List[Dict[str, Any]]:
        rows = payload.get(resource) or []
        if isinstance(rows, dict):
            rows = [rows]
        return [row for row in rows if isinstance(row, dict)]

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
                    "display": "[id,reference,name,description_short,price,id_category_default,active,manufacturer_name,available_for_order,show_price]",
                    "filter[name]": f"%{term}%",
                    "filter[active]": "[1]",
                    "limit": f"0,{safe_limit}",
                    "sort": "[name_ASC]",
                },
            )
            for item in self._rows(payload, "products"):
                product_id = str(item.get("id") or "").strip()
                if product_id:
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
                "display": "[id,reference,name,description_short,price,id_category_default,active,manufacturer_name,available_for_order,show_price]",
                "filter[active]": "[1]",
                "limit": f"{max(0, offset)},{safe_limit}",
                "sort": "[id_ASC]",
            },
        )
        return [
            await self._normalize_product(item, include_details=include_details)
            for item in self._rows(payload, "products")
            if str(item.get("id") or "").strip()
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

        return {
            "external_id": product_id,
            "sku": str(item.get("reference") or f"PS-{product_id}").strip(),
            "name": self._localized(item.get("name")) or f"Producto {product_id}",
            "description": self._clean_html_text(self._localized(item.get("description_short"))),
            "base_price": float(base_price),
            "stock_quantity": stock,
            "category": category_name or category_id or "PrestaShop",
            "attributes": {
                "active": str(item.get("active", "1")).lower() in {"1", "true"},
                "available_for_order": str(item.get("available_for_order", "1")).lower() in {"1", "true"},
                "show_price": str(item.get("show_price", "1")).lower() in {"1", "true"},
                "manufacturer": self._localized(item.get("manufacturer_name")),
                "id_category_default": item.get("id_category_default"),
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
        return {
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
            association_rows = associations.get("combinations") or []
            if isinstance(association_rows, dict):
                association_rows = [association_rows]

        params: Dict[str, Any] = {
            "filter[id_product]": f"[{product_id}]",
            "display": "full",
            "limit": "0,500",
            "sort": "[id_ASC]",
        }
        if association_rows:
            ids = [row.get("id") for row in association_rows if isinstance(row, dict)]
            if ids:
                params.pop("filter[id_product]", None)
                params["filter[id]"] = self._filter_ids(ids)

        payload = await self._get("combinations", params)
        rows = self._rows(payload, "combinations")
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
        try:
            payload = await self._get(
                "specific_prices",
                {
                    "filter[id_product]": f"[{product_id}]",
                    "display": "[id,id_shop,id_currency,id_country,id_group,id_customer,id_product_attribute,price,from_quantity,reduction,reduction_tax,reduction_type,from,to]",
                    "limit": "0,500",
                },
            )
        except PrestaShopIntegrationError:
            return []
        result: List[Dict[str, Any]] = []
        for row in self._rows(payload, "specific_prices"):
            result.append(
                {
                    "id": str(row.get("id") or ""),
                    "combination_id": str(row.get("id_product_attribute") or "0"),
                    "shop_id": str(row.get("id_shop") or "0"),
                    "currency_id": str(row.get("id_currency") or "0"),
                    "country_id": str(row.get("id_country") or "0"),
                    "group_id": str(row.get("id_group") or "0"),
                    "customer_id": str(row.get("id_customer") or "0"),
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
        from html import unescape
        import re

        without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
        without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
        return " ".join(unescape(without_tags).split())
