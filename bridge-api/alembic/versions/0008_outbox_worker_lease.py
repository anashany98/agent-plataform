"""0008: lease del worker durable en ``outbox_messages``.

Fase B (bloque 3): añade ``processing_until`` para que un mensaje en
``processing`` con lease vencido (worker muerto) pueda reclamarse y
reintentarse. Aditiva, idempotente y portable en ambos dialectos
(SQLite/PostgreSQL). El ``downgrade`` sigue la política preservadora del
repositorio (0001-0007): NO elimina la columna ni el índice para no perder
la señal de lease ante un rollback de release.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "outbox_messages", "processing_until"):
        op.add_column(
            "outbox_messages",
            sa.Column("processing_until", sa.DateTime(), nullable=True),
        )
    inspector = sa.inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes("outbox_messages")}
    if "ix_outbox_messages_processing_until" not in indexes:
        op.create_index(
            "ix_outbox_messages_processing_until",
            "outbox_messages",
            ["processing_until"],
        )


def downgrade() -> None:
    # Política preservadora: un rollback de release no borra la columna de
    # lease; los mensajes quedan con processing_until a NULL y el reclaim los
    # reclama igualmente (or_ processing_until IS NULL).
    return
