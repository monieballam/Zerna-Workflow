"""add feedback table

Revision ID: f2a14bc9de77
Revises: d91f4a7b2c10
Create Date: 2026-04-07 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f2a14bc9de77"
down_revision: str | Sequence[str] | None = "d91f4a7b2c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the feedback table used by the feedback and admin views."""
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("user_email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("dataset_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("template_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column(
            "run_parameters_snapshot",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("run_status_snapshot", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_organization_id", "feedback", ["organization_id"], unique=False)
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"], unique=False)
    op.create_index("ix_feedback_run_id", "feedback", ["run_id"], unique=False)
    op.create_index(
        "ix_feedback_dataset_id_snapshot", "feedback", ["dataset_id_snapshot"], unique=False
    )
    op.create_index(
        "ix_feedback_org_created_at", "feedback", ["organization_id", "created_at"], unique=False
    )
    op.create_index("ix_feedback_org_scope", "feedback", ["organization_id", "scope"], unique=False)
    op.create_index("ix_feedback_org_run", "feedback", ["organization_id", "run_id"], unique=False)


def downgrade() -> None:
    """Drop feedback table."""
    op.drop_index("ix_feedback_org_run", table_name="feedback")
    op.drop_index("ix_feedback_org_scope", table_name="feedback")
    op.drop_index("ix_feedback_org_created_at", table_name="feedback")
    op.drop_index("ix_feedback_dataset_id_snapshot", table_name="feedback")
    op.drop_index("ix_feedback_run_id", table_name="feedback")
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_index("ix_feedback_organization_id", table_name="feedback")
    op.drop_table("feedback")
