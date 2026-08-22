import datetime
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
import uuid
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from app.catalog_policy import TRUSTED_PRODUCTION_CATALOG_SOURCES
from app.config import settings
from app.models.models import (
    Activity,
    ApprovalRequest,
    AuditLog,
    Campaign,
    CampaignRecipient,
    ConversationState,
    Customer,
    EmailTrackingEvent,
    InvoiceDraft,
    LandingPage,
    Lead,
    Opportunity,
    Order,
    PipelineStage,
    Product,
    Quote,
    SEOProject,
    SocialChannel,
    SocialMessage,
    SocialTriage,
    StockReservation,
    WikiPage,
)
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MONEY = Decimal("0.01")


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


class BusinessRuleError(ValueError):
    pass


class InsufficientStockError(BusinessRuleError):
    pass


class DeterministicToolsService:
    _PRESTASHOP_COMMERCE_FLAGS = ("active", "show_price", "available_for_order")

    _SEARCH_STOPWORDS = {
        "para", "con", "una", "uno", "unos", "unas", "que", "del", "las", "los", "por",
        "necesito", "quiero", "busco", "comprar", "producto", "productos", "unidad", "unidades",
        "oficina", "recomienda", "recomendar", "mejor", "tengo", "debe", "ser", "algo",
        # Muletillas/verbos de petición que no describen el producto: "vale"
        # matcheaba "VALES" del talonario (falso positivo observado en vivo),
        # "dame"/"quiero" son ruido de intención, no del catálogo.
        "vale", "dame",
    }

    def __init__(
        self,
        db: Session,
        country: str | None = None,
        currency: str | None = None,
        default_vat_rate: float | None = None,
        invoice_series: str | None = None,
    ):
        self.db = db
        self.country = country or settings.COUNTRY
        self.currency = currency or settings.CURRENCY
        self.default_vat_rate = Decimal(str(default_vat_rate if default_vat_rate is not None else settings.DEFAULT_VAT_RATE))
        self.invoice_series = invoice_series or settings.INVOICE_SERIES
        self.shipping_flat_rate = money(settings.SHIPPING_FLAT_RATE)
        self.free_shipping_threshold = money(settings.FREE_SHIPPING_THRESHOLD)

    @staticmethod
    def _hash_confirmation_token(token: str) -> str:
        return hashlib.sha256(token.strip().upper().encode("utf-8")).hexdigest()

    @staticmethod
    def _confirmation_token_for_quote(quote_id: str) -> str:
        """Derive a recoverable, installation-bound 128-bit confirmation token."""

        secret = settings.AUTH_SECRET.strip()
        if not secret:
            raise BusinessRuleError("No existe una clave para emitir confirmaciones")
        message = f"{settings.INSTALLATION_ID}:quote-confirmation:{quote_id}".encode()
        return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:32].upper()

    @staticmethod
    def _non_demo_product_clause():
        normalized_source = func.lower(func.trim(Product.source))
        return normalized_source.in_(tuple(sorted(TRUSTED_PRODUCTION_CATALOG_SOURCES)))

    @staticmethod
    def _local_product_clause():
        return func.lower(func.trim(Product.source)) == "local"

    @classmethod
    def _is_product_commercially_available(cls, product: Product) -> bool:
        if str(product.source or "").strip().lower() != "prestashop":
            return True
        attributes = product.attributes
        return isinstance(attributes, dict) and all(
            attributes.get(field) is True for field in cls._PRESTASHOP_COMMERCE_FLAGS
        )

    @classmethod
    def _require_product_commercially_available(cls, product: Product) -> None:
        if not cls._is_product_commercially_available(product):
            raise BusinessRuleError(f"Producto {product.id} no encontrado")

    @staticmethod
    def _confirmation_payload_hash(
        *,
        customer_id: str,
        items: list[dict[str, Any]],
        subtotal: Any,
        tax_total: Any,
        shipping_total: Any,
        grand_total: Any,
        currency: str,
    ) -> str:
        canonical = json.dumps(
            {
                "customer_id": customer_id,
                "items": items,
                "subtotal": str(money(subtotal)),
                "tax_total": str(money(tax_total)),
                "shipping_total": str(money(shipping_total)),
                "grand_total": str(money(grand_total)),
                "currency": currency,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_search_text(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def search_products(
        self,
        query: str = "",
        limit: int = 50,
        *,
        include_demo: bool = False,
        source: str | None = None,
        sources: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca productos verificados del catálogo local.

        Args:
            query: Texto libre para matchear nombre/SKU/categoría/attrs.
            limit: Tamaño máximo del resultado (clamped a 1..10_000). El
                cap interno permite que el ``catalog_overview`` del chat
                pueda devolver catálogos completos incluso por encima
                del MVP inicial (300-500 productos).
            include_demo: Si True, incluye productos demo (sólo en tests).
            source: Si se especifica (p. ej. ``"prestashop"``), filtra
                únicamente productos con ese origen. Útil para que las
                respuestas de catálogo en el chat expongan sólo lo
                realmente disponible en la tienda y excluyan productos
                sintéticos locales o importados de pruebas internas.
            sources: Alternativa a ``source`` para que un proveedor de
                catálogo exponga varios orígenes a la vez (p. ej.
                ``LocalCatalogProvider`` sirve ``local``/``import``). Si
                se pasa, filtra ``Product.source IN sources``.
        """
        safe_limit = max(1, min(limit, 10_000))
        product_query = self.db.query(Product)
        if not include_demo:
            product_query = product_query.filter(self._non_demo_product_clause())
        if source:
            normalized_source = func.lower(func.trim(Product.source))
            product_query = product_query.filter(normalized_source == str(source).strip().lower())
        if sources:
            normalized_sources = {
                str(value).strip().lower()
                for value in sources
                if str(value or "").strip()
            }
            if normalized_sources:
                normalized_source = func.lower(func.trim(Product.source))
                product_query = product_query.filter(
                    normalized_source.in_(sorted(normalized_sources))
                )
        if self._is_postgres():
            return self._search_products_postgres(product_query, query, safe_limit)
        return self._search_products_python(product_query, query, safe_limit)

    def _is_postgres(self) -> bool:
        return self.db.get_bind().dialect.name == "postgresql"

    def _search_products_python(
        self,
        product_query,
        query: str,
        safe_limit: int,
    ) -> list[dict[str, Any]]:
        """Buscador en memoria (SQLite / entornos sin pg_trgm).

        Conserva la implementación original: carga hasta 5_000 candidatos
        ordenados por nombre y puntúa en Python. Es la ruta de los tests
        hermeticos y de despliegues sin la extensión PostgreSQL.
        """

        if not query.strip():
            products = product_query.order_by(Product.name.asc()).limit(5_000).all()
            visible_products = [
                product
                for product in products
                if self._is_product_commercially_available(product)
            ]
            return [self._product_dict(product) for product in visible_products[:safe_limit]]

        normalized_query = self._normalize_search_text(query)
        tokens = self._search_tokens(normalized_query)
        if not tokens:
            return []
        candidates = product_query.order_by(Product.name.asc()).limit(5_000).all()
        return self._score_candidates(candidates, tokens, normalized_query, safe_limit)

    def _search_products_postgres(
        self,
        product_query,
        query: str,
        safe_limit: int,
    ) -> list[dict[str, Any]]:
        """Buscador PostgreSQL con índice GIN trigrama (pg_trgm).

        Con catálogos grandes evita dos problemas del buscador en memoria:

        - La consulta vacía filtra la disponibilidad comercial en SQL y
          aplica ``LIMIT safe_limit`` sin cargar 5_000 filas por petición.
        - La búsqueda por tokens usa ``ILIKE '%token%'`` sobre el texto
          normalizado (acelerado por el índice ``ix_products_search_trgm``
          de la migración 0009), de modo que el cap de 5_000 candidatos
          solo se alcanza cuando hay miles de coincidencias reales y no
          se recorre el catálogo entero para puntuar.

        El scoring final (umbral >= 10, orden por relevancia) es idéntico
        al del buscador en memoria: el índice solo acota el conjunto de
        candidatos, no cambia la semántica de los resultados.
        """

        if not query.strip():
            rows = (
                product_query
                .filter(self._availability_clause())
                .order_by(Product.name.asc())
                .limit(safe_limit)
                .all()
            )
            return [self._product_dict(product) for product in rows]

        normalized_query = self._normalize_search_text(query)
        tokens = self._search_tokens(normalized_query)
        if not tokens:
            return []
        # Incluye la forma singular de cada token: "boligrafos" también
        # matchea nombres en singular ("BOLIGRAFO ..."), "negros" → "NEGRO".
        match_forms = self._match_forms(tokens)
        like_clause = or_(
            *[self._search_haystack_expr().ilike(f"%{form}%") for form in sorted(match_forms)]
        )
        candidates = (
            product_query.filter(like_clause).order_by(Product.name.asc()).limit(5_000).all()
        )
        return self._score_candidates(candidates, tokens, normalized_query, safe_limit)

    @staticmethod
    def _singularize(token: str) -> str:
        """Raíz singular de un token español (heurística de búsqueda).

        ``boligrafos`` -> ``boligrafo``, ``negros`` -> ``negro``,
        ``lapices`` -> ``lapic``, ``azules`` -> ``azul``. Como la búsqueda
        es por subcadena, la raíz singular sigue matcheando tanto el
        singular como el plural de los nombres de producto (p. ej.
        ``LAPICES ALPINO...`` contiene ``lapic``). No se aplica si la raíz
        quedaría con menos de 3 caracteres (``mes`` se conserva) para no
        generar ruido tipo ``me``.
        """

        if len(token) <= 4:
            return token
        if token.endswith("es"):
            root = token[:-2]
        elif token.endswith("s"):
            root = token[:-1]
        else:
            return token
        return root if len(root) >= 3 else token

    def _token_matches(self, token: str, text: str) -> bool:
        """True si el token (o su forma singular) está en ``text``."""

        return token in text or self._singularize(token) in text

    @classmethod
    def _match_forms(cls, tokens: list[str]) -> set[str]:
        """Formas de búsqueda por token: el token original y su singular.

        Sin esto, "quiero 50 boligrafos negros" no encontraba el BIC negro
        (el nombre del producto está en singular: ``BOLIGRAFO ... NEGRO``)
        y el buscador devolvía matches por subcadena de "vale" (→ VALES).
        """

        forms: set[str] = set()
        for token in tokens:
            forms.add(token)
            singular = cls._singularize(token)
            if singular != token:
                forms.add(singular)
        return forms

    @staticmethod
    def _search_tokens(normalized_query: str) -> list[str]:
        """Tokens de búsqueda con mínimo de 3 caracteres.

        Los tokens de 2 caracteres ("de", "es", "un", ...) son ruido en
        consultas naturales y matchean SKUs/descripciones por subcadena
        (p. ej. "de" → "demo", "es" → "escritorio", "un" → "unidad"),
        produciendo falsos positivos en preguntas no relacionadas con un
        peso alto de SKU (+12). Solo importan términos significativos de
        3+ caracteres; los tokens cortos restantes se filtran como
        stopwords si aparecen ("una", "para", ...).
        """

        return [
            token
            for token in normalized_query.split()
            if len(token) >= 3 and token not in DeterministicToolsService._SEARCH_STOPWORDS
        ]

    @staticmethod
    def _discarded_short_tokens(normalized_query: str) -> list[str]:
        """Tokens descartados por ser demasiado cortos (<3 caracteres).

        Complementa a ``_search_tokens``: son los términos que el buscador
        léxico ignora (p. ej. ``de``, ``es``, ``un``) y que, si la consulta
        solo los contiene, explican un resultado vacío. Se devuelven
        deduplicados conservando el orden de aparición.
        """

        seen: set[str] = set()
        discarded: list[str] = []
        for token in normalized_query.split():
            if len(token) < 3 and token not in seen:
                seen.add(token)
                discarded.append(token)
        return discarded

    def search_products_by_sku(self, content: str) -> list[dict[str, Any]]:
        """Devuelve el producto exacto cuyo SKU aparece literal en el mensaje.

        Cuando el cliente escribe un SKU concreto (p. ej. ``SKU=PS-40``,
        ``ps-40`` o el código desnudo ``46023``), la búsqueda léxica normal
        no lo encuentra: los dígitos se descartan como tokens cortos y el
        ``ILIKE`` no matchea el SKU exacto. Este método hace match exacto
        contra ``Product.sku`` (case-insensitive) y devuelve ese único
        producto si es comercialmente disponible; en caso contrario ``[]``.
        """

        for match in re.finditer(
            r"(?i)(?:sku\s*[:=]\s*)?\b((?:PS-?\d{2,8})|(?:[A-Z]{2,6}-\d{2,8})|(?:\d{4,6}))\b",
            content or "",
        ):
            sku = match.group(1).strip()
            product = (
                self.db.query(Product)
                .filter(
                    func.lower(func.trim(Product.sku)) == sku.lower(),
                    self._non_demo_product_clause(),
                )
                .first()
            )
            if product:
                try:
                    return [self._product_dict(product)]
                except BusinessRuleError:
                    # SKU localizado pero no disponible comercialmente:
                    # seguimos con el siguiente candidato.
                    continue
        return []

    @classmethod
    def _search_haystack_expr(cls):
        """Texto normalizado de búsqueda (migración 0009 ``bridge_search_norm``).

        Concatena nombre, SKU, categoría, descripción y atributos con la
        misma normalización que ``_normalize_search_text`` en Python
        (minúsculas, sin acentos, solo ``[a-z0-9]``) para que el índice
        GIN trigrama acelere el ``ILIKE``.
        """

        return func.bridge_search_norm(
            sa.text(
                "coalesce(name, '') || ' ' || coalesce(sku, '') || ' ' || "
                "coalesce(category, '') || ' ' || coalesce(description, '') || ' ' || "
                "coalesce(attributes::text, '')"
            )
        )

    @classmethod
    def _availability_clause(cls):
        """Predicado SQL de disponibilidad comercial (equivalente a
        ``_is_product_commercially_available``): todo producto no-PrestaShop
        es visible; los PrestaShop requieren los flags de comercio activos.
        """

        return or_(
            func.lower(func.trim(Product.source)) != "prestashop",
            and_(
                *[
                    Product.attributes.op("->>")(flag) == "true"
                    for flag in cls._PRESTASHOP_COMMERCE_FLAGS
                ]
            ),
        )

    def _score_candidates(
        self,
        candidates: list[Product],
        tokens: list[str],
        normalized_query: str,
        safe_limit: int,
    ) -> list[dict[str, Any]]:
        """Puntuación en memoria de candidatos (compartida por ambos buscadores)."""

        scored: list[tuple[int, str, Product]] = []
        for product in candidates:
            if not self._is_product_commercially_available(product):
                continue
            attributes = json.dumps(product.attributes or {}, ensure_ascii=False, sort_keys=True)
            name = self._normalize_search_text(product.name)
            sku = self._normalize_search_text(product.sku)
            description = self._normalize_search_text(product.description)
            category = self._normalize_search_text(product.category)
            attribute_text = self._normalize_search_text(attributes)
            haystack = " ".join((name, sku, description, category, attribute_text))
            # Cada token cuenta UNA vez matcheando cualquiera de sus formas
            # (singular o plural): "boligrafos" → "boligrafo" encuentra el
            # BIC NEGRO aunque el nombre esté en singular. Un producto cuyo
            # nombre contiene singular Y plural ("BOLIGRAFO ... 2
            # BOLIGRAFOS") no debe puntuar doble: eso hundía el BIC negro
            # frente al RHODIA "PUNTOS NEGROS" (falso positivo observado
            # en vivo).
            matched = [
                token
                for token in tokens
                if self._token_matches(token, haystack)
            ]
            if not matched:
                continue
            score = 0
            for token in matched:
                if self._token_matches(token, name):
                    score += 10
                if self._token_matches(token, sku):
                    score += 12
                if self._token_matches(token, category):
                    score += 7
                if self._token_matches(token, attribute_text):
                    score += 6
                if self._token_matches(token, description):
                    score += 4
            if normalized_query and normalized_query in haystack:
                score += 15
            score += int(20 * len(matched) / len(tokens))
            # Umbral mínimo: descartamos matches con score muy bajo para
            # evitar falsos positivos por sub-cadenas débiles (p. ej.
            # "hola" → "holandesa"). El umbral 10 equivale a 1 match en
            # nombre o sku, o varios matches débiles pero consistentes.
            if score < 10:
                continue
            scored.append((score, name, product))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self._product_dict(product) for _, _, product in scored[:safe_limit]]

    def get_product(self, product_id: str, *, include_demo: bool = False) -> dict[str, Any]:
        query = self.db.query(Product).filter(Product.id == product_id)
        if not include_demo:
            query = query.filter(self._non_demo_product_clause())
        product = query.first()
        if not product:
            raise BusinessRuleError(f"Producto {product_id} no encontrado")
        self._require_product_commercially_available(product)
        return self._product_dict(product)

    @staticmethod
    def _iso_utc(value: Any) -> str | None:
        """Serializa un datetime (naive UTC) como ISO 8601 con sufijo Z."""

        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            if value.tzinfo is not None:
                value = value.astimezone(datetime.UTC).replace(tzinfo=None)
            return value.isoformat(timespec="seconds") + "Z"
        return str(value)

    @classmethod
    def _product_dict(cls, product: Product) -> dict[str, Any]:
        cls._require_product_commercially_available(product)
        return {
            "id": product.id,
            "external_id": product.external_id,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "category": product.category,
            "attributes": product.attributes or {},
            "source": product.source,
            "source_url": product.source_url,
            "unit_price": float(product.base_price),
            "tax_rate": float(product.tax_rate),
            "stock_quantity": int(product.stock_quantity),
            "reserved_stock": int(product.reserved_stock),
            "available_stock": product.available_stock,
            "created_at": cls._iso_utc(product.created_at),
            "updated_at": cls._iso_utc(product.updated_at),
        }

    # Columnas de orden admitidas por ``list_catalog``. El catálogo del
    # portal solo permite ordenar por campos estables y significativos;
    # cualquier otro valor se rechaza con 422 (nunca se inyecta en SQL).
    CATALOG_SORT_COLUMNS = frozenset(
        {"name", "sku", "category", "unit_price", "available_stock", "created_at", "updated_at"}
    )

    def _sort_column(self, sort: str):
        mapping = {
            "unit_price": Product.base_price,
            "available_stock": Product.stock_quantity - Product.reserved_stock,
            "created_at": Product.created_at,
            "updated_at": Product.updated_at,
            "sku": Product.sku,
            "category": Product.category,
            "name": Product.name,
        }
        return mapping[sort]

    def list_catalog(
        self,
        *,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        sort: str = "name",
        order: str = "asc",
        source: str | None = None,
        sources: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Listado paginado del catálogo para el portal operativo.

        Devuelve ``{"items": [...], "total": N, "limit": L, "offset": O}``.
        El conjunto de productos es el mismo que el del chat (orígenes de
        confianza, sin demo y comercialmente disponibles), pero con
        paginación por SQL (LIMIT/OFFSET) para catálogos de decenas de
        miles de filas y orden estable por columna whitelisted.

        Con ``query`` no vacía la búsqueda usa la relevancia del buscador
        léxico (``search_products``) y el parámetro ``sort`` se ignora
        (documentado en la API): la paginación recorre el mismo ranking
        que el chat. Sin query, ``sort``/``order`` controlan el listado
        completo.

        Raises:
            BusinessRuleError: si ``sort`` no está en ``CATALOG_SORT_COLUMNS``
                o ``order`` no es ``asc``/``desc``.
        """

        if sort not in self.CATALOG_SORT_COLUMNS:
            raise BusinessRuleError(f"Orden no permitido: {sort}")
        normalized_order = str(order or "asc").strip().lower()
        if normalized_order not in {"asc", "desc"}:
            raise BusinessRuleError(f"Dirección no permitida: {order}")
        safe_limit = max(1, min(int(limit or 50), 200))
        safe_offset = max(0, int(offset or 0))

        if str(query or "").strip():
            scored = self.search_products(
                query,
                limit=10_000,
                source=source,
                sources=sources,
            )
            return {
                "items": scored[safe_offset : safe_offset + safe_limit],
                "total": len(scored),
                "limit": safe_limit,
                "offset": safe_offset,
            }

        product_query = self.db.query(Product).filter(self._non_demo_product_clause())
        if source:
            normalized_source = func.lower(func.trim(Product.source))
            product_query = product_query.filter(normalized_source == str(source).strip().lower())
        if sources:
            normalized_sources = {
                str(value).strip().lower()
                for value in sources
                if str(value or "").strip()
            }
            if normalized_sources:
                normalized_source = func.lower(func.trim(Product.source))
                product_query = product_query.filter(
                    normalized_source.in_(sorted(normalized_sources))
                )
        column = self._sort_column(sort)
        ordered = (
            product_query.order_by(column.asc() if normalized_order == "asc" else column.desc())
            .order_by(Product.id.asc())
        )

        if self._is_postgres():
            available = ordered.filter(self._availability_clause())
            rows = (
                available.offset(safe_offset)
                .limit(safe_limit)
                .all()
            )
            return {
                "items": [self._product_dict(product) for product in rows],
                "total": available.count(),
                "limit": safe_limit,
                "offset": safe_offset,
            }

        # SQLite (entornos herméticos y catálogos pequeños): el predicado
        # de disponibilidad de PrestaShop usa operadores JSON no portables,
        # así que se filtran en Python antes de paginar, igual que el
        # buscador en memoria.
        visible = [
            product
            for product in ordered.limit(20_000).all()
            if self._is_product_commercially_available(product)
        ]
        return {
            "items": [
                self._product_dict(product) for product in visible[safe_offset : safe_offset + safe_limit]
            ],
            "total": len(visible),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise BusinessRuleError(f"Cliente {customer_id} no encontrado")
        return {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "company": customer.company,
            "pricelist_id": customer.pricelist_id,
            "discount_percentage": customer.discount_percentage,
            "is_tax_exempt": customer.is_tax_exempt,
        }

    def calculate_price(
        self,
        product_id: str,
        qty: int,
        customer_id: str | None = None,
        custom_vat_rate: float | None = None,
        is_tax_exempt: bool = False,
        combination_id: str | None = None,
    ) -> dict[str, Any]:
        if qty <= 0:
            raise BusinessRuleError("La cantidad debe ser mayor que cero")
        product = self.db.query(Product).filter(
            Product.id == product_id,
            self._non_demo_product_clause(),
        ).first()
        if not product:
            raise BusinessRuleError(f"Producto {product_id} no encontrado")
        self._require_product_commercially_available(product)

        customer = None
        discount = Decimal("0")
        if customer_id:
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                raise BusinessRuleError(f"Cliente {customer_id} no encontrado")
            if str(product.source).strip().lower() == "local":
                discount = Decimal(str(customer.discount_percentage))
            is_tax_exempt = is_tax_exempt or customer.is_tax_exempt

        attributes = product.attributes or {}
        unit_price = money(product.base_price)
        combinations = [
            row for row in attributes.get("combinations", []) if isinstance(row, dict)
        ]
        if combination_id is None and combinations:
            configured_default = str(attributes.get("default_combination_id") or "0")
            defaults = [
                row
                for row in combinations
                if str(row.get("id") or "") == configured_default
                or bool(row.get("default"))
            ]
            unique_defaults = {
                str(row.get("id") or ""): row for row in defaults if row.get("id")
            }
            if len(unique_defaults) != 1:
                raise BusinessRuleError(
                    "El producto tiene variantes pero no una combinación predeterminada única"
                )
            combination_id = next(iter(unique_defaults))
        selected_combination: dict[str, Any] | None = None
        if combination_id:
            selected_combination = next(
                (
                    row
                    for row in combinations
                    if str(row.get("id")) == str(combination_id)
                ),
                None,
            )
            if selected_combination is None:
                raise BusinessRuleError(f"Combinación {combination_id} no encontrada")
            minimum_quantity = int(selected_combination.get("minimal_quantity") or 1)
            if qty < minimum_quantity:
                raise BusinessRuleError(
                    f"La combinación {combination_id} requiere al menos {minimum_quantity} unidades"
                )
            unit_price = money(unit_price + Decimal(str(selected_combination.get("price_impact") or 0)))

        product_vat_rate = Decimal(
            str(product.tax_rate if product.tax_rate is not None else self.default_vat_rate)
        )
        if product_vat_rate < 0 or product_vat_rate > 1:
            raise BusinessRuleError("Tipo impositivo de producto fuera de rango")
        vat_rate = (
            Decimal("0")
            if is_tax_exempt
            else Decimal(str(custom_vat_rate))
            if custom_vat_rate is not None
            else product_vat_rate
        )
        if vat_rate < 0 or vat_rate > 1:
            raise BusinessRuleError("Tipo impositivo fuera de rango")

        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        has_prestashop_context = any(
            field in attributes
            for field in ("shop_group_id", "shop_id", "currency_id", "country_id")
        )
        if has_prestashop_context:
            # Local IDs are never assumed to equal PrestaShop IDs. Customer or
            # group rules require a future explicit identity mapping.
            customer_scope = "0"
            group_scope = "0"
            shop_group_scope = str(attributes.get("shop_group_id") or "0")
            shop_scope = str(attributes.get("shop_id") or "0")
            currency_scope = str(attributes.get("currency_id") or "0")
            country_scope = str(attributes.get("country_id") or "0")
        else:
            customer_scope = str(customer.id) if customer else "0"
            group_scope = str(customer.pricelist_id or "0") if customer else "0"
            shop_group_scope = "0"
            shop_scope = "0"
            currency_scope = str(attributes.get("currency_id") or self.currency)
            country_scope = str(attributes.get("country_id") or self.country)
        applicable_specific_prices = []
        for row in attributes.get("specific_prices", []):
            if not isinstance(row, dict):
                continue
            row_combination = str(row.get("combination_id") or "0")
            if row_combination not in {"0", str(combination_id or "0")}:
                continue
            # Cart-scoped prices cannot be authorized without a trusted remote
            # cart identity in the pricing context. Fail closed instead of
            # treating an arbitrary PrestaShop cart as a global rule.
            if str(row.get("cart_id") or "0") != "0":
                continue
            if int(row.get("from_quantity") or 1) > qty:
                continue
            scoped_values = (
                ("shop_group_id", shop_group_scope),
                ("shop_id", shop_scope),
                ("customer_id", customer_scope),
                ("group_id", group_scope),
                ("currency_id", currency_scope),
                ("country_id", country_scope),
            )
            if any(
                str(row.get(field) or "0") not in {"0", actual}
                for field, actual in scoped_values
            ):
                continue
            starts_at = self._parse_specific_price_boundary(row.get("from"), "from")
            ends_at = self._parse_specific_price_boundary(row.get("to"), "to")
            if starts_at and now < starts_at:
                continue
            if ends_at and now > ends_at:
                continue
            applicable_specific_prices.append(row)
        selected_specific_price = self._select_specific_price(
            applicable_specific_prices,
            combination_id=str(combination_id or "0"),
            scopes={
                "customer_id": customer_scope,
                "shop_id": shop_scope,
                "currency_id": currency_scope,
                "country_id": country_scope,
                "group_id": group_scope,
            },
        )
        catalog_unit_price = unit_price
        if selected_specific_price:
            explicit_price = Decimal(str(selected_specific_price.get("price", -1)))
            if explicit_price >= 0:
                unit_price = money(explicit_price)
            reduction = Decimal(str(selected_specific_price.get("reduction") or 0))
            reduction_type = str(selected_specific_price.get("reduction_type") or "").lower()
            if reduction < 0:
                raise BusinessRuleError("La reducción de precio específico no puede ser negativa")
            if reduction_type == "percentage":
                if reduction > 1:
                    raise BusinessRuleError("La reducción porcentual debe estar entre cero y uno")
                unit_price = money(unit_price * (Decimal("1") - reduction))
            elif reduction_type == "amount":
                net_reduction = reduction
                reduction_includes_tax = str(
                    selected_specific_price.get("reduction_tax", "0")
                ).lower() in {"1", "true"}
                if reduction_includes_tax and product_vat_rate:
                    net_reduction = money(reduction / (Decimal("1") + product_vat_rate))
                unit_price = money(max(Decimal("0"), unit_price - net_reduction))
            elif reduction:
                raise BusinessRuleError(f"Tipo de reducción no soportado: {reduction_type}")

        if discount < 0 or discount > 100:
            raise BusinessRuleError("Descuento fuera de rango")

        discounted_unit = money(unit_price * (Decimal("1") - discount / Decimal("100")))
        subtotal = money(discounted_unit * qty)
        vat_amount = money(subtotal * vat_rate)
        shipping = Decimal("0") if subtotal >= self.free_shipping_threshold else self.shipping_flat_rate
        total = money(subtotal + vat_amount + shipping)

        return {
            "product_id": product_id,
            "combination_id": str(combination_id) if combination_id else None,
            "quantity": qty,
            "base_unit_price": float(catalog_unit_price),
            "discount_percentage": float(discount),
            "discounted_unit_price": float(discounted_unit),
            "specific_price_id": str(selected_specific_price.get("id")) if selected_specific_price else None,
            "subtotal": float(subtotal),
            "vat_rate": float(vat_rate),
            "vat_amount": float(vat_amount),
            "is_tax_exempt": bool(is_tax_exempt),
            "currency": self.currency,
            "shipping_cost": float(shipping),
            "grand_total": float(total),
        }

    @staticmethod
    def _parse_specific_price_boundary(value: Any, field: str) -> datetime.datetime | None:
        raw = str(value or "").strip()
        if raw in {"", "0000-00-00", "0000-00-00 00:00:00"}:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BusinessRuleError(f"Fecha {field} inválida en precio específico") from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.UTC).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _specific_price_int(row: dict[str, Any], field: str, default: int = 0) -> int:
        raw = row.get(field)
        if raw in (None, ""):
            return default
        try:
            value = int(str(raw))
        except (TypeError, ValueError) as exc:
            raise BusinessRuleError(
                f"El campo {field} del precio específico no es un entero válido"
            ) from exc
        if value < 0:
            raise BusinessRuleError(
                f"El campo {field} del precio específico no puede ser negativo"
            )
        return value

    def _select_specific_price(
        self,
        rows: list[dict[str, Any]],
        *,
        combination_id: str,
        scopes: dict[str, str],
    ) -> dict[str, Any] | None:
        """Select a safe winner using PrestaShop's authoritative ordering.

        PrestaShop's score order can be customized globally and per product,
        but that priority table is not exposed by the standard Webservice.
        We therefore select only when one candidate's exact scopes dominate
        all others under every possible priority; incomparable candidates fail
        closed instead of silently producing a potentially different price.
        """

        if not rows:
            return None
        candidates = list(rows)

        def retain_extreme(key, *, highest: bool) -> None:
            nonlocal candidates
            values = [key(row) for row in candidates]
            target = max(values) if highest else min(values)
            candidates = [row for row in candidates if key(row) == target]

        # Mirrors SpecificPrice::getSpecificPrice through the keys that precede
        # its configurable score: combination DESC, cart DESC, quantity DESC,
        # generated-rule ID ASC. Only the selected combination or wildcard can
        # reach this point, and cart-scoped rows have already failed closed.
        retain_extreme(
            lambda row: str(row.get("combination_id") or "0") == combination_id,
            highest=True,
        )
        retain_extreme(
            lambda row: self._specific_price_int(row, "cart_id"),
            highest=True,
        )
        retain_extreme(
            lambda row: self._specific_price_int(row, "from_quantity", default=1),
            highest=True,
        )
        retain_extreme(
            lambda row: self._specific_price_int(row, "specific_price_rule_id"),
            highest=False,
        )

        score_fields = (
            "customer_id",
            "shop_id",
            "currency_id",
            "country_id",
            "group_id",
        )

        def exact_scope_set(row: dict[str, Any]) -> frozenset[str]:
            return frozenset(
                field
                for field in score_fields
                if str(row.get(field) or "0") == scopes[field]
            )

        score_sets = {exact_scope_set(row) for row in candidates}
        maximal_score_sets = {
            candidate
            for candidate in score_sets
            if not any(candidate < other for other in score_sets)
        }
        if len(maximal_score_sets) != 1:
            raise BusinessRuleError(
                "La prioridad configurable de precios específicos es ambigua; "
                "se requiere autoridad explícita de PrestaShop"
            )
        winning_score_set = next(iter(maximal_score_sets))
        candidates = [
            row for row in candidates if exact_scope_set(row) == winning_score_set
        ]

        minimum_boundary = datetime.datetime.min
        retain_extreme(
            lambda row: self._parse_specific_price_boundary(row.get("to"), "to")
            or minimum_boundary,
            highest=True,
        )
        retain_extreme(
            lambda row: self._parse_specific_price_boundary(row.get("from"), "from")
            or minimum_boundary,
            highest=True,
        )
        if len(candidates) != 1:
            raise BusinessRuleError(
                "Precios específicos indistinguibles según la precedencia de PrestaShop"
            )
        return candidates[0]

    def check_stock(self, product_id: str, qty: int = 1) -> dict[str, Any]:
        product = self.db.query(Product).filter(
            Product.id == product_id,
            self._non_demo_product_clause(),
        ).first()
        if not product or not self._is_product_commercially_available(product):
            return {"product_id": product_id, "available": False, "stock_quantity": 0, "available_stock": 0}
        if str(product.source).strip().lower() != "local":
            return {
                "product_id": product_id,
                "available": False,
                "stock_quantity": None,
                "reserved_stock": int(product.reserved_stock),
                "available_stock": None,
                "authority": "external_confirmation_required",
            }
        available = product.available_stock
        return {
            "product_id": product_id,
            "available": available >= qty,
            "stock_quantity": int(product.stock_quantity),
            "reserved_stock": int(product.reserved_stock),
            "available_stock": available,
        }

    def reserve_stock(self, product_id: str, qty: int, order_id: str | None = None, commit: bool = True) -> bool:
        if qty <= 0 or not order_id:
            return False
        product = self.db.query(Product).filter(
            Product.id == product_id,
            self._non_demo_product_clause(),
        ).first()
        if not product or str(product.source).strip().lower() != "local":
            # Una proyección sincronizada de un sistema externo no constituye
            # autoridad suficiente para efectuar una reserva comercial.
            return False
        if not self.db.query(Order).filter(Order.id == order_id).first():
            # Las reservas huérfanas violan el ciclo de vida transaccional y
            # fallan además por FK en PostgreSQL; se rechazan antes del efecto.
            return False
        try:
            result = self.db.execute(
                update(Product)
                .where(Product.id == product_id)
                .where(self._local_product_clause())
                .where((Product.stock_quantity - Product.reserved_stock) >= qty)
                .values(reserved_stock=Product.reserved_stock + qty)
            )
            if result.rowcount != 1:
                self.db.rollback()
                return False
            self.db.add(
                StockReservation(
                    id=f"res-{uuid.uuid4().hex[:12]}",
                    order_id=order_id,
                    product_id=product_id,
                    quantity_reserved=qty,
                    status="active",
                )
            )
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            return True
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(StockReservation).filter(
                StockReservation.order_id == order_id,
                StockReservation.product_id == product_id,
            ).first()
            return existing is not None
        except Exception:
            self.db.rollback()
            return False

    def release_stock(self, reservation_id: str, commit: bool = True) -> bool:
        try:
            released_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            claimed = self.db.execute(
                update(StockReservation)
                .where(StockReservation.id == reservation_id)
                .where(StockReservation.status == "active")
                .values(status="released", released_at=released_at)
                .returning(
                    StockReservation.product_id,
                    StockReservation.quantity_reserved,
                )
            ).first()
            if claimed is None:
                reservation = self.db.query(StockReservation).filter(
                    StockReservation.id == reservation_id
                ).first()
                return bool(reservation and reservation.status == "released")

            result = self.db.execute(
                update(Product)
                .where(Product.id == claimed.product_id)
                .where(self._local_product_clause())
                .where(Product.reserved_stock >= claimed.quantity_reserved)
                .values(reserved_stock=Product.reserved_stock - claimed.quantity_reserved)
            )
            if result.rowcount != 1:
                raise BusinessRuleError(
                    f"No se puede liberar la reserva inconsistente {reservation_id}"
                )
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            return True
        except Exception:
            self.db.rollback()
            return False

    def expire_stock_reservations(self, now: datetime.datetime | None = None) -> int:
        effective_now = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        try:
            reservations = self.db.execute(
                update(StockReservation)
                .where(StockReservation.status == "active")
                .where(StockReservation.expires_at <= effective_now)
                .values(status="expired", released_at=effective_now)
                .returning(
                    StockReservation.id,
                    StockReservation.product_id,
                    StockReservation.quantity_reserved,
                )
            ).all()
            for reservation in reservations:
                result = self.db.execute(
                    update(Product)
                    .where(Product.id == reservation.product_id)
                    .where(self._local_product_clause())
                    .where(Product.reserved_stock >= reservation.quantity_reserved)
                    .values(reserved_stock=Product.reserved_stock - reservation.quantity_reserved)
                )
                if result.rowcount != 1:
                    raise BusinessRuleError(
                        f"No se puede expirar la reserva inconsistente {reservation.id}"
                    )
            self.db.commit()
            return len(reservations)
        except Exception:
            self.db.rollback()
            raise

    def cancel_order_stock(self, order_id: str) -> int:
        try:
            released_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            reservations = self.db.execute(
                update(StockReservation)
                .where(StockReservation.order_id == order_id)
                .where(StockReservation.status == "active")
                .values(status="cancelled", released_at=released_at)
                .returning(
                    StockReservation.id,
                    StockReservation.product_id,
                    StockReservation.quantity_reserved,
                )
            ).all()
            for reservation in reservations:
                result = self.db.execute(
                    update(Product)
                    .where(Product.id == reservation.product_id)
                    .where(self._local_product_clause())
                    .where(Product.reserved_stock >= reservation.quantity_reserved)
                    .values(reserved_stock=Product.reserved_stock - reservation.quantity_reserved)
                )
                if result.rowcount != 1:
                    raise BusinessRuleError(
                        f"No se puede cancelar la reserva inconsistente {reservation.id}"
                    )
            self.db.commit()
            return len(reservations)
        except Exception:
            self.db.rollback()
            raise

    def create_quote(
        self,
        customer_id: str,
        items: list[dict[str, Any]],
        custom_vat_rate: float | None = None,
        account_id: str | None = None,
        conversation_id: str | None = None,
        source_message_id: str | None = None,
    ) -> dict[str, Any]:
        if not settings.ENABLE_QUOTES:
            raise BusinessRuleError("Módulo presupuestos deshabilitado")
        if not items:
            raise BusinessRuleError("El presupuesto debe contener al menos una línea")
        if source_message_id:
            existing_quote = self.db.query(Quote).filter(Quote.source_message_id == source_message_id).first()
            if existing_quote:
                confirmation_token = self._confirmation_token_for_quote(existing_quote.id)
                if not secrets.compare_digest(
                    str(existing_quote.confirmation_token),
                    self._hash_confirmation_token(confirmation_token),
                ):
                    raise BusinessRuleError(
                        "El presupuesto existente no tiene un token de confirmación recuperable"
                    )
                return {
                    "quote_id": existing_quote.id,
                    "customer_id": existing_quote.customer_id,
                    "confirmation_token": confirmation_token,
                    "currency": existing_quote.currency,
                    "subtotal": float(existing_quote.subtotal),
                    "tax_total": float(existing_quote.tax_total),
                    "shipping_total": float(existing_quote.shipping_total),
                    "grand_total": float(existing_quote.grand_total),
                    "items": existing_quote.items,
                    "created": False,
                }
        customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise BusinessRuleError("Cliente no encontrado")

        normalized_items: list[dict[str, Any]] = []
        subtotal = Decimal("0")
        tax_total = Decimal("0")
        shipping_total = Decimal("0")
        for item in items:
            product_id = str(item["product_id"])
            qty = int(item["qty"])
            combination_id = str(item["combination_id"]) if item.get("combination_id") else None
            price = self.calculate_price(
                product_id,
                qty,
                customer_id,
                custom_vat_rate,
                combination_id=combination_id,
            )
            combination_id = (
                str(price["combination_id"]) if price.get("combination_id") else None
            )
            product = self.get_product(product_id)
            normalized_items.append(
                {
                    "product_id": product_id,
                    "combination_id": combination_id,
                    "sku": product["sku"],
                    "name": product["name"],
                    "qty": qty,
                    "unit_price": price["discounted_unit_price"],
                    "tax_rate": price["vat_rate"],
                    "line_subtotal": price["subtotal"],
                    "line_tax": price["vat_amount"],
                }
            )
            subtotal += money(price["subtotal"])
            tax_total += money(price["vat_amount"])
        shipping_total = (
            Decimal("0")
            if subtotal >= self.free_shipping_threshold
            else self.shipping_flat_rate
        )

        grand_total = money(subtotal + tax_total + shipping_total)
        quote_id = f"quote-{uuid.uuid4().hex[:12]}"
        confirmation_token = self._confirmation_token_for_quote(quote_id)
        confirmation_payload_hash = self._confirmation_payload_hash(
            customer_id=customer_id,
            items=normalized_items,
            subtotal=subtotal,
            tax_total=tax_total,
            shipping_total=shipping_total,
            grand_total=grand_total,
            currency=self.currency,
        )
        quote = Quote(
            id=quote_id,
            customer_id=customer_id,
            account_id=account_id,
            conversation_id=conversation_id,
            confirmation_token=self._hash_confirmation_token(confirmation_token),
            confirmation_payload_hash=confirmation_payload_hash,
            confirmation_expires_at=(
                datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                + datetime.timedelta(seconds=settings.QUOTE_CONFIRMATION_TTL_SEC)
            ),
            source_message_id=source_message_id,
            items=normalized_items,
            subtotal=money(subtotal),
            tax_total=money(tax_total),
            shipping_total=money(shipping_total),
            grand_total=grand_total,
            currency=self.currency,
            status="draft",
        )
        self.db.add(quote)
        if account_id and conversation_id:
            state = self.db.query(ConversationState).filter(
                ConversationState.account_id == str(account_id),
                ConversationState.conversation_id == str(conversation_id),
            ).first()
            if not state:
                state = ConversationState(account_id=str(account_id), conversation_id=str(conversation_id))
                self.db.add(state)
            state.customer_id = customer_id
            state.active_quote_id = quote.id
            state.state = "awaiting_confirmation"
        self.db.commit()
        return {
            "quote_id": quote.id,
            "customer_id": customer_id,
            "confirmation_token": confirmation_token,
            "currency": self.currency,
            "subtotal": float(quote.subtotal),
            "tax_total": float(quote.tax_total),
            "shipping_total": float(quote.shipping_total),
            "grand_total": float(quote.grand_total),
            "items": normalized_items,
            "created": True,
        }

    def confirm_quote_transactional(
        self,
        quote_id: str,
        business_key: str,
        confirmation_token: str,
        *,
        confirmed_by: str | None = None,
        verified_remote_stock: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if not settings.ENABLE_QUOTES:
            raise BusinessRuleError("Módulo presupuestos deshabilitado")
        if not settings.ENABLE_ORDERS:
            raise BusinessRuleError("Módulo pedidos deshabilitado")
        if not settings.ENABLE_INVOICES:
            raise BusinessRuleError("Módulo facturas deshabilitado")
        try:
            query = self.db.query(Quote).filter(Quote.id == quote_id)
            if self.db.bind and self.db.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            quote = query.first()
            if not quote:
                raise BusinessRuleError("Presupuesto no encontrado")

            supplied_hash = self._hash_confirmation_token(confirmation_token)
            if not secrets.compare_digest(str(quote.confirmation_token), supplied_hash):
                raise BusinessRuleError("Token de confirmación inválido")
            expected_payload_hash = self._confirmation_payload_hash(
                customer_id=quote.customer_id,
                items=quote.items,
                subtotal=quote.subtotal,
                tax_total=quote.tax_total,
                shipping_total=quote.shipping_total,
                grand_total=quote.grand_total,
                currency=quote.currency,
            )
            if not secrets.compare_digest(str(quote.confirmation_payload_hash), expected_payload_hash):
                raise BusinessRuleError("El presupuesto cambió después de solicitar la confirmación")
            existing = self.db.query(Order).filter(Order.quote_id == quote_id).first()
            if existing:
                invoice = self.db.query(InvoiceDraft).filter(InvoiceDraft.order_id == existing.id).first()
                approval = self.db.query(ApprovalRequest).filter(
                    ApprovalRequest.action_type == "issue_invoice",
                    ApprovalRequest.target_key == (invoice.id if invoice else ""),
                ).first()
                return {
                    "created": False,
                    "order_id": existing.id,
                    "invoice_draft_id": invoice.id if invoice else None,
                    "approval_id": approval.id if approval else None,
                    "total_amount": float(existing.grand_total),
                    "currency": existing.currency,
                    "status": existing.status,
                }
            now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            if quote.confirmation_expires_at and now > quote.confirmation_expires_at:
                if quote.status == "draft":
                    quote.status = "expired"
                    self.db.commit()
                raise BusinessRuleError("El token de confirmación ha caducado")
            if quote.status != "draft":
                raise BusinessRuleError(f"El presupuesto no puede confirmarse desde el estado {quote.status}")
            if any(item.get("combination_id") for item in quote.items):
                raise BusinessRuleError(
                    "La confirmación de variantes requiere una autoridad de stock por combinación"
                )

            order = Order(
                id=f"ord-{uuid.uuid4().hex[:12]}",
                customer_id=quote.customer_id,
                quote_id=quote.id,
                idempotency_key=business_key,
                items=quote.items,
                subtotal=quote.subtotal,
                tax_total=quote.tax_total,
                shipping_total=quote.shipping_total,
                grand_total=quote.grand_total,
                currency=quote.currency,
                status="confirmed",
            )
            self.db.add(order)
            self.db.flush()

            for item in quote.items:
                product_id = str(item["product_id"])
                qty = int(item["qty"])
                product = self.db.query(Product).filter(Product.id == product_id).first()
                if product and str(product.source).strip().lower() != "local":
                    # P0-003 (opción C): autoridad de stock externa
                    # (PrestaShop). La confirmación solo procede con
                    # verificación en vivo del stock remoto por el llamador;
                    # sin ella (fail-closed) el pedido se rechaza con 409.
                    verified_qty = (verified_remote_stock or {}).get(product_id)
                    if verified_qty is None or int(verified_qty) < qty:
                        raise InsufficientStockError(
                            f"Stock remoto no verificado o insuficiente para {product_id}"
                        )
                    # Stock remoto verificado en vivo contra la tienda: no
                    # hay stock local que reservar para este item.
                    continue
                result = self.db.execute(
                    update(Product)
                    .where(Product.id == product_id)
                    .where(self._local_product_clause())
                    .where((Product.stock_quantity - Product.reserved_stock) >= qty)
                    .values(reserved_stock=Product.reserved_stock + qty)
                )
                if result.rowcount != 1:
                    raise InsufficientStockError(f"Stock insuficiente para {product_id}")
                self.db.add(
                    StockReservation(
                        id=f"res-{uuid.uuid4().hex[:12]}",
                        order_id=order.id,
                        product_id=product_id,
                        quantity_reserved=qty,
                        status="active",
                    )
                )

            invoice = InvoiceDraft(
                id=f"inv-{uuid.uuid4().hex[:12]}",
                invoice_number=f"{self.invoice_series}{uuid.uuid4().hex[:8].upper()}",
                order_id=order.id,
                customer_id=order.customer_id,
                items=order.items,
                total_amount=order.grand_total,
                tax_amount=order.tax_total,
                currency=order.currency,
                status="pending_approval" if settings.PILOT_MODE else "draft",
            )
            self.db.add(invoice)
            self.db.flush()

            approval = ApprovalRequest(
                id=f"appr-{uuid.uuid4().hex[:12]}",
                action_type="issue_invoice",
                target_key=invoice.id,
                payload={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "order_id": order.id,
                    "amount": float(invoice.total_amount),
                    "currency": invoice.currency,
                },
                requested_by="sales_agent",
                status="pending",
            )
            self.db.add(approval)

            quote.status = "confirmed"
            quote.confirmed_at = now
            quote.confirmation_consumed_at = now
            quote.confirmed_by = (confirmed_by or "unknown")[:255]
            if quote.account_id and quote.conversation_id:
                state = self.db.query(ConversationState).filter(
                    ConversationState.account_id == quote.account_id,
                    ConversationState.conversation_id == quote.conversation_id,
                ).first()
                if state:
                    state.order_id = order.id
                    state.state = "pending_approval"
            self.db.add(
                AuditLog(
                    correlation_id=business_key,
                    agent_id="commerce_confirmation",
                    event_type="quote_confirmed",
                    provider="internal",
                    model_name="deterministic",
                    status="success",
                    details={
                        "quote_id": quote.id,
                        "order_id": order.id,
                        "payload_hash": quote.confirmation_payload_hash,
                        "actor_sha256": hashlib.sha256(quote.confirmed_by.encode("utf-8")).hexdigest(),
                    },
                )
            )
            self.db.commit()
            return {
                "created": True,
                "order_id": order.id,
                "invoice_draft_id": invoice.id,
                "approval_id": approval.id,
                "total_amount": float(order.grand_total),
                "currency": order.currency,
                "status": order.status,
            }
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(Order).filter(Order.quote_id == quote_id).first()
            if existing:
                invoice = self.db.query(InvoiceDraft).filter(InvoiceDraft.order_id == existing.id).first()
                approval = self.db.query(ApprovalRequest).filter(
                    ApprovalRequest.action_type == "issue_invoice",
                    ApprovalRequest.target_key == (invoice.id if invoice else ""),
                ).first()
                return {
                    "created": False,
                    "order_id": existing.id,
                    "invoice_draft_id": invoice.id if invoice else None,
                    "approval_id": approval.id if approval else None,
                    "total_amount": float(existing.grand_total),
                    "currency": existing.currency,
                    "status": existing.status,
                }
            raise
        except Exception:
            self.db.rollback()
            raise

    def create_order(
        self,
        customer_id: str,
        quote_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        if not settings.ENABLE_ORDERS:
            raise BusinessRuleError("Módulo pedidos deshabilitado")
        if not quote_id or not confirmation_token:
            raise BusinessRuleError("quote_id y confirmation_token son obligatorios")
        quote = self.db.query(Quote).filter(Quote.id == quote_id, Quote.customer_id == customer_id).first()
        if not quote:
            raise BusinessRuleError("Presupuesto no encontrado para el cliente indicado")
        return self.confirm_quote_transactional(
            quote_id,
            f"quote-confirm:{quote_id}",
            confirmation_token,
            confirmed_by=f"customer:{customer_id}",
        )

    def create_invoice_draft(self, order_id: str) -> dict[str, Any]:
        if not settings.ENABLE_INVOICES:
            raise BusinessRuleError("Módulo facturas deshabilitado")
        existing = self.db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).first()
        if existing:
            return {
                "invoice_draft_id": existing.id,
                "invoice_number": existing.invoice_number,
                "order_id": order_id,
                "amount": float(existing.total_amount),
                "currency": existing.currency,
                "status": existing.status,
            }
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise BusinessRuleError("Pedido no encontrado")
        invoice = InvoiceDraft(
            id=f"inv-{uuid.uuid4().hex[:12]}",
            invoice_number=f"{self.invoice_series}{uuid.uuid4().hex[:8].upper()}",
            order_id=order.id,
            customer_id=order.customer_id,
            items=order.items,
            total_amount=order.grand_total,
            tax_amount=order.tax_total,
            currency=order.currency,
            status="draft",
        )
        self.db.add(invoice)
        self.db.commit()
        return {
            "invoice_draft_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "order_id": order_id,
            "amount": float(invoice.total_amount),
            "currency": invoice.currency,
            "status": invoice.status,
        }

    def submit_invoice_for_approval(
        self,
        invoice_draft_id: str,
        *,
        requested_by: str = "sales_agent",
        commit: bool = True,
    ) -> dict[str, Any]:
        if not settings.ENABLE_INVOICES:
            raise BusinessRuleError("Módulo facturas deshabilitado")
        invoice = self.db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_draft_id).first()
        if not invoice:
            raise BusinessRuleError("Borrador de factura no encontrado")
        if invoice.status == "approved":
            raise BusinessRuleError("La factura ya fue aprobada")
        existing = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.action_type == "issue_invoice",
            ApprovalRequest.target_key == invoice_draft_id,
        ).first()
        if existing:
            if existing.status == "pending":
                return {
                    "approval_id": existing.id,
                    "status": existing.status,
                    "invoice_draft_id": invoice_draft_id,
                }
            if existing.status == "approved":
                raise BusinessRuleError("La factura ya fue aprobada")
            # La unicidad por (action_type, target_key) impide insertar otra
            # fila. Reutilizamos la solicitud decidida y limpiamos toda la
            # decisión previa para permitir una re-sumisión explícita.
            existing.payload = {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": float(invoice.total_amount),
                "currency": invoice.currency,
            }
            existing.requested_by = requested_by
            existing.status = "pending"
            existing.reviewed_at = None
            existing.reviewed_by = None
            existing.rejection_reason = None
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            return {
                "approval_id": existing.id,
                "status": existing.status,
                "invoice_draft_id": invoice_draft_id,
            }
        approval = ApprovalRequest(
            id=f"appr-{uuid.uuid4().hex[:12]}",
            action_type="issue_invoice",
            target_key=invoice_draft_id,
            payload={
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": float(invoice.total_amount),
                "currency": invoice.currency,
            },
            requested_by=requested_by,
            status="pending",
        )
        self.db.add(approval)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return {"approval_id": approval.id, "status": approval.status, "invoice_draft_id": invoice_draft_id}

    # ------------------------------------------------------------------
    # Herramientas read-only por módulo (T-057, agentes especializados).
    # Todas son deterministas, sin LLM/red y SIN mutación: un agente de
    # un módulo lee su dominio para preparar acciones que, si mutan,
    # pasan por aprobación humana (deny-by-default del tool_policy).
    # ------------------------------------------------------------------

    def list_leads(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Lectura del CRM (agente crm_agent): leads con estado y fuente."""

        query = self.db.query(Lead)
        if status:
            query = query.filter(Lead.status == str(status).strip())
        safe_limit = max(1, min(int(limit or 50), 200))
        rows = (
            query.order_by(Lead.created_at.desc(), Lead.id.asc())
            .limit(safe_limit)
            .all()
        )
        items = []
        for lead in rows:
            open_opps = (
                self.db.query(Opportunity.id)
                .filter(
                    Opportunity.lead_id == lead.id,
                    Opportunity.status == "open",
                )
                .count()
            )
            items.append(
                {
                    "id": lead.id,
                    "first_name": lead.first_name,
                    "email": lead.email,
                    "company_name": lead.company_name,
                    "source": lead.source,
                    "status": lead.status,
                    "assigned_to": lead.assigned_to,
                    "open_opportunities": int(open_opps),
                    "created_at": (
                        lead.created_at.isoformat() if lead.created_at else None
                    ),
                }
            )
        return {"items": items, "total": len(items)}

    def list_activities(
        self,
        *,
        lead_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Lectura de actividades (agente crm_agent): tareas y su estado."""

        query = self.db.query(Activity)
        if lead_id:
            query = query.filter(Activity.lead_id == str(lead_id).strip())
        if status:
            query = query.filter(Activity.status == str(status).strip())
        safe_limit = max(1, min(int(limit or 50), 200))
        rows = (
            query.order_by(Activity.due_at.is_(None), Activity.due_at.asc())
            .limit(safe_limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "lead_id": row.lead_id,
                    "title": row.title,
                    "kind": row.kind,
                    "status": row.status,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                }
                for row in rows
            ],
            "total": len(rows),
        }

    def get_pipeline_report(self) -> dict[str, Any]:
        """Funnel del pipeline (agente crm_agent): por etapa + weighted."""

        stages = (
            self.db.query(PipelineStage)
            .order_by(PipelineStage.position.asc(), PipelineStage.id.asc())
            .all()
        )
        stage_names = {stage.key: stage.name for stage in stages}
        opportunities = self.db.query(Opportunity).all()
        by_stage: dict[str, dict[str, Any]] = {}
        open_value = Decimal("0")
        weighted = Decimal("0")
        for opportunity in opportunities:
            key = str(opportunity.stage or "")
            bucket = by_stage.setdefault(
                key,
                {"name": stage_names.get(key, key), "count": 0, "value": 0.0},
            )
            bucket["count"] += 1
            bucket["value"] += float(opportunity.monetary_value or 0)
            if opportunity.status == "open":
                open_value += Decimal(str(opportunity.monetary_value or 0))
                probability = float(opportunity.probability or 0)
                weighted += Decimal(str(opportunity.monetary_value or 0)) * Decimal(str(probability))
        return {
            "by_stage": [by_stage[key] for key in sorted(by_stage)],
            "open_value": float(open_value),
            "weighted_pipeline_value": float(weighted),
        }

    def list_social_inbox(
        self,
        *,
        status: str | None = None,
        intent: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Inbox social (agente social_agent): mensajes con su triaje."""

        query = self.db.query(SocialMessage)
        if status:
            query = query.filter(SocialMessage.status == str(status).strip())
        if intent:
            query = query.join(
                SocialTriage, SocialTriage.message_id == SocialMessage.id
            ).filter(SocialTriage.intent == str(intent).strip())
        safe_limit = max(1, min(int(limit or 50), 200))
        rows = (
            query.order_by(SocialMessage.created_at.desc(), SocialMessage.id.desc())
            .limit(safe_limit)
            .all()
        )
        triages = {
            triage.message_id: triage
            for triage in self.db.query(SocialTriage)
            .filter(SocialTriage.message_id.in_([row.id for row in rows]))
            .all()
        }
        items = []
        for row in rows:
            triage = triages.get(row.id)
            items.append(
                {
                    "id": row.id,
                    "channel_id": row.channel_id,
                    "sender_name": row.sender_name,
                    "sender_handle": row.sender_handle,
                    "body": (row.body or "")[:300],
                    "status": row.status,
                    "lead_id": row.lead_id,
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                    "triage": (
                        {
                            "intent": triage.intent,
                            "score_social": triage.score_social,
                            "urgency": triage.urgency,
                            "language": triage.language,
                            "summary": triage.summary,
                        }
                        if triage is not None
                        else None
                    ),
                }
            )
        return {"items": items, "total": len(items)}

    def get_social_stats(self) -> dict[str, Any]:
        """Resumen del inbox social (agente social_agent)."""

        by_intent = {
            row[0]: row[1]
            for row in self.db.query(SocialTriage.intent, func.count(SocialTriage.id))
            .group_by(SocialTriage.intent)
            .all()
        }
        avg_score = (
            self.db.query(func.avg(SocialTriage.score_social)).scalar() or 0
        )
        pending = (
            self.db.query(SocialMessage.id)
            .filter(SocialMessage.status == "pending_triage")
            .count()
        )
        return {
            "by_intent": by_intent,
            "pending_triage": int(pending),
            "avg_score_social": round(float(avg_score), 2),
        }

    # ---------------------------------------------------------------------
    # Mejoras de agentes (SEO / wiki / landing / social SLA): herramientas
    # read-only deterministas. El ORM aplica el filtrado por installation_id
    # (do_orm_execute), así que cada consulta queda dentro del tenant.
    # ---------------------------------------------------------------------

    def search_wiki(
        self,
        *,
        query: str | None = None,
        status: str | None = "published",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Busca páginas de la wiki (agente content_agent)."""

        safe_limit = max(1, min(int(limit or 20), 100))
        db_query = self.db.query(WikiPage)
        normalized_status = (status or "").strip()
        if normalized_status:
            db_query = db_query.filter(WikiPage.status == normalized_status)
        needle = (query or "").strip()
        if needle:
            like = f"%{needle.lower()}%"
            db_query = db_query.filter(
                or_(
                    func.lower(WikiPage.title).like(like),
                    func.lower(WikiPage.content).like(like),
                )
            )
        rows = (
            db_query.order_by(WikiPage.updated_at.desc(), WikiPage.id.asc())
            .limit(safe_limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "slug": row.slug,
                    "title": row.title,
                    "status": row.status,
                    "version": row.version,
                    "updated_at": (
                        row.updated_at.isoformat() if row.updated_at else None
                    ),
                }
                for row in rows
            ],
            "total": len(rows),
        }

    def get_seo_overview(self) -> dict[str, Any]:
        """Panorama de contenido/SEO: proyectos SEO, landings y wiki por estado."""

        def _counts(model: Any, field: Any) -> dict[str, int]:
            rows = self.db.query(field, func.count(model.id)).group_by(field).all()
            return {str(status): int(count) for status, count in rows}

        return {
            "seo_projects_by_status": _counts(SEOProject, SEOProject.status),
            "landing_pages_by_status": _counts(LandingPage, LandingPage.status),
            "wiki_pages_by_status": _counts(WikiPage, WikiPage.status),
        }

    def list_landing_pages(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Landings (agente content_agent): listado con estado de aprobación."""

        safe_limit = max(1, min(int(limit or 50), 200))
        query = self.db.query(LandingPage)
        normalized_status = (status or "").strip()
        if normalized_status:
            query = query.filter(LandingPage.status == normalized_status)
        rows = (
            query.order_by(LandingPage.updated_at.desc(), LandingPage.id.asc())
            .limit(safe_limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "slug": row.slug,
                    "title": row.title,
                    "status": row.status,
                    "version": row.version,
                    "approved_at": (
                        row.approved_at.isoformat() if row.approved_at else None
                    ),
                }
                for row in rows
            ],
            "total": len(rows),
        }

    def list_social_sla_breaches(
        self,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Mensajes sociales que superaron su SLA de primera respuesta.

        Regla idéntica a la del pipeline de escucha: queja 15 min,
        WhatsApp 30 min, resto 240 min desde la creación del mensaje y
        mientras siga sin respuesta (``new``/``in_process``).
        """

        from app.installation_context import get_current_installation_id

        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        pending_statuses = ("new", "in_process")
        triages = {
            triage.message_id: triage
            for triage in self.db.query(SocialTriage).all()
        }
        channels = {
            channel.id: channel
            for channel in self.db.query(SocialChannel).all()
        }
        breaches: list[dict[str, Any]] = []
        safe_limit = max(1, min(int(limit or 50), 200))
        rows = (
            self.db.query(SocialMessage)
            .filter(SocialMessage.status.in_(pending_statuses))
            .order_by(SocialMessage.created_at.asc(), SocialMessage.id.asc())
            .limit(500)
            .all()
        )
        for row in rows:
            created = row.created_at
            if created is None:
                continue
            channel = channels.get(row.channel_id)
            triage = triages.get(row.id)
            intent = triage.intent if triage is not None else "consulta"
            if intent == "queja":
                sla_minutes = 15
            elif channel is not None and channel.channel == "whatsapp":
                sla_minutes = 30
            else:
                sla_minutes = 240
            due_at = created + datetime.timedelta(minutes=sla_minutes)
            if now > due_at:
                overdue_minutes = int((now - due_at).total_seconds() // 60)
                breaches.append(
                    {
                        "id": row.id,
                        "channel_id": row.channel_id,
                        "channel": channel.channel if channel is not None else None,
                        "intent": intent,
                        "sender_handle": row.sender_handle,
                        "lead_id": row.lead_id,
                        "created_at": created.isoformat(),
                        "sla_minutes": sla_minutes,
                        "overdue_minutes": overdue_minutes,
                    }
                )
                if len(breaches) >= safe_limit:
                    break
        return {"installation_id": get_current_installation_id(), "items": breaches, "total": len(breaches)}


    def list_campaigns(
        self,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Campañas (agente marketing_agent): listado con stats de envío."""

        safe_limit = max(1, min(int(limit or 50), 200))
        rows = (
            self.db.query(Campaign)
            .order_by(Campaign.created_at.desc(), Campaign.id.asc())
            .limit(safe_limit)
            .all()
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "template_name": row.template_name,
                    "status": row.status,
                    "sent_at": row.sent_at.isoformat() if row.sent_at else None,
                }
                for row in rows
            ],
            "total": len(rows),
        }

    def get_campaign_stats(self, campaign_id: str) -> dict[str, Any]:
        """Estadísticas de una campaña (agente marketing_agent)."""

        campaign = (
            self.db.query(Campaign).filter(Campaign.id == str(campaign_id).strip()).first()
        )
        if campaign is None:
            raise BusinessRuleError(f"Campaña {campaign_id} no encontrada")
        recipients = (
            self.db.query(CampaignRecipient)
            .filter(CampaignRecipient.campaign_id == campaign.id)
            .all()
        )
        by_status: dict[str, int] = {}
        for recipient in recipients:
            by_status[str(recipient.status or "pending")] = (
                by_status.get(str(recipient.status or "pending"), 0) + 1
            )
        tokens = [recipient.tracking_token for recipient in recipients if recipient.tracking_token]
        opened = 0
        clicked = 0
        if tokens:
            events = (
                self.db.query(EmailTrackingEvent)
                .filter(EmailTrackingEvent.token.in_(tokens))
                .all()
            )
            for event in events:
                if event.event_type == "open":
                    opened += 1
                elif event.event_type == "click":
                    clicked += 1
        return {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "status": campaign.status,
            "recipients": len(recipients),
            "by_status": by_status,
            "opened": opened,
            "clicked": clicked,
        }
