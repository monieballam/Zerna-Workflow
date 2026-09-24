"""CrossDatasetAnalysis and PathwayPattern models."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.base import Base, OrganizationMixin

# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CrossDatasetAnalysis(Base, OrganizationMixin):
    """Cross-dataset pathway analysis aggregating patterns across multiple datasets.

    Supports privacy-preserving aggregation (no raw data sharing between orgs).
    LLM interpretation is stored separately once generated.
    """

    __tablename__ = "cross_dataset_analyses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_ids: Mapped[list] = mapped_column(JSONType, nullable=False)  # list[UUID str]
    pathway_database: Mapped[str] = mapped_column(String(100), nullable=False, default="MSigDB")
    aggregation_method: Mapped[str] = mapped_column(
        String(100), nullable=False, default="meta-analysis"
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    pathway_patterns: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    llm_interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_hypotheses: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    llm_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_cross_dataset_analyses_org_id", "organization_id"),
        Index("ix_cross_dataset_analyses_status", "status"),
        Index("ix_cross_dataset_analyses_created_at", "created_at"),
    )
