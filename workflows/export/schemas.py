"""Schemas for export workflow."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class ExportStatus(str, Enum):
    """Export status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportInput(BaseModel):
    """Input for export workflow."""

    export_id: UUID
    run_id: UUID
    include_provenance: bool = True


class ExportOutput(BaseModel):
    """Output from export workflow."""

    export_id: UUID
    status: ExportStatus
    h5ad_url: str | None
    report_url: str | None
    error_message: str | None
