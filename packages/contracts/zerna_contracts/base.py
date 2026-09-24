"""Base Pydantic models for Zerna platform contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ZernaBaseModel(BaseModel):
    """Base model for all Zerna contracts with common configuration."""

    model_config = ConfigDict(
        # Use attribute names as-is (no camelCase conversion)
        populate_by_name=True,
        # Validate on assignment
        validate_assignment=True,
        # Allow arbitrary types for UUID, datetime, etc.
        arbitrary_types_allowed=False,
        # Strict mode for better type safety
        strict=False,
        # Use enum values instead of enum instances in serialization
        use_enum_values=True,
        # Validate default values
        validate_default=True,
        # Extra fields are forbidden by default
        extra="forbid",
    )


class TimestampedModel(ZernaBaseModel):
    """Base model with created_at timestamp."""

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when the resource was created"
    )


class OrganizationScopedModel(TimestampedModel):
    """Base model for resources scoped to an organization."""

    organization_id: UUID = Field(description="ID of the organization that owns this resource")


class IdentifiedModel(ZernaBaseModel):
    """Base model with UUID identifier."""

    id: UUID = Field(description="Unique identifier for the resource")


class PaginationParams(ZernaBaseModel):
    """Common pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(
        default=20, ge=1, le=100, description="Number of items per page (max 100)"
    )


class PaginatedResponse(ZernaBaseModel):
    """Base model for paginated list responses."""

    total: int = Field(ge=0, description="Total number of items across all pages")
    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, description="Number of items per page")


class ErrorDetail(ZernaBaseModel):
    """Detailed error information."""

    field: str | None = Field(default=None, description="Field that caused the error")
    message: str = Field(description="Human-readable error message")
    code: str | None = Field(default=None, description="Machine-readable error code")


class ErrorResponse(ZernaBaseModel):
    """Standard error response format."""

    error_type: str = Field(
        description="Error classification (user_error, system_error, transient_error)"
    )
    error_code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] | None = Field(default=None, description="Additional error context")
    request_id: str = Field(description="Request ID for tracing")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When the error occurred"
    )


class HealthCheckResponse(ZernaBaseModel):
    """Health check response."""

    status: str = Field(description="Service health status")
    version: str = Field(description="Service version")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Health check timestamp"
    )
    dependencies: dict[str, str] | None = Field(
        default=None, description="Status of service dependencies"
    )
