"""preserve runs when deleting datasets

Revision ID: d91f4a7b2c10
Revises: c4e8f1a2b3d5
Create Date: 2026-04-07 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d91f4a7b2c10"
down_revision: str | Sequence[str] | None = "c4e8f1a2b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_run_dataset_snapshots() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            UPDATE runs AS r
            SET
                dataset_id_snapshot = dv.dataset_id,
                dataset_version_id_snapshot = dv.id,
                dataset_name_snapshot = d.name,
                dataset_version_label_snapshot = dv.version
            FROM dataset_versions AS dv
            JOIN datasets AS d ON d.id = dv.dataset_id
            WHERE r.dataset_version_id = dv.id
            """
        )
        return

    op.execute(
        """
        UPDATE runs
        SET dataset_id_snapshot = (
                SELECT dv.dataset_id
                FROM dataset_versions AS dv
                WHERE dv.id = runs.dataset_version_id
            ),
            dataset_version_id_snapshot = (
                SELECT dv.id
                FROM dataset_versions AS dv
                WHERE dv.id = runs.dataset_version_id
            ),
            dataset_name_snapshot = (
                SELECT d.name
                FROM dataset_versions AS dv
                JOIN datasets AS d ON d.id = dv.dataset_id
                WHERE dv.id = runs.dataset_version_id
            ),
            dataset_version_label_snapshot = (
                SELECT dv.version
                FROM dataset_versions AS dv
                WHERE dv.id = runs.dataset_version_id
            )
        """
    )


def upgrade() -> None:
    """Allow runs to survive dataset deletion."""
    op.add_column("runs", sa.Column("dataset_id_snapshot", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("dataset_version_id_snapshot", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("dataset_name_snapshot", sa.String(length=255), nullable=True))
    op.add_column(
        "runs",
        sa.Column("dataset_version_label_snapshot", sa.String(length=50), nullable=True),
    )

    _backfill_run_dataset_snapshots()

    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint("runs_dataset_version_id_fkey", type_="foreignkey")
        batch_op.alter_column("dataset_version_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_foreign_key(
            "runs_dataset_version_id_fkey",
            "dataset_versions",
            ["dataset_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index("ix_runs_dataset_id_snapshot", "runs", ["dataset_id_snapshot"], unique=False)
    op.create_index(
        "ix_runs_org_dataset_snapshot",
        "runs",
        ["organization_id", "dataset_id_snapshot"],
        unique=False,
    )


def downgrade() -> None:
    """Revert run preservation fields."""
    op.drop_index("ix_runs_org_dataset_snapshot", table_name="runs")
    op.drop_index("ix_runs_dataset_id_snapshot", table_name="runs")

    op.execute(
        """
        UPDATE runs
        SET dataset_version_id = dataset_version_id_snapshot
        WHERE dataset_version_id IS NULL AND dataset_version_id_snapshot IS NOT NULL
        """
    )

    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint("runs_dataset_version_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "runs_dataset_version_id_fkey",
            "dataset_versions",
            ["dataset_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.alter_column("dataset_version_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_column("runs", "dataset_version_label_snapshot")
    op.drop_column("runs", "dataset_name_snapshot")
    op.drop_column("runs", "dataset_version_id_snapshot")
    op.drop_column("runs", "dataset_id_snapshot")
