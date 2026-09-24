"""Schemas for run execution workflow."""

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RunStatus(str, Enum):
    """Run execution status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunExecutionInput(BaseModel):
    """Input for run execution workflow."""

    run_id: UUID
    dataset_version_id: UUID
    template_id: UUID
    parameters: dict[str, Any]
    random_seed: int


class RunExecutionOutput(BaseModel):
    """Output from run execution workflow."""

    run_id: UUID
    status: RunStatus
    artifacts: list[UUID]
    error_message: str | None
