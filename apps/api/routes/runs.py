"""Run API routes."""

from typing import Any
from uuid import UUID

import anndata as ad
from zerna_contracts.enums import RunStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_cache_service, get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.schemas.run import (
    ArtifactResponse,
    BulkDeleteRunsRequest,
    BulkDeleteRunsResponse,
    CreateRunRequest,
    DeleteRunResponse,
    ListArtifactsResponse,
    ListRunsResponse,
    ResumeRunRequest,
    RunResponse,
)
from apps.api.services.cache_service import CacheService
from apps.api.services.run_explorer_service import RunExplorerService
from apps.api.services.run_service import RunService
from apps.api.tracing import set_span_user_context
from methods.annotation.audit.resource_guard import (
    AnnotationAuditResourceError,
    assert_h5ad_safe_for_sync_annotation_audit,
)
from methods.annotation.audit.runner import run_annotation_audit

router = APIRouter(prefix="/v1/runs", tags=["runs"])


async def get_run_service(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> RunService:
    """Get RunService dependency."""
    return RunService(db=db, cache_service=cache)


async def get_user_org_id(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UUID:
    """Get user's organization ID.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        Organization ID

    Raises:
        HTTPException: 403 if user not member of any organization
    """
    # Get user's first organization (for now, we'll use the first one)
    # In a real implementation, this would come from the request or user context
    result = await db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = result.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    return UUID(str(org_id))


@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create run",
    description="Create a new pipeline run with parameter validation",
)
async def create_run(
    request: CreateRunRequest,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Create a new run.

    Args:
        request: Create run request
        org_id: Organization ID from authenticated user
        run_service: Run service

    Returns:
        Created run in QUEUED status

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 404 if dataset version or template not found
    """
    try:
        run = await run_service.create_run(
            org_id=org_id,
            dataset_version_id=request.dataset_version_id,
            template_id=request.template_id,
            parameters=request.parameters,
            random_seed=request.random_seed,
            user_id=user.id,
        )

        # Auto-start the run (dispatches Temporal workflow)
        run = await run_service.start_run(run.id)

        set_span_user_context(org_id=org_id)
        return RunResponse.model_validate(run)

    except ValueError as e:
        # Check if it's a not found error or validation error
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create run: {str(e)}",
        )


@router.get(
    "",
    response_model=ListRunsResponse,
    status_code=status.HTTP_200_OK,
    summary="List runs",
    description="List runs with optional filtering and pagination",
)
async def list_runs(
    status_filter: RunStatus | None = Query(
        None, alias="status", description="Filter by run status"
    ),
    dataset_version_id: UUID | None = Query(None, description="Filter by dataset version"),
    dataset_id: UUID | None = Query(None, description="Filter by source dataset"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> ListRunsResponse:
    """List runs with optional filtering and pagination.

    Args:
        status_filter: Optional status filter
        dataset_version_id: Optional dataset version filter
        dataset_id: Optional dataset filter
        page: Page number
        page_size: Items per page
        org_id: Organization ID from authenticated user
        run_service: Run service

    Returns:
        Paginated list of runs
    """
    # Calculate offset
    offset = (page - 1) * page_size

    # List runs
    runs, total = await run_service.list_runs(
        org_id=org_id,
        status=status_filter,
        dataset_version_id=dataset_version_id,
        dataset_id=dataset_id,
        limit=page_size,
        offset=offset,
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return ListRunsResponse(
        items=[RunResponse.model_validate(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get run details",
    description="Get run details including status and parameters",
)
async def get_run(
    run_id: UUID,
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Get run details.

    Args:
        run_id: Run ID
        org_id: Organization ID from authenticated user
        run_service: Run service

    Returns:
        Run details

    Raises:
        HTTPException: 404 if run not found
    """
    run = await run_service.get_run(run_id=run_id, org_id=org_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    return RunResponse.model_validate(run)


@router.delete(
    "/{run_id}",
    response_model=DeleteRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete run",
    description="Delete a run and all persisted artifacts, snapshots, and local cache entries owned by it.",
)
async def delete_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> DeleteRunResponse:
    """Delete one run and all of its stored data."""
    try:
        deleted = await run_service.delete_run(run_id=run_id, org_id=org_id, user_id=user.id)
        return DeleteRunResponse.model_validate(deleted)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete run: {str(e)}",
        )


@router.post(
    "/cleanup",
    response_model=BulkDeleteRunsResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk delete runs",
    description="Delete all failed runs or all runs for the current organization, including persisted artifacts and snapshots.",
)
async def bulk_delete_runs(
    request: BulkDeleteRunsRequest,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> BulkDeleteRunsResponse:
    """Bulk-delete runs and their stored data."""
    try:
        deleted = await run_service.bulk_delete_runs(
            org_id=org_id,
            scope=request.scope,
            dataset_id=request.dataset_id,
            run_ids=request.run_ids,
            user_id=user.id,
        )
        return BulkDeleteRunsResponse.model_validate(deleted)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete runs: {str(e)}",
        )


@router.post(
    "/{run_id}/resume",
    response_model=RunResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume failed run",
    description="Resume a failed run after correcting parameters, continuing from the failed step checkpoint",
)
async def resume_run(
    run_id: UUID,
    request: ResumeRunRequest,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Resume a failed run with updated parameters."""
    try:
        run = await run_service.resume_run(
            run_id=run_id,
            org_id=org_id,
            parameters=request.parameters,
            random_seed=request.random_seed,
            user_id=user.id,
        )
        return RunResponse.model_validate(run)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume run: {str(e)}",
        )


@router.post(
    "/{run_id}/cancel",
    response_model=RunResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel run",
    description="Cancel a running or queued run",
)
async def cancel_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Cancel a run.

    Args:
        run_id: Run ID
        org_id: Organization ID from authenticated user
        run_service: Run service

    Returns:
        Updated run with CANCELLED status

    Raises:
        HTTPException: 404 if run not found
        HTTPException: 400 if run cannot be cancelled
    """
    try:
        # First verify the run belongs to the organization
        existing_run = await run_service.get_run(run_id=run_id, org_id=org_id)
        if existing_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )

        run = await run_service.cancel_run(run_id=run_id, user_id=user.id)
        return RunResponse.model_validate(run)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel run: {str(e)}",
        )


@router.get(
    "/{run_id}/artifacts",
    response_model=ListArtifactsResponse,
    status_code=status.HTTP_200_OK,
    summary="List run artifacts",
    description="List all artifacts produced by a run with optional pre-signed download URLs",
)
async def list_artifacts(
    run_id: UUID,
    generate_urls: bool = Query(default=True, description="Generate pre-signed S3 download URLs"),
    org_id: UUID = Depends(get_user_org_id),
    run_service: RunService = Depends(get_run_service),
) -> ListArtifactsResponse:
    """List run artifacts.

    Args:
        run_id: Run ID
        generate_urls: Whether to generate pre-signed S3 download URLs
        org_id: Organization ID from authenticated user
        run_service: Run service

    Returns:
        List of artifacts with optional download URLs

    Raises:
        HTTPException: 404 if run not found
    """
    try:
        artifacts_with_urls = await run_service.list_artifacts(
            run_id=run_id, org_id=org_id, generate_download_urls=generate_urls
        )

        # Convert to response schema
        artifact_responses = []
        for artifact, download_url in artifacts_with_urls:
            artifact_dict = {
                "id": artifact.id,
                "run_id": artifact.run_id,
                "artifact_type": artifact.artifact_type,
                "s3_path": artifact.s3_path,
                "size_bytes": artifact.size_bytes,
                "extra_metadata": artifact.extra_metadata,
                "download_url": download_url,
                "created_at": artifact.created_at,
            }
            artifact_responses.append(ArtifactResponse.model_validate(artifact_dict))

        return ListArtifactsResponse(artifacts=artifact_responses)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list artifacts: {str(e)}",
        )


@router.get(
    "/{run_id}/annotation-audit",
    status_code=status.HTTP_200_OK,
    summary="Annotation artifact audit",
    description=(
        "Runs the Kiro annotation QA suite on the run's primary H5AD artifact "
        "(same object as Run Explorer), using S3-backed artifact paths."
    ),
)
async def get_run_annotation_audit(
    run_id: UUID,
    cluster_key: str = Query(
        default="leiden", description="obs column for cluster-level L3 gating"
    ),
    _: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Load the latest H5AD artifact from S3 (with local cache) and return audit JSON."""
    explorer = RunExplorerService(db=db)
    try:
        local_path = await explorer.get_primary_h5ad_local_path(run_id=run_id, org_id=org_id)
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg or "no h5ad" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        if "completed" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        assert_h5ad_safe_for_sync_annotation_audit(local_path)
    except AnnotationAuditResourceError as e:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(e),
        )

    adata = ad.read_h5ad(local_path)
    try:
        return run_annotation_audit(adata, cluster_key=cluster_key)
    finally:
        del adata
