"""Feedback submission routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.middleware.auth import (
    CurrentOrganizationContext,
    get_current_org_context,
    get_current_user,
)
from apps.api.models.organization import User
from apps.api.schemas.feedback import (
    CreateFeedbackRequest,
    FeedbackResponse,
    ListFeedbackResponse,
)
from apps.api.services.feedback_service import FeedbackService

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


async def get_feedback_service(
    db: AsyncSession = Depends(get_db),
) -> FeedbackService:
    """Get FeedbackService dependency."""
    return FeedbackService(db=db)


@router.post(
    "",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback",
    description="Submit system-wide or run-specific feedback in the current organization.",
)
async def create_feedback(
    request: CreateFeedbackRequest,
    user: User = Depends(get_current_user),
    org_context: CurrentOrganizationContext = Depends(get_current_org_context),
    feedback_service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackResponse:
    """Create one feedback submission."""
    try:
        feedback = await feedback_service.create_feedback(
            org_id=org_context.organization_id,
            user=user,
            scope=request.scope,
            category=request.category,
            title=request.title,
            message=request.message,
            run_id=request.run_id,
        )
    except ValueError as exc:
        error_message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in error_message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=error_message) from exc

    return FeedbackResponse.model_validate(feedback)


@router.get(
    "",
    response_model=ListFeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="List feedback",
    description="List feedback in the current organization. Intended for the submitter-facing feedback page.",
)
async def list_feedback(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scope: str | None = Query(default=None),
    category: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    org_context: CurrentOrganizationContext = Depends(get_current_org_context),
    feedback_service: FeedbackService = Depends(get_feedback_service),
) -> ListFeedbackResponse:
    """List feedback entries for the current organization."""
    items, total = await feedback_service.list_feedback(
        org_id=org_context.organization_id,
        user_id=user.id,
        page=page,
        page_size=page_size,
        scope=scope,
        category=category,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ListFeedbackResponse(
        items=[FeedbackResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
