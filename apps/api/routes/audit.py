"""Audit event API routes.

GET /v1/audit-events — list audit events with filtering and pagination.

Requirements: 15.4
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_auth_service, get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.schemas.audit import AuditEventResponse, ListAuditEventsResponse
from apps.api.services.audit_service import AuditService
from apps.api.services.auth_service import AuthService

router = APIRouter(prefix="/v1/audit-events", tags=["audit"])


async def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    """Dependency: AuditService."""
    return AuditService(db)


@router.get(
    "",
    response_model=ListAuditEventsResponse,
    status_code=status.HTTP_200_OK,
    summary="List audit events",
    description=(
        "Return a paginated, filtered list of audit events for the caller's organization. "
        "Only org members can query their own org's events."
    ),
)
async def list_audit_events(
    organization_id: UUID = Query(..., description="Organization to query audit events for"),
    user_id: UUID | None = Query(None, description="Filter by user who performed the action"),
    resource_type: str | None = Query(
        None, description="Filter by resource type (e.g. 'dataset', 'run')"
    ),
    resource_id: UUID | None = Query(None, description="Filter by specific resource ID"),
    start_date: datetime | None = Query(
        None, description="Include events at or after this timestamp (ISO 8601)"
    ),
    end_date: datetime | None = Query(
        None, description="Include events at or before this timestamp (ISO 8601)"
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Events per page"),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> ListAuditEventsResponse:
    """List audit events for an organization.

    Requires the caller to be a member of the specified organization.
    """
    # Verify caller is a member of the requested organization
    is_member = await auth_service.is_member_of_organization(current_user.id, organization_id)
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    events, total = await audit_service.list_events(
        org_id=organization_id,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

    total_pages = max(1, (total + page_size - 1) // page_size)

    return ListAuditEventsResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
