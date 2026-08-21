"""Add pg_trgm + normalized-text GIN index for scalable product search.

Revision ID: 0009
Revises: 0008

Esta migración es **aditiva, idempotente y dialect-aware** (mismo patrón
que 0006):

- En **PostgreSQL** habilita ``pg_trgm`` y ``unaccent``, crea una función
  inmutable ``bridge_search_norm(text)`` que normaliza el texto igual que
  el buscador en Python (minúsculas + sin acentos + solo ``[a-z0-9]``) y
  añade un índice GIN trigrama sobre la concatenación normalizada de
  ``name + sku + category + description + attributes``. El índice acelera
  los ``ILIKE '%token%'`` del chat/portal y elimina el límite de 5.000
  candidatos que el buscador en memoria imponía sobre catálogos grandes.
- En **SQLite** la migración no hace nada (no existe ``pg_trgm``); los
  tests hermeticos siguen usando el buscador en memoria.

El downgrade es no-op por la política de downgrades preservadores del
repositorio (0001–0004): la función y el índice se pueden eliminar a mano
si hiciera falta, y no se tocan datos.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dialect_name() -> str:
    bind = op.get_bind()
    return getattr(bind.dialect, "name", "unknown")


def upgrade() -> None:
    """Aplica el índice de búsqueda sólo donde tenga sentido (PostgreSQL)."""

    if _dialect_name() != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bridge_search_norm(value text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
            -- unaccent ANTES del regexp: si se invierte el orden, el
            -- regexp borra los caracteres acentuados en vez de
            -- transliterarlos ("Portátil" -> "port til").
            SELECT lower(
                regexp_replace(
                    public.unaccent('public.unaccent', value),
                    '[^a-zA-Z0-9]+',
                    ' ',
                    'g'
                )
            )
        $$
        """
    )
    # El índice GIN trigrama acelera `ILIKE '%token%'` sobre el texto
    # normalizado (misma semántica que el buscador en memoria: subcadena
    # en nombre/SKU/categoría/descripción/atributos, sin importar acentos).
    # Si el índice ya existía con una definición previa de la función, se
    # reindexa para que los trigramas almacenados reflejen la normalización
    # vigente (CREATE OR REPLACE no actualiza el contenido del índice).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_search_trgm
        ON products
        USING gin (
            bridge_search_norm(
                coalesce(name, '') || ' ' || coalesce(sku, '') || ' ' ||
                coalesce(category, '') || ' ' || coalesce(description, '') ||
                ' ' || coalesce(attributes::text, '')
            ) gin_trgm_ops
        )
        """
    )
    op.execute("REINDEX INDEX ix_products_search_trgm")


def downgrade() -> None:
    """No-op por diseño: política de downgrades preservadores (0001-0004)."""
    return
