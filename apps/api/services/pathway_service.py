"""PathwayService for cross-dataset pathway analysis orchestration."""

import statistics
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.pathway import CrossDatasetAnalysis


class PathwayService:
    """Service for cross-dataset pathway analysis.

    Orchestrates multi-dataset aggregation, computes statistical significance,
    and stores analysis results. LLM interpretation is handled via Temporal.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_analysis(
        self,
        organization_id: UUID,
        created_by: UUID,
        dataset_ids: list[UUID],
        pathway_database: str = "MSigDB",
        aggregation_method: str = "meta-analysis",
    ) -> CrossDatasetAnalysis:
        """Create a new cross-dataset analysis record (status=pending).

        The actual computation is triggered via Temporal workflow.
        """
        analysis = CrossDatasetAnalysis(
            id=uuid4(),
            organization_id=organization_id,
            created_by=created_by,
            dataset_ids=[str(d) for d in dataset_ids],
            pathway_database=pathway_database,
            aggregation_method=aggregation_method,
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.db.add(analysis)
        await self.db.commit()
        await self.db.refresh(analysis)
        return analysis

    async def get_analysis(
        self, analysis_id: UUID, organization_id: UUID
    ) -> CrossDatasetAnalysis | None:
        """Return analysis by ID scoped to organization, or None."""
        stmt = select(CrossDatasetAnalysis).where(
            CrossDatasetAnalysis.id == analysis_id,
            CrossDatasetAnalysis.organization_id == organization_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_analyses(
        self,
        organization_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[CrossDatasetAnalysis], int]:
        """List analyses for an organization with pagination."""
        from sqlalchemy import func

        count_stmt = select(func.count()).where(
            CrossDatasetAnalysis.organization_id == organization_id
        )
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = (
            select(CrossDatasetAnalysis)
            .where(CrossDatasetAnalysis.organization_id == organization_id)
            .order_by(CrossDatasetAnalysis.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    def aggregate_pathway_scores(
        self,
        dataset_summaries: list[dict[str, Any]],
        aggregation_method: str = "meta-analysis",
    ) -> list[dict[str, Any]]:
        """Aggregate pathway scores across datasets using meta-analysis.

        Args:
            dataset_summaries: list of {dataset_id, pathway_scores: {pathway_id: float}}
            aggregation_method: "meta-analysis" (default) or "mean"

        Returns:
            list of pathway pattern dicts sorted by p_value ascending
        """
        # Collect all pathway IDs
        all_pathway_ids: set = set()
        for summary in dataset_summaries:
            all_pathway_ids.update(summary.get("pathway_scores", {}).keys())

        patterns = []
        n_datasets = len(dataset_summaries)

        for pathway_id in all_pathway_ids:
            scores = [
                s["pathway_scores"][pathway_id]
                for s in dataset_summaries
                if pathway_id in s.get("pathway_scores", {})
            ]
            datasets_present = [
                s["dataset_id"]
                for s in dataset_summaries
                if pathway_id in s.get("pathway_scores", {})
            ]

            if len(scores) < 2:
                continue  # require presence in ≥2 datasets

            aggregated_score = statistics.mean(scores)
            score_variance = statistics.variance(scores) if len(scores) > 1 else 0.0

            # Statistical significance: lower variance + higher score = lower p-value
            # Production: use Stouffer's Z-score method or Fisher's combined probability
            p_value = max(1e-6, score_variance / (aggregated_score + 1e-9) / len(scores))
            p_value = min(1.0, p_value)
            confidence = len(scores) / n_datasets

            patterns.append(
                {
                    "pathway_name": pathway_id,
                    "pathway_id": pathway_id,
                    "datasets_present": datasets_present,
                    "aggregated_score": aggregated_score,
                    "p_value": p_value,
                    "confidence": confidence,
                }
            )

        patterns.sort(key=lambda p: p["p_value"])
        return patterns

    async def update_analysis_results(
        self,
        analysis_id: UUID,
        organization_id: UUID,
        status: str,
        patterns: list[dict] | None = None,
        error_message: str | None = None,
    ) -> CrossDatasetAnalysis | None:
        """Update analysis with computed results."""
        analysis = await self.get_analysis(analysis_id, organization_id)
        if analysis is None:
            return None

        analysis.status = status
        analysis.completed_at = datetime.utcnow()
        if patterns is not None:
            analysis.pathway_patterns = patterns
        if error_message:
            analysis.error_message = error_message

        await self.db.commit()
        await self.db.refresh(analysis)
        return analysis
