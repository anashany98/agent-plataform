"""Add composite index for keyset pagination of product indexing.

Revision ID: 0010
Revises: 0009

La indexación semántica del catálogo recorre los productos con paginación
keyset sobre ``(name, id)`` (lotes acotados, sin cargar el catálogo en
memoria). Sin índice, cada página exige un scan+sort del rango completo
(~250 ms/página medidos a 100.000 SKUs → 10+ minutos por pase); con este
índice compuesto la travesía es un salto por la rama ordenada del B-tree
(~1-5 ms/página → pase completo en segundos).

Es **aditiva, idempotente y dialect-aware** (mismo patrón que 0006/0009):
- En **PostgreSQL** crea ``ix_product_installation_name_id`` sobre
  ``(installation_id, name, id)``. ``installation_id`` es el prefijo del
  tenant-scoping automático (``with_loader_criteria``) y ``(name, id)`` la
  clave ordenada del keyset; ``id`` garantiza el desempate estable.
- En **SQLite** no hace nada; los tests herméticos no dependen de él.

El downgrade es no-op por la política de downgrades preservadores del
repositorio (0001–0004): el índice se puede eliminar a mano y no toca datos.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_product_installation_name_id"


def _dialect_name() -> str:
    bind = op.get_bind()
    return getattr(bind.dialect, "name", "unknown")


def upgrade() -> None:
    """Crea el índice del keyset sólo en PostgreSQL (donde existe pgvector)."""

    if _dialect_name() != "postgresql":
        return
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {INDEX_NAME}
        ON products (installation_id, name, id)
        """
    )


def downgrade() -> None:
    """No-op por diseño: política de downgrades preservadores (0001-0004)."""
    return
