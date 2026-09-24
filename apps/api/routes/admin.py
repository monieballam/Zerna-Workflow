"""Admin routes for organization members and submitted feedback."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_service, get_db
from apps.api.middleware.auth import (
    CurrentOrganizationContext,
    get_current_user,
    require_current_admin,
)
from apps.api.models.organization import User
from apps.api.schemas.admin import (
    AdminFeedbackResponse,
    CreateOrganizationMemberRequest,
    ListAdminFeedbackResponse,
    ListOrganizationMembersResponse,
    OrganizationMemberResponse,
    UpdateOrganizationMemberRoleRequest,
)
from apps.api.schemas.feedback import FeedbackCategory, FeedbackScope
from apps.api.services.auth_service import AuthService
from apps.api.services.feedback_service import FeedbackService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


async def get_feedback_service(
    db: AsyncSession = Depends(get_db),
) -> FeedbackService:
    """Get FeedbackService dependency."""
    return FeedbackService(db=db)


@router.get(
    "/members",
    response_model=ListOrganizationMembersResponse,
    status_code=status.HTTP_200_OK,
    summary="List organization members",
    description="Admin-only member list for the current organization.",
)
async def list_members(
    org_context: CurrentOrganizationContext = Depends(require_current_admin),
    auth_service: AuthService = Depends(get_auth_service),
) -> ListOrganizationMembersResponse:
    """List organization members."""
    members = await auth_service.list_organization_members(org_context.organization_id)
    return ListOrganizationMembersResponse(
        items=[OrganizationMemberResponse.model_validate(member) for member in members]
    )


@router.post(
    "/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or attach a member",
    description="Admin-only endpoint to create a new user or attach an existing user to the current organization.",
)
async def create_member(
    request: CreateOrganizationMemberRequest,
    current_user: User = Depends(get_current_user),
    org_context: CurrentOrganizationContext = Depends(require_current_admin),
    auth_service: AuthService = Depends(get_auth_service),
) -> OrganizationMemberResponse:
    """Create a new member or add an existing user to the current organization."""
    try:
        member = await auth_service.create_or_add_member(
            organization_id=org_context.organization_id,
            email=request.email,
            password=request.password,
            role=request.role,
            acting_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return OrganizationMemberResponse.model_validate(member)


@router.patch(
    "/members/{member_user_id}",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Update member role",
    description="Admin-only endpoint to change one member's role within the current organization.",
)
async def update_member_role(
    member_user_id: UUID,
    request: UpdateOrganizationMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    org_context: CurrentOrganizationContext = Depends(require_current_admin),
    auth_service: AuthService = Depends(get_auth_service),
) -> OrganizationMemberResponse:
    """Update one member role."""
    try:
        member = await auth_service.update_member_role(
            organization_id=org_context.organization_id,
            member_user_id=member_user_id,
            role=request.role,
            acting_user_id=current_user.id,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not a member" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    return OrganizationMemberResponse.model_validate(member)


@router.get(
    "/feedback",
    response_model=ListAdminFeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="List feedback submissions",
    description="Admin-only feedback review surface for the current organization.",
)
async def list_feedback(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    scope: str | None = Query(default=None),
    category: str | None = Query(default=None),
    org_context: CurrentOrganizationContext = Depends(require_current_admin),
    feedback_service: FeedbackService = Depends(get_feedback_service),
) -> ListAdminFeedbackResponse:
    """List feedback with the run and dataset snapshots captured at submission time."""
    items, total = await feedback_service.list_feedback(
        org_id=org_context.organization_id,
        page=page,
        page_size=page_size,
        scope=scope,
        category=category,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return ListAdminFeedbackResponse(
        items=[
            AdminFeedbackResponse(
                id=item.id,
                organization_id=item.organization_id,
                user_id=item.user_id,
                user_email=item.user_email_snapshot,
                scope=cast(FeedbackScope, item.scope),
                category=cast(FeedbackCategory, item.category),
                title=item.title,
                message=item.message,
                run_id=item.run_id,
                dataset_id_snapshot=item.dataset_id_snapshot,
                dataset_name_snapshot=item.dataset_name_snapshot,
                template_id_snapshot=item.template_id_snapshot,
                run_parameters_snapshot=item.run_parameters_snapshot,
                run_status_snapshot=item.run_status_snapshot,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
