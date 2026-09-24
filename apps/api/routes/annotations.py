"""Annotation revision API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.routes.runs import get_user_org_id
from apps.api.schemas.annotation import (
    AnnotationRevisionResponse,
    CreateAnnotationRevisionRequest,
    EditAnnotationsRequest,
    ListAnnotationRevisionsResponse,
)
from apps.api.services.annotation_service import AnnotationService

router = APIRouter(tags=["annotations"])


async def get_annotation_service(db: AsyncSession = Depends(get_db)) -> AnnotationService:
    return AnnotationService(db=db)


@router.post(
    "/v1/runs/{run_id}/annotations",
    response_model=AnnotationRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation revision",
)
async def create_annotation_revision(
    run_id: UUID,
    request: CreateAnnotationRevisionRequest,
    current_user: User = Depends(get_current_user),
    svc: AnnotationService = Depends(get_annotation_service),
) -> AnnotationRevisionResponse:
    revision = await svc.create_revision(
        run_id=run_id,
        annotations=request.annotations,
        created_by=current_user.id,
        method=request.method,
        knowledge_pack_id=request.knowledge_pack_id,
    )
    return AnnotationRevisionResponse.model_validate(revision)


@router.patch(
    "/v1/annotations/{annotation_id}",
    response_model=AnnotationRevisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit annotations (creates new revision)",
)
async def edit_annotations(
    annotation_id: UUID,
    request: EditAnnotationsRequest,
    current_user: User = Depends(get_current_user),
    svc: AnnotationService = Depends(get_annotation_service),
) -> AnnotationRevisionResponse:
    try:
        new_revision = await svc.edit_annotations(
            revision_id=annotation_id,
            edits=request.edits,
            user_id=current_user.id,
        )
        return AnnotationRevisionResponse.model_validate(new_revision)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/v1/annotations/{annotation_id}/approve",
    response_model=AnnotationRevisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve annotation revision",
)
async def approve_revision(
    annotation_id: UUID,
    current_user: User = Depends(get_current_user),
    svc: AnnotationService = Depends(get_annotation_service),
) -> AnnotationRevisionResponse:
    try:
        revision = await svc.approve_revision(
            revision_id=annotation_id,
            approver_id=current_user.id,
        )
        return AnnotationRevisionResponse.model_validate(revision)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.get(
    "/v1/runs/{run_id}/annotations",
    response_model=ListAnnotationRevisionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List annotation revisions for a run",
)
async def list_revisions(
    run_id: UUID,
    _: User = Depends(get_current_user),
    svc: AnnotationService = Depends(get_annotation_service),
) -> ListAnnotationRevisionsResponse:
    revisions = await svc.list_revisions(run_id=run_id)
    return ListAnnotationRevisionsResponse(
        items=[AnnotationRevisionResponse.model_validate(r) for r in revisions],
        total=len(revisions),
    )


@router.post(
    "/v1/runs/{run_id}/annotations/bootstrap",
    response_model=AnnotationRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bootstrap annotations from completed run output",
)
async def bootstrap_annotations(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    svc: AnnotationService = Depends(get_annotation_service),
) -> AnnotationRevisionResponse:
    """Create an annotation revision from the completed run's H5AD artifact."""
    try:
        revision = await svc.bootstrap_revision_from_run(
            run_id=run_id,
            created_by=current_user.id,
            org_id=org_id,
        )
        return AnnotationRevisionResponse.model_validate(revision)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
