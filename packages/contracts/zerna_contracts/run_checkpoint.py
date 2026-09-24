"""Run checkpoint contract for pipeline step failure persistence and resume."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from .base import ZernaBaseModel
from .enums import RunStatus


class RunCheckpoint(ZernaBaseModel):
    """Checkpoint persisted when a pipeline step completes or fails.

    Enables resume-from-failure by recording the last known good state,
    the step that failed, and any artifacts produced up to that point.
    """

    run_id: UUID = Field(description="Run this checkpoint belongs to")
    step_name: str = Field(min_length=1, description="Pipeline step name")
    status: RunStatus = Field(description="Status of this step (COMPLETED or FAILED)")
    artifact_refs: list[str] = Field(
        default_factory=list,
        description="S3 keys of artifacts produced by this step",
    )
    started_at: datetime = Field(description="When the step started executing")
    completed_at: datetime | None = Field(
        default=None, description="When the step finished (None if still running)"
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if the step failed; must be non-null when status=FAILED",
    )

    @field_validator("step_name", mode="before")
    @classmethod
    def normalize_step_name(cls, value: object) -> object:
        """Coerce legacy object-shaped step references into a canonical string name."""
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name:
                return name
        return value
