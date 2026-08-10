"""Add the ``product_embeddings`` table with pgvector for semantic search.

Revision ID: 0006
Revises: 0005

Esta migración es **aditiva, idempotente y dialect-aware**:

- En **PostgreSQL** crea la tabla ``product_embeddings`` con una columna
  vector de dimensión ``EMBEDDING_DIMENSION`` (768 por defecto,
  ``nomic-embed-text``) usando ``vector(768)``, índice ANN opcional y FKs
  compuestas ``(installation_id, product_id)`` que respetan el aislamiento
  por instalación. Requiere la extensión ``vector`` (la imagen
  ``pgvector/pgvector:pg15`` ya la trae).
- En **SQLite** la migración se aborta de forma controlada: ``vector`` no
  existe, no se crea la tabla y se documenta el motivo. Los tests del
  corpus de hermético usan SQLite, así que esto evita falsos fallos en
  migraciones mientras deja PostgreSQL completamente funcional.

El downgrade preserva la tabla por la política de downgrades
preservadores del repositorio (0001–0004). La política de backup
(``SCHEMA_VERSION`` en ``app/services/backup.py``) sigue fijada a 0005
porque esta revisión es opcional y no introduce tablas críticas para el
manifiesto.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSION = 768


def _bind() -> sa.engine.Connection | sa.engine.Engine:
    return op.get_bind()


def _dialect_name() -> str:
    bind = _bind()
    return getattr(bind.dialect, "name", "unknown")


def _table_names() -> set[str]:
    return set(inspect(_bind()).get_table_names())


def upgrade() -> None:
    """Aplica la migración sólo donde tenga sentido (PostgreSQL)."""

    if _dialect_name() != "postgresql":
        # SQLite/MySQL/etc.: la columna vector no existe. No creamos la
        # tabla para no introducir columnas no soportadas. El cambio se
        # mantiene registrado para que Alembic mueva la marca de revisión
        # y el historial quede alineado.
        return

    if "product_embeddings" in _table_names():
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Se usa el tipo ``pgvector.sqlalchemy.Vector`` cuando está disponible
    # (imagen ``pgvector/pgvector:pg15``); si no, se cae al textual ``ARRAY``
    # para que la migración no rompa en builds sin la dependencia. La
    # opción preferente es Vector: ``<=>`` (cosine) requiere ese tipo.
    try:  # pragma: no cover - depende de la imagen
        from pgvector.sqlalchemy import Vector

        embedding_col = Vector(EMBEDDING_DIMENSION)
    except Exception:  # pragma: no cover - fallback textual
        embedding_col = sa.dialects.postgresql.ARRAY(sa.Float(), dimensions=1)

    op.create_table(
        "product_embeddings",
        sa.Column(
            "installation_id",
            sa.String(length=128),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(length=64),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "model_name",
            sa.String(length=128),
            nullable=False,
            server_default="nomic-embed-text",
        ),
        sa.Column("embedding", embedding_col, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "installation_id", "product_id", name="uq_product_embeddings_inst_prod"
        ),
    )
    # FK tenant-safe hacia ``products(id)``. La columna ``products.id`` no
    # lleva ``installation_id``; la clave compuesta garantiza que un
    # embedding sólo apunte a un producto de la misma instalación.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_product_embeddings_product'
            ) THEN
                ALTER TABLE product_embeddings
                ADD CONSTRAINT fk_product_embeddings_product
                FOREIGN KEY (installation_id, product_id)
                REFERENCES products (installation_id, id)
                ON DELETE CASCADE;
            END IF;
        END$$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_embeddings_inst "
        "ON product_embeddings (installation_id)"
    )
    # Índice ANN opcional (ivfflat). Se crea con ``IF NOT EXISTS``; si la
    # extensión no expone el operador todavía, la migración sigue siendo
    # válida: el índice se puede añadir manualmente en el destino.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_embeddings_vector "
        "ON product_embeddings USING ivfflat (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Política de downgrades preservadores (0001-0004): no se borra la tabla.

    Si el operador quiere eliminarla por completo debe hacerlo manualmente
    para no perder datos de embeddings que ya no se regeneran en frío.
    """

    # No-op por diseño: el repositorio mantiene la tabla para preservar
    # historial de embeddings en caso de rollback de release.
    return