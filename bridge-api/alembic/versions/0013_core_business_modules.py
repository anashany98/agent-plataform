"""Persist agent registry and safe draft-first business modules.

Revision ID: 0013
Revises: 0012

Adds only new tenant-owned tables. Publishing and scheduled execution remain
disabled at the data layer until an explicit approval changes their status.
The downgrade preserves data intentionally, following the non-destructive
policy of the existing migration chain.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _installation_index(table_name: str) -> None:
    op.create_index(
        f"ix_{table_name}_installation_id",
        table_name,
        ["installation_id"],
    )


def upgrade() -> None:
    tables = _table_names()
    if "agent_definitions" not in tables:
        op.create_table(
            "agent_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("configuration", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_agent_definition_installation_id",
            ),
            sa.CheckConstraint(
                "status IN ('draft','pending_approval','active','inactive','rejected')",
                name="ck_agent_definition_status",
            ),
            sa.CheckConstraint(
                "version >= 1",
                name="ck_agent_definition_version_positive",
            ),
        )
        _installation_index("agent_definitions")

    if "wiki_pages" not in tables:
        op.create_table(
            "wiki_pages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_wiki_page_installation_id",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "slug",
                name="uq_wiki_page_installation_slug",
            ),
            sa.CheckConstraint(
                "status IN ('draft','pending_approval','published','archived','rejected')",
                name="ck_wiki_page_status",
            ),
            sa.CheckConstraint("version >= 1", name="ck_wiki_page_version_positive"),
        )
        _installation_index("wiki_pages")

    if "seo_projects" not in tables:
        op.create_table(
            "seo_projects",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(length=240), nullable=False),
            sa.Column("domain", sa.String(length=253), nullable=False),
            sa.Column("configuration", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_seo_project_installation_id",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "domain",
                name="uq_seo_project_installation_domain",
            ),
            sa.CheckConstraint(
                "status IN ('draft','active','paused','archived')",
                name="ck_seo_project_status",
            ),
            sa.CheckConstraint("version >= 1", name="ck_seo_project_version_positive"),
        )
        _installation_index("seo_projects")

    if "landing_pages" not in tables:
        op.create_table(
            "landing_pages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_landing_page_installation_id",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "slug",
                name="uq_landing_page_installation_slug",
            ),
            sa.CheckConstraint(
                "status IN ('draft','pending_approval','approved','archived','rejected')",
                name="ck_landing_page_status",
            ),
            sa.CheckConstraint(
                "version >= 1",
                name="ck_landing_page_version_positive",
            ),
        )
        _installation_index("landing_pages")

    if "scheduled_tasks" not in tables:
        op.create_table(
            "scheduled_tasks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("task_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("interval_seconds", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("next_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("installation_id", sa.String(length=128), nullable=False),
            sa.UniqueConstraint(
                "installation_id",
                "id",
                name="uq_scheduled_task_installation_id",
            ),
            sa.UniqueConstraint(
                "installation_id",
                "name",
                name="uq_scheduled_task_installation_name",
            ),
            sa.CheckConstraint(
                "status IN ('draft','pending_approval','active','paused','rejected')",
                name="ck_scheduled_task_status",
            ),
            sa.CheckConstraint(
                "interval_seconds >= 60",
                name="ck_scheduled_task_interval_minimum",
            ),
            sa.CheckConstraint(
                "version >= 1",
                name="ck_scheduled_task_version_positive",
            ),
        )
        _installation_index("scheduled_tasks")


def downgrade() -> None:
    # No se destruyen definiciones, borradores ni contenido publicado.
    pass
