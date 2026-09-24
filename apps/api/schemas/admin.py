"""Admin API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from zerna_contracts.enums import UserRole
from pydantic import BaseModel, EmailStr, Field

from apps.api.schemas.feedback import FeedbackCategory, FeedbackScope


class OrganizationMemberResponse(BaseModel):
    """Organization member summary for admin views."""

    user_id: UUID
    email: str
    role: UserRole
    joined_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class ListOrganizationMembersResponse(BaseModel):
    """List organization members response."""

    items: list[OrganizationMemberResponse]


class CreateOrganizationMemberRequest(BaseModel):
    """Create or attach a user to the current organization."""

    email: EmailStr
    password: str | None = Field(
        default=None,
        min_length=8,
        description="Required only when the email does not already exist in the system.",
    )
    role: UserRole = Field(default=UserRole.MEMBER)


class UpdateOrganizationMemberRoleRequest(BaseModel):
    """Change one member's role in the current organization."""

    role: UserRole


class AdminFeedbackResponse(BaseModel):
    """Feedback row enriched for admin review."""

    id: UUID
    organization_id: UUID
    user_id: UUID | None = None
    user_email: str
    scope: FeedbackScope
    category: FeedbackCategory
    title: str | None = None
    message: str
    run_id: UUID | None = None
    dataset_id_snapshot: UUID | None = None
    dataset_name_snapshot: str | None = None
    template_id_snapshot: UUID | None = None
    run_parameters_snapshot: dict[str, Any] | None = None
    run_status_snapshot: str | None = None
    created_at: datetime


class ListAdminFeedbackResponse(BaseModel):
    """Paginated admin feedback list."""

    items: list[AdminFeedbackResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
