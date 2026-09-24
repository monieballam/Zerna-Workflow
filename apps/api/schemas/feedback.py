"""Feedback API schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

FeedbackScope = Literal["system", "run"]
FeedbackCategory = Literal["bug", "science", "ux", "performance", "feature", "other"]


class CreateFeedbackRequest(BaseModel):
    """Create feedback request."""

    scope: FeedbackScope = Field(
        default="system",
        description="Whether the feedback applies to the whole system or one specific run.",
    )
    category: FeedbackCategory = Field(
        default="other",
        description="Broad category used to triage the feedback.",
    )
    run_id: UUID | None = Field(
        default=None,
        description="Required when scope='run'.",
    )
    title: str | None = Field(default=None, min_length=1, max_length=255)
    message: str = Field(..., min_length=5, max_length=10000)

    @model_validator(mode="after")
    def validate_scope(self) -> "CreateFeedbackRequest":
        """Require run_id when the feedback is tied to a run."""
        if self.scope == "run" and self.run_id is None:
            raise ValueError("run_id is required when scope='run'")
        if self.scope == "system":
            self.run_id = None
        return self


class FeedbackResponse(BaseModel):
    """Feedback response returned after submission."""

    id: UUID
    organization_id: UUID
    user_id: UUID | None = None
    user_email: str = Field(alias="user_email_snapshot")
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

    class Config:
        from_attributes = True
        populate_by_name = True


class ListFeedbackResponse(BaseModel):
    """Paginated feedback list."""

    items: list[FeedbackResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
