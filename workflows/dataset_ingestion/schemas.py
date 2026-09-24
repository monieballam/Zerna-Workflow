"""Schemas for dataset ingestion workflow."""

from uuid import UUID

from pydantic import BaseModel


class S3Path(BaseModel):
    """S3 file path reference."""

    bucket: str
    key: str


class DatasetIngestionInput(BaseModel):
    """Input for dataset ingestion workflow."""

    dataset_id: UUID
    organization_id: UUID
    files: list[S3Path]


class DatasetIngestionOutput(BaseModel):
    """Output from dataset ingestion workflow."""

    dataset_version_id: UUID | None
    cell_count: int
    gene_count: int
    validation_errors: list[str]
