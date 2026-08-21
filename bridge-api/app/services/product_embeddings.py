"""Búsqueda semántica del catálogo local con embeddings vectoriales.

La migración 0006 creó la tabla ``product_embeddings`` (pgvector) y este
servicio la aprovecha: indexa el texto del catálogo con el mismo proveedor
de embeddings que el RAG de documentos (LM Studio / Ollama / OpenAI) y
responde consultas por similitud coseno. Cuando el catálogo crece a miles
de productos, la búsqueda semántica complementa al buscador léxico
(``pg_trgm``) con recall conceptual: p. ej. "una pantalla para jugar"
encuentra un monitor aunque el nombre no contenga la palabra.

La indexación recorre el catálogo con paginación keyset ``(name, id)`` en
lotes — nunca carga el catálogo completo en memoria — de modo que escala a
100.000+ SKUs con memoria acotada al tamaño del lote. ``index_products``
reindexa solo un subconjunto de ids (p. ej. los recién importados) sin
volver a recorrer el catálogo.

Sin tabla indexada o sin proveedor remoto, ``search`` devuelve ``[]`` y el
chat cae a sus ramas existentes (fallback extractivo / catálogo completo):
la búsqueda semántica es un refuerzo, nunca un punto de fallo.
"""

from typing import Any

from sqlalchemy import and_, func, tuple_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Product, ProductEmbedding
from app.services.deterministic_tools import DeterministicToolsService
from app.services.rag_service import RAGError, RAGService, embed_texts


