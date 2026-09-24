"""pipeline_templates: is_active, updated_at, indexes

Revision ID: c4e8f1a2b3d5
Revises: a3b7c9d1e2f4
Create Date: 2026-04-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8f1a2b3d5"
down_revision: str | Sequence[str] | None = "a3b7c9d1e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        name
        for column in inspector.get_columns(table_name)
        if isinstance(name := column["name"], str)
    }


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        name
        for index in inspector.get_indexes(table_name)
        if isinstance(name := index["name"], str)
    }


def upgrade() -> None:
    columns = _column_names("pipeline_templates")
    indexes = _index_names("pipeline_templates")

    if "is_active" not in columns:
        op.add_column(
            "pipeline_templates",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if "updated_at" not in columns:
        op.add_column(
            "pipeline_templates",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if "ix_pipeline_templates_org_name" not in indexes:
        op.create_index(
            "ix_pipeline_templates_org_name",
            "pipeline_templates",
            ["organization_id", "name"],
            unique=False,
        )
    if "ix_pipeline_templates_is_active" not in indexes:
        op.create_index(
            "ix_pipeline_templates_is_active",
            "pipeline_templates",
            ["is_active"],
            unique=False,
        )
    op.alter_column(
        "pipeline_templates",
        "is_active",
        server_default=None,
    )
    op.alter_column(
        "pipeline_templates",
        "updated_at",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_templates_is_active", table_name="pipeline_templates")
    op.drop_index("ix_pipeline_templates_org_name", table_name="pipeline_templates")
    op.drop_column("pipeline_templates", "updated_at")
    op.drop_column("pipeline_templates", "is_active")
