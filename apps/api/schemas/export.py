"""Export API schemas."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

ExportType = Literal["h5ad", "de_results", "embeddings", "report"]


class ExportRequest(BaseModel):
    """Request body for initiating an export."""

    export_type: ExportType


class ExportResponse(BaseModel):
    """Response for a completed export."""

    run_id: UUID
    export_type: ExportType
    s3_path: str
    status: str = "completed"


class ExportStatusResponse(BaseModel):
    """Response for export status check."""

    run_id: UUID
    available_exports: list[ExportType]


class ExportDownloadResponse(BaseModel):
    """Response for export download URL generation."""

    run_id: UUID
    export_type: ExportType
    download_url: str
    expires_in: int = 3600
