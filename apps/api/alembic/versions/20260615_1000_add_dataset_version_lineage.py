"""add dataset version lineage fields

Revision ID: a3b7c9d1e2f4
Revises: e1acfd25f882
Create Date: 2026-06-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3b7c9d1e2f4"
down_revision: str | Sequence[str] | None = "e1acfd25f882"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add lineage columns to dataset_versions table."""
    op.add_column(
        "dataset_versions",
        sa.Column("checksum", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "dataset_versions",
        sa.Column("source_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "dataset_versions",
        sa.Column(
            "parent_version_ids",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column(
        "dataset_versions",
        sa.Column(
            "schema_summary",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column(
        "dataset_versions",
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    """Remove lineage columns from dataset_versions table."""
    op.drop_column("dataset_versions", "uploaded_by")
    op.drop_column("dataset_versions", "schema_summary")
    op.drop_column("dataset_versions", "parent_version_ids")
    op.drop_column("dataset_versions", "source_type")
    op.drop_column("dataset_versions", "checksum")
