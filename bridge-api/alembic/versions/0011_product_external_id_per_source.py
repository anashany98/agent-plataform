"""Make product ``external_id`` unique per source, not per installation.

Revision ID: 0011
Revises: 0010

Problema observado al conectar PrestaShop real (btopdigital.es): el catálogo
importado por CSV y el sincronizado desde la tienda comparten los ids externos
(``external_id`` del CSV es el mismo id de producto de PrestaShop). La
constraint ``uq_product_installation_external_id`` sobre
``(installation_id, external_id)`` sin distinguir fuente provocaba
``UniqueViolation`` en el commit del sync (p. ej. external_id=42 existe como
``source='import'`` y la tienda lo reclama como ``source='prestashop'``).

La app ya consulta los productos de PrestaShop filtrando por
``source == 'prestashop'`` (webhook y sync), así que la unicidad solo tiene
sentido POR FUENTE: ``(installation_id, source, external_id)``.

Es **Postgres-only** (mismo patrón que 0006/0009/0010):
- En **PostgreSQL** drop de la constraint antigua y creación de la nueva. Es
  seguro con datos existentes: si ``(installation_id, external_id)`` era único
  en toda la tabla, ``(installation_id, source, external_id)`` también lo es.
- En **SQLite** es no-op. SQLite no soporta ``ALTER TABLE ... DROP/ADD
  CONSTRAINT`` (ni en 3.42) y el rebuild de la tabla rompe las FKs que apuntan
  a ``products`` (``reservations``, líneas de pedido); la migración 0011 en el
  path de Alembic conserva la constraint legacy en SQLite, mientras que el
  path ``Base.metadata.create_all`` (corpus de tests) usa la constraint nueva
  declarada en el modelo. PostgreSQL es la autoridad de producción.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CONSTRAINT = "uq_product_installation_external_id"
NEW_CONSTRAINT = "uq_product_installation_source_external_id"


def _dialect_name() -> str:
    bind = op.get_bind()
    return getattr(bind.dialect, "name", "unknown")


def upgrade() -> None:
    if _dialect_name() != "postgresql":
        return
    op.execute(f"ALTER TABLE products DROP CONSTRAINT IF EXISTS {OLD_CONSTRAINT}")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{NEW_CONSTRAINT}'
                  AND conrelid = 'products'::regclass
            ) THEN
                ALTER TABLE products
                ADD CONSTRAINT {NEW_CONSTRAINT}
                UNIQUE (installation_id, source, external_id);
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    """No-op por diseño: política de downgrades preservadores (0001-0004)."""
    return
