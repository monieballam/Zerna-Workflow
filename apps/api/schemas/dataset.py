"""Dataset API schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from zerna_contracts.enums import RunStatus
from pydantic import BaseModel, Field


class DatasetVersionSummary(BaseModel):
    """Summary of a dataset version."""

    id: UUID
    version: str
    s3_path: str
    cell_count: int | None = None
    gene_count: int | None = None
    file_format: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, alias="extra_metadata", serialization_alias="metadata"
    )
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class DatasetResponse(BaseModel):
    """Dataset response schema."""

    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, alias="extra_metadata", serialization_alias="metadata"
    )
    created_at: datetime
    versions: list[DatasetVersionSummary] = Field(default_factory=list)

    class Config:
        from_attributes = True
        populate_by_name = True


class CreateDatasetRequest(BaseModel):
    """Create dataset request schema."""

    name: str = Field(..., min_length=1, max_length=255, description="Dataset name")
    description: str | None = Field(None, description="Dataset description")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class UpdateDatasetRequest(BaseModel):
    """Update dataset metadata request schema."""

    name: str | None = Field(None, min_length=1, max_length=255, description="New dataset name")
    description: str | None = Field(None, description="New dataset description")
    metadata: dict[str, Any] | None = Field(None, description="Metadata to merge with existing")


class CreateVersionRequest(BaseModel):
    """Create dataset version request schema."""

    pass  # File upload will be handled via multipart/form-data


class DatasetVersionResponse(BaseModel):
    """Dataset version response schema."""

    id: UUID
    dataset_id: UUID
    version: str
    s3_path: str
    cell_count: int | None = None
    gene_count: int | None = None
    file_format: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, alias="extra_metadata", serialization_alias="metadata"
    )
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class DatasetVersionColumnsResponse(BaseModel):
    """Dataset-version column metadata for parameter pickers."""

    dataset_version_id: UUID
    obs_columns: list[str] = Field(default_factory=list)
    batch_candidates: list[str] = Field(default_factory=list)
    cluster_candidates: list[str] = Field(default_factory=list)
    source: str = Field(default="unknown", description="Where the column metadata was derived from")


class ListDatasetsRequest(BaseModel):
    """List datasets request schema (query parameters)."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: str = Field(default="created_at", description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort order (asc/desc)")
    name: str | None = Field(None, description="Filter by name (partial match)")
    created_after: datetime | None = Field(None, description="Filter by creation date (after)")
    created_before: datetime | None = Field(None, description="Filter by creation date (before)")
    min_cell_count: int | None = Field(None, ge=0, description="Minimum cell count")
    max_cell_count: int | None = Field(None, ge=0, description="Maximum cell count")
    file_format: str | None = Field(None, description="Filter by file format")


class ListDatasetsResponse(BaseModel):
    """List datasets response schema."""

    items: list[DatasetResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteDatasetRequest(BaseModel):
    """Delete dataset options."""

    run_delete_mode: Literal["preserve", "all", "selected"] = Field(
        default="preserve",
        description="Whether to preserve associated runs or delete all/specific runs first.",
    )
    run_ids: list[UUID] = Field(
        default_factory=list,
        description="Associated runs to delete when run_delete_mode='selected'.",
    )


class DeleteDatasetResponse(BaseModel):
    """Delete dataset summary."""

    dataset_id: UUID
    deleted_runs: int
    preserved_runs: int


class BulkDeleteDatasetsRequest(BaseModel):
    """Bulk dataset deletion request."""

    scope: Literal["selected", "all"] = Field(
        ...,
        description="Delete explicitly selected datasets or every dataset in the organization.",
    )
    dataset_ids: list[UUID] = Field(
        default_factory=list,
        description="Dataset IDs to delete when scope='selected'.",
    )
    run_delete_mode: Literal["preserve", "all"] = Field(
        default="preserve",
        description="Whether to preserve associated runs or delete all of them before dataset deletion.",
    )


class BulkDeleteDatasetsResponse(BaseModel):
    """Bulk dataset deletion summary."""

    scope: Literal["selected", "all"]
    deleted_dataset_ids: list[UUID]
    deleted_datasets: int
    deleted_runs: int
    preserved_runs: int


class DatasetAssociatedRunResponse(BaseModel):
    """Summary of a run associated with one dataset."""

    id: UUID
    status: RunStatus
    template_id: UUID
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    dataset_deleted: bool = False

    class Config:
        from_attributes = True


class ListDatasetAssociatedRunsResponse(BaseModel):
    """List of runs associated with a dataset."""

    items: list[DatasetAssociatedRunResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
