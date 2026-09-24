"""Dataset and DatasetVersion models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base, OrganizationMixin

if TYPE_CHECKING:
    from apps.api.models.organization import Organization
    from apps.api.models.pipeline import Run


# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class Dataset(Base, OrganizationMixin):
    """Dataset model representing a collection of single-cell data files.

    Datasets are versioned - each upload creates a new DatasetVersion.
    Metadata is stored as JSONB for flexible custom fields.
    """

    __tablename__ = "datasets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="datasets")
    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_datasets_created_at", "created_at"),
        Index("ix_datasets_org_created_at", "organization_id", "created_at"),
        Index("ix_datasets_org_name", "organization_id", "name"),
    )


class DatasetVersion(Base):
    """Immutable snapshot of a Dataset with specific file contents.

    Each version has its own S3 path and metadata (cell count, gene count).
    Versions are immutable to ensure reproducibility.

    Lineage fields track the origin of each version:
    - checksum: SHA-256 digest of the source file(s)
    - source_type: how the version was created (upload, s3_uri, merge)
    - parent_version_ids: UUIDs of parent versions (non-empty for merges)
    - schema_summary: column names, dtypes, shape of the dataset
    - uploaded_by: user who created this version
    """

    __tablename__ = "dataset_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gene_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # --- Lineage fields (added for dataset versioning) ---
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # upload | s3_uri | merge
    parent_version_ids: Mapped[dict | None] = mapped_column(
        "parent_version_ids", JSONType, nullable=True, default=None
    )  # stored as JSON list of UUID strings
    schema_summary: Mapped[dict | None] = mapped_column(
        "schema_summary", JSONType, nullable=True, default=None
    )
    uploaded_by: Mapped[UUID | None] = mapped_column(nullable=True)

    # Relationships
    dataset: Mapped["Dataset"] = relationship(back_populates="versions")
    runs: Mapped[list["Run"]] = relationship(back_populates="dataset_version")

    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),)
