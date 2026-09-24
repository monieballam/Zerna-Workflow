"""Authentication API schemas."""

from datetime import datetime
from uuid import UUID

from zerna_contracts.enums import UserRole
from pydantic import BaseModel, EmailStr, Field


class UserOrganizationMembership(BaseModel):
    """Organization membership information returned in the auth session."""

    organization_id: UUID
    organization_name: str
    role: UserRole
    joined_at: datetime


class UserProfile(BaseModel):
    """User profile information."""

    id: UUID
    email: str
    created_at: datetime
    organizations: list[UserOrganizationMembership] = Field(default_factory=list)
    active_organization_id: UUID | None = None
    active_organization_name: str | None = None
    active_role: UserRole | None = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")


class SignupRequest(BaseModel):
    """Signup request schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    organization_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=255,
        description="Optional initial organization/workspace name",
    )


class LoginResponse(BaseModel):
    """Login response schema."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration in seconds")
    user: UserProfile = Field(..., description="User profile information")


class RefreshRequest(BaseModel):
    """Token refresh request schema."""

    refresh_token: str = Field(..., description="JWT refresh token")


class RefreshResponse(BaseModel):
    """Token refresh response schema."""

    access_token: str = Field(..., description="New JWT access token")
    refresh_token: str = Field(..., description="New JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration in seconds")
