"""Run API schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from zerna_contracts.enums import ArtifactType, RunStatus
from pydantic import BaseModel, Field


class RunResponse(BaseModel):
    """Run response schema."""

    id: UUID
    organization_id: UUID
    dataset_version_id: UUID | None = None
    source_dataset_id: UUID | None = None
    source_dataset_version_id: UUID | None = None
    dataset_name: str | None = None
    dataset_version_label: str | None = None
    dataset_deleted: bool = False
    template_id: UUID
    status: RunStatus
    parameters: dict[str, Any]
    software_versions: dict[str, str] | None = None
    random_seed: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class CreateRunRequest(BaseModel):
    """Create run request schema."""

    dataset_version_id: UUID = Field(..., description="Dataset version to run against")
    template_id: UUID = Field(..., description="Pipeline template to execute")
    parameters: dict[str, Any] = Field(
        ..., description="Run parameters to validate against template schema"
    )
    random_seed: int | None = Field(None, description="Optional random seed for reproducibility")


class ResumeRunRequest(BaseModel):
    """Resume a failed run after correcting parameters."""

    parameters: dict[str, Any] = Field(
        ..., description="Updated run parameters to validate against the existing template"
    )
    random_seed: int | None = Field(
        None,
        description="Optional replacement random seed. If omitted, the previous run seed is kept.",
    )


class DeleteRunResponse(BaseModel):
    """Run deletion summary."""

    run_id: UUID
    deleted_artifacts: int
    deleted_storage_objects: int


class BulkDeleteRunsRequest(BaseModel):
    """Bulk run cleanup request."""

    scope: Literal["failed", "all", "selected"] = Field(
        ...,
        description="Delete failed runs, all runs, or only explicitly selected runs.",
    )
    dataset_id: UUID | None = Field(
        None,
        description="Optionally limit cleanup to runs originally associated with one dataset.",
    )
    run_ids: list[UUID] = Field(
        default_factory=list,
        description="Run IDs to delete when scope='selected'.",
    )


class BulkDeleteRunsResponse(BaseModel):
    """Bulk run cleanup summary."""

    scope: Literal["failed", "all", "selected"]
    dataset_id: UUID | None = None
    deleted_run_ids: list[UUID]
    deleted_runs: int
    deleted_artifacts: int
    deleted_storage_objects: int


class ArtifactResponse(BaseModel):
    """Artifact response schema."""

    id: UUID
    run_id: UUID
    artifact_type: ArtifactType
    s3_path: str
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="extra_metadata")
    download_url: str | None = Field(None, description="Pre-signed S3 download URL (if generated)")
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class ListRunsResponse(BaseModel):
    """List runs response schema."""

    items: list[RunResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ListArtifactsResponse(BaseModel):
    """List artifacts response schema."""

    artifacts: list[ArtifactResponse]


class RunManifestResponse(BaseModel):
    """Run manifest response schema.

    Represents the immutable record of dataset version binding, checksum,
    template, parameters, and method versions for a pipeline run.
    """

    run_id: UUID
    dataset_version_id: UUID = Field(..., description="ID of the dataset version bound to this run")
    dataset_checksum: str = Field(..., description="SHA-256 checksum of the dataset version")
    template_id: UUID
    parameters: dict[str, Any]
    method_versions: dict[str, str] = Field(default_factory=dict)
    random_seed: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True
