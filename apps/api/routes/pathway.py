"""Pathway analysis API routes.

Endpoints:
  POST /v1/pathway/cross-dataset   - initiate cross-dataset analysis
  GET  /v1/pathway/analyses/{id}   - get analysis results
  POST /v1/pathway/{id}/interpret  - request LLM interpretation
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db, get_redis
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.schemas.pathway import (
    CrossDatasetPathwayRequest,
    CrossDatasetPathwayResponse,
    InterpretPathwayRequest,
    InterpretPathwayResponse,
    PathwayPatternResponse,
)
from apps.api.services.llm_client import LLMClient
from apps.api.services.pathway_service import PathwayService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pathway"])


async def get_pathway_service(db: AsyncSession = Depends(get_db)) -> PathwayService:
    return PathwayService(db=db)


async def get_user_org_id(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Get the organization ID for the current user."""
    result = await db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :uid"),
        {"uid": user.id},
    )
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )
    return UUID(str(org_id))


def _to_response(analysis: Any) -> CrossDatasetPathwayResponse:
    """Convert CrossDatasetAnalysis model to response schema."""
    patterns = None
    if analysis.pathway_patterns:
        patterns = [PathwayPatternResponse(**p) for p in analysis.pathway_patterns]
    return CrossDatasetPathwayResponse(
        analysis_id=analysis.id,
        organization_id=analysis.organization_id,
        dataset_ids=analysis.dataset_ids,
        pathway_database=analysis.pathway_database,
        aggregation_method=analysis.aggregation_method,
        status=analysis.status,
        pathway_patterns=patterns,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


@router.post(
    "/v1/pathway/cross-dataset",
    response_model=CrossDatasetPathwayResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate cross-dataset pathway analysis",
)
async def initiate_cross_dataset_analysis(
    request: CrossDatasetPathwayRequest,
    current_user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    svc: PathwayService = Depends(get_pathway_service),
) -> CrossDatasetPathwayResponse:
    """Create a cross-dataset pathway analysis and trigger the Temporal workflow."""
    analysis = await svc.create_analysis(
        organization_id=org_id,
        created_by=current_user.id,
        dataset_ids=request.dataset_ids,
        pathway_database=request.pathway_database,
        aggregation_method=request.aggregation_method,
    )

    # Trigger Temporal workflow asynchronously
    try:
        from temporalio.client import Client

        from workflows.config import get_workflow_settings
        from workflows.cross_dataset_pathway.schemas import CrossDatasetPathwayInput
        from workflows.cross_dataset_pathway.workflow import CrossDatasetPathwayWorkflow

        settings = get_workflow_settings()
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
        )
        await client.start_workflow(
            CrossDatasetPathwayWorkflow.run,
            CrossDatasetPathwayInput(
                analysis_id=analysis.id,
                organization_id=analysis.organization_id,
                dataset_ids=[UUID(d) for d in analysis.dataset_ids],
                pathway_database=analysis.pathway_database,
                aggregation_method=analysis.aggregation_method,
                llm_model=None,  # LLM called separately via /interpret endpoint
            ),
            id=f"pathway-analysis-{analysis.id}",
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        logger.error(f"Failed to start Temporal workflow for analysis {analysis.id}: {e}")
        # Analysis record is created; workflow can be retried or status polled

    return _to_response(analysis)


@router.get(
    "/v1/pathway/analyses/{analysis_id}",
    response_model=CrossDatasetPathwayResponse,
    status_code=status.HTTP_200_OK,
    summary="Get cross-dataset analysis results",
)
async def get_analysis(
    analysis_id: UUID,
    org_id: UUID = Depends(get_user_org_id),
    svc: PathwayService = Depends(get_pathway_service),
) -> CrossDatasetPathwayResponse:
    analysis = await svc.get_analysis(
        analysis_id=analysis_id,
        organization_id=org_id,
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis {analysis_id} not found",
        )
    return _to_response(analysis)


@router.post(
    "/v1/pathway/{analysis_id}/interpret",
    response_model=InterpretPathwayResponse,
    status_code=status.HTTP_200_OK,
    summary="Request LLM interpretation of pathway analysis",
)
async def interpret_analysis(
    analysis_id: UUID,
    request: InterpretPathwayRequest,
    org_id: UUID = Depends(get_user_org_id),
    svc: PathwayService = Depends(get_pathway_service),
) -> InterpretPathwayResponse:
    """Call LLM to interpret pathway patterns and generate hypotheses."""
    analysis = await svc.get_analysis(
        analysis_id=analysis_id,
        organization_id=org_id,
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis {analysis_id} not found",
        )
    if analysis.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis is not completed (status={analysis.status})",
        )
    if not analysis.pathway_patterns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis has no pathway patterns to interpret",
        )

    redis = await get_redis()
    llm = LLMClient(redis_client=redis)

    try:
        response = await llm.interpret_pathways(
            patterns=analysis.pathway_patterns,
            model=request.model,
            organization_id=str(org_id),
            context=request.context,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Persist interpretation back to analysis record
    analysis.llm_interpretation = response.interpretation
    analysis.llm_hypotheses = response.hypotheses
    analysis.llm_model_used = response.model_used
    if not response.from_cache:
        analysis.llm_cost_usd = (analysis.llm_cost_usd or 0.0) + response.cost_usd
    await svc.db.commit()

    return InterpretPathwayResponse(
        analysis_id=analysis_id,
        interpretation=response.interpretation,
        hypotheses=response.hypotheses,
        suggested_experiments=response.suggested_experiments,
        model_used=response.model_used,
        cost_usd=response.cost_usd,
        from_cache=response.from_cache,
    )
