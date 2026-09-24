"""PipelineTemplate, Run, and Artifact models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from zerna_contracts.enums import ArtifactType, RunStatus
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base, OrganizationMixin

if TYPE_CHECKING:
    from apps.api.models.annotation import AnnotationRevision
    from apps.api.models.dataset import DatasetVersion


# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class PipelineTemplate(Base, OrganizationMixin):
    """Reusable pipeline definition with versioning.

    Templates define the DAG structure and parameter schemas.
    Versions are immutable to ensure reproducibility.
    """

    __tablename__ = "pipeline_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONType, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    runs: Mapped[list["Run"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", "version", name="uq_template_org_name_version"),
        Index("ix_pipeline_templates_org_name", "organization_id", "name"),
        Index("ix_pipeline_templates_is_active", "is_active"),
    )


class Run(Base, OrganizationMixin):
    """Execution instance of a PipelineTemplate against a DatasetVersion.

    Tracks status, parameters, software versions, and random seeds for reproducibility.
    """

    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_id_snapshot: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    dataset_version_id_snapshot: Mapped[UUID | None] = mapped_column(nullable=True)
    dataset_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_version_label_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"),
        nullable=False,
        default=RunStatus.QUEUED,
    )
    parameters: Mapped[dict] = mapped_column(JSONType, nullable=False)
    software_versions: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    dataset_version: Mapped["DatasetVersion | None"] = relationship(back_populates="runs")
    template: Mapped["PipelineTemplate"] = relationship(back_populates="runs")
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    annotations: Mapped[list["AnnotationRevision"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_runs_status", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_org_status", "organization_id", "status"),
        Index("ix_runs_org_dataset_version", "organization_id", "dataset_version_id"),
        Index("ix_runs_org_dataset_snapshot", "organization_id", "dataset_id_snapshot"),
        Index("ix_runs_org_status_created", "organization_id", "status", "created_at"),
    )

    @property
    def source_dataset_id(self) -> UUID | None:
        """Return the dataset that originally owned this run."""
        if self.dataset_id_snapshot is not None:
            return self.dataset_id_snapshot
        if self.dataset_version is not None:
            return self.dataset_version.dataset_id
        return None

    @property
    def source_dataset_version_id(self) -> UUID | None:
        """Return the bound dataset-version ID even after source deletion."""
        return self.dataset_version_id or self.dataset_version_id_snapshot

    @property
    def dataset_name(self) -> str | None:
        """Return the source dataset name or its historical snapshot."""
        if self.dataset_name_snapshot:
            return self.dataset_name_snapshot
        dataset_version = self.dataset_version
        if dataset_version is None or dataset_version.dataset is None:
            return None
        return dataset_version.dataset.name

    @property
    def dataset_version_label(self) -> str | None:
        """Return the source dataset version label or its historical snapshot."""
        if self.dataset_version_label_snapshot:
            return self.dataset_version_label_snapshot
        dataset_version = self.dataset_version
        if dataset_version is None:
            return None
        return dataset_version.version

    @property
    def dataset_deleted(self) -> bool:
        """Whether the source dataset/version has been deleted."""
        return self.dataset_version_id is None and self.dataset_version_id_snapshot is not None


class Artifact(Base):
    """Output file or object produced by a Run.

    Artifacts are stored in S3 with metadata in JSONB.
    Types include h5ad files, plots, reports, and analysis results.
    """

    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="artifact_type"),
        nullable=False,
    )
    s3_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="artifacts")

    __table_args__ = (
        Index("ix_artifacts_type", "artifact_type"),
        Index("ix_artifacts_run_type", "run_id", "artifact_type"),
    )
