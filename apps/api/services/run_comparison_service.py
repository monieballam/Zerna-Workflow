"""Run comparison service backed by persisted run artifacts and metrics.

Replaces static/in-code run comparison data with queries against
persisted run artifacts and metrics in the database (Requirement 8.3).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.pipeline import Artifact, Run


class RunComparisonService:
    """Service for comparing runs using persisted artifacts and metrics."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def compare_runs(
        self,
        org_id: UUID,
        run_ids: list[UUID],
    ) -> dict[str, Any]:
        """Compare multiple runs by loading their persisted artifacts and metrics.

        Args:
            org_id: Organization ID for scoping.
            run_ids: List of run IDs to compare.

        Returns:
            Comparison dict with per-run summaries keyed by run ID string.

        Raises:
            ValueError: If any run is not found or doesn't belong to the org.
        """
        if len(run_ids) < 2:
            raise ValueError("At least two run IDs are required for comparison")

        summaries: dict[str, Any] = {}

        for run_id in run_ids:
            stmt = (
                select(Run)
                .where(and_(Run.id == run_id, Run.organization_id == org_id))
                .options(
                    selectinload(Run.artifacts),
                    selectinload(Run.dataset_version),
                    selectinload(Run.template),
                )
            )
            result = await self.db.execute(stmt)
            run = result.scalar_one_or_none()

            if run is None:
                raise ValueError(
                    f"Run {run_id} not found or does not belong to organization {org_id}"
                )

            summaries[str(run_id)] = self._build_run_summary(run)

        return {
            "run_count": len(run_ids),
            "runs": summaries,
        }

    def _build_run_summary(self, run: Run) -> dict[str, Any]:
        """Build a comparison summary from a persisted run and its artifacts."""
        artifact_summary = {}
        for artifact in run.artifacts:
            art_type = (
                artifact.artifact_type.value
                if hasattr(artifact.artifact_type, "value")
                else str(artifact.artifact_type)
            )
            artifact_summary[art_type] = {
                "id": str(artifact.id),
                "s3_path": artifact.s3_path,
                "size_bytes": artifact.size_bytes,
                "metadata": artifact.extra_metadata,
            }

        return {
            "run_id": str(run.id),
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "parameters": run.parameters,
            "software_versions": run.software_versions,
            "random_seed": run.random_seed,
            "dataset_version_id": str(run.source_dataset_version_id)
            if run.source_dataset_version_id is not None
            else None,
            "template_id": str(run.template_id),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "artifacts": artifact_summary,
        }

    async def get_run_metrics(self, run_id: UUID, org_id: UUID) -> dict[str, Any]:
        """Get metrics for a single run from its persisted artifacts.

        Returns a dict of metric_name -> metric_value extracted from
        artifact metadata.
        """
        stmt = (
            select(Artifact)
            .join(Run, Artifact.run_id == Run.id)
            .where(and_(Run.id == run_id, Run.organization_id == org_id))
        )
        result = await self.db.execute(stmt)
        artifacts = list(result.scalars().all())

        metrics: dict[str, Any] = {}
        for artifact in artifacts:
            # Extract metrics stored in artifact metadata
            art_metrics = artifact.extra_metadata.get("metrics", {})
            if art_metrics:
                art_type = (
                    artifact.artifact_type.value
                    if hasattr(artifact.artifact_type, "value")
                    else str(artifact.artifact_type)
                )
                metrics[art_type] = art_metrics

        return metrics