class ProductEmbeddingService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Texto a indexar
    # ------------------------------------------------------------------
    @staticmethod
    def product_text(product: Product) -> str:
        attributes = product.attributes or {}
        scalar_attributes = [
            f"{key}: {value}"
            for key, value in attributes.items()
            if not isinstance(value, (dict, list))
        ]
        parts = [
            product.name or "",
            f"SKU {product.sku}" if product.sku else "",
            product.category or "",
            product.description or "",
            ". ".join(scalar_attributes),
        ]
        return ". ".join(part.strip() for part in parts if str(part or "").strip())

    # ------------------------------------------------------------------
    # Indexación
    # ------------------------------------------------------------------
    def _require_enabled(self) -> None:
        if ProductEmbedding is None:
            raise RAGError(
                "La búsqueda semántica de productos requiere PostgreSQL "
                "(la tabla product_embeddings no existe en SQLite)"
            )

    def _require_remote_provider(self) -> str:
        self._require_enabled()
        provider = settings.EMBEDDING_PROVIDER.lower()
        if provider == "local_tfidf":
            raise RAGError(
                "La búsqueda semántica de productos requiere un proveedor de embeddings "
                "remoto (ollama / openai / openai_compatible)"
            )
        return provider

    def _summary(self, *, total: int, indexed: int, skipped: int, errors: int) -> dict[str, Any]:
        return {
            "total": total,
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
            "provider": settings.EMBEDDING_PROVIDER.lower(),
            "model": settings.EMBEDDING_MODEL,
            "dimension": settings.EMBEDDING_DIMENSION,
        }

    def indexed_count(self) -> int:
        if ProductEmbedding is None:
            return 0
        return (
            self.db.query(func.count(ProductEmbedding.product_id))
            .filter(ProductEmbedding.installation_id == settings.INSTALLATION_ID)
            .scalar()
            or 0
        )

    def _existing_by_id(self, product_ids: list[str]) -> dict[str, ProductEmbedding]:
        """Embeddings ya persistidos para un conjunto de productos (1 consulta)."""

        if not product_ids:
            return {}
        rows = (
            self.db.query(ProductEmbedding)
            .filter(
                ProductEmbedding.installation_id == settings.INSTALLATION_ID,
                ProductEmbedding.product_id.in_(product_ids),
            )
            .all()
        )
        return {row.product_id: row for row in rows}

    async def _embed_page(
        self,
        products: list[Product],
        *,
        force: bool,
    ) -> tuple[int, int, int]:
        """Embebe y persiste una página de productos.

        Devuelve ``(indexed, skipped, errors)`` para el lote. Cada página se
        confirma por separado: si el proveedor de embeddings cae a mitad, el
        progreso parcial queda persistido y los productos fallidos se
        reportan en ``errors`` sin abortar la indexación completa.
        """

        if not products:
            return 0, 0, 0
        existing_by_id = self._existing_by_id([product.id for product in products])
        pending = [product for product in products if force or product.id not in existing_by_id]
        if not pending:
            return 0, len(products), 0
        try:
            vectors = await embed_texts([self.product_text(product) for product in pending])
        except RAGError:
            return 0, 0, len(pending)
        for product, vector in zip(pending, vectors, strict=True):
            row = existing_by_id.get(product.id)
            if row is None:
                row = ProductEmbedding(
                    installation_id=settings.INSTALLATION_ID,
                    product_id=product.id,
                )
                self.db.add(row)
            row.model_name = settings.EMBEDDING_MODEL
            row.embedding = vector
        self.db.commit()
        return len(pending), 0, 0

    async def index_catalog(self, *, force: bool = False, batch_size: int = 16) -> dict[str, Any]:
        """Indexa (o re-indexa con ``force=True``) el catálogo local no-demo.

        Recorre el catálogo con paginación keyset sobre ``(name, id)`` en
        lotes de ``batch_size``: la memoria se mantiene acotada al lote sin
        importar el tamaño del catálogo. Salta los productos ya indexados
        salvo que ``force=True``.
        """

        self._require_remote_provider()
        if batch_size < 1 or batch_size > 64:
            batch_size = 16

        total = 0
        indexed = 0
        skipped = 0
        errors = 0
        last_name = ""
        last_id = ""
        while True:
            # Comparación por fila (name, id): el planner la traduce a un
            # Index Scan sobre (installation_id, name, id) (~0.2 ms/página a
            # 100k SKUs). La forma expandida `name > x OR (name = x AND id > y)`
            # hace Parallel Seq Scan + sort por página (~80 ms/página), que a
            # 100k convertiría un pase completo en ~10+ minutos.
            rows = (
                self.db.query(Product)
                .filter(
                    DeterministicToolsService._non_demo_product_clause(),
                    tuple_(Product.name, Product.id) > (last_name, last_id),
                )
                .order_by(Product.name.asc(), Product.id.asc())
                .limit(batch_size)
                .all()
            )
            if not rows:
                break
            total += len(rows)
            page_indexed, page_skipped, page_errors = await self._embed_page(rows, force=force)
            indexed += page_indexed
            skipped += page_skipped
            errors += page_errors
            last_name = rows[-1].name
            last_id = rows[-1].id
            # La página ya está persistida: expulsarla mantiene la identity
            # map acotada al lote (memoria O(batch), no O(catálogo)).
            self.db.expunge_all()
            if len(rows) < batch_size:
                break
        return self._summary(total=total, indexed=indexed, skipped=skipped, errors=errors)

    async def index_products(
        self,
        product_ids: list[str],
        *,
        force: bool = False,
        batch_size: int = 16,
    ) -> dict[str, Any]:
        """Indexa solo los productos indicados (reindexado incremental).

        Pensado para indexar los productos recién creados tras una
        importación sin recorrer el catálogo completo. Los ids inexistentes
        o demo se ignoran; devuelve el mismo resumen que ``index_catalog``.
        """

        self._require_remote_provider()
        if batch_size < 1 or batch_size > 64:
            batch_size = 16
        ids = [str(product_id) for product_id in product_ids if str(product_id or "").strip()]
        if not ids:
            return self._summary(total=0, indexed=0, skipped=0, errors=0)

        indexed = 0
        skipped = 0
        errors = 0
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            products = (
                self.db.query(Product)
                .filter(
                    Product.id.in_(chunk),
                    DeterministicToolsService._non_demo_product_clause(),
                )
                .all()
            )
            if not products:
                continue
            by_id = {product.id: product for product in products}
            ordered = [by_id[product_id] for product_id in chunk if product_id in by_id]
            page_indexed, page_skipped, page_errors = await self._embed_page(ordered, force=force)
            indexed += page_indexed
            skipped += page_skipped
            errors += page_errors
            self.db.expunge_all()
        return self._summary(
            total=len(ids),
            indexed=indexed,
            skipped=skipped,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        sources: list[str] | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """Búsqueda semántica sobre el catálogo indexado.

        Devuelve productos disponibles (no-demo, filtro de fuentes opcional
        y disponibilidad comercial) con su score de similitud coseno.
        ``[]`` si no hay nada indexado o la consulta no supera el umbral.
        """

        clean_query = str(query or "").strip()
        if not clean_query or self.indexed_count() == 0:
            return []
        self._require_enabled()

        base = (
            self.db.query(ProductEmbedding, Product)
            .join(
                Product,
                and_(
                    Product.id == ProductEmbedding.product_id,
                    Product.installation_id == ProductEmbedding.installation_id,
                ),
            )
            .filter(ProductEmbedding.installation_id == settings.INSTALLATION_ID)
        )
        if sources:
            normalized_sources = sorted(
                {str(value).strip().lower() for value in sources if str(value or "").strip()}
            )
            if normalized_sources:
                base = base.filter(
                    func.lower(func.trim(Product.source)).in_(normalized_sources)
                )

        query_vector = (await embed_texts([clean_query]))[0]
        dialect = self.db.get_bind().dialect.name
        if dialect == "postgresql" and hasattr(ProductEmbedding.embedding, "cosine_distance"):
            distance = ProductEmbedding.embedding.cosine_distance(query_vector).label("distance")
            rows = (
                base.add_columns(distance)
                .order_by(distance.asc())
                .limit(max(1, min(top_k * 3, 60)))
                .all()
            )
            scored = [
                (max(-1.0, min(1.0, 1.0 - float(dist))), product)
                for _, product, dist in rows
            ]
        else:
            rows = base.all()
            scored = [
                (RAGService._cosine(query_vector, list(map(float, embedding.embedding))), product)
                for embedding, product in rows
            ]

        scored.sort(key=lambda item: item[0], reverse=True)
        threshold = settings.RAG_MIN_SCORE if min_score is None else min_score
        results: list[dict[str, Any]] = []
        for score, product in scored:
            if score < threshold:
                continue
            if not DeterministicToolsService._is_product_commercially_available(product):
                continue
            product_dict = DeterministicToolsService._product_dict(product)
            product_dict["score"] = round(score, 4)
            results.append(product_dict)
            if len(results) >= top_k:
                break
        return results
