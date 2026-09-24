"""AnnotationRevision and KnowledgePack models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from zerna_contracts.enums import KnowledgePackType
from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base

if TYPE_CHECKING:
    from apps.api.models.pipeline import Run


# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class AnnotationRevision(Base):
    """Versioned cell type annotation with confidence scores and provenance.

    Each revision is immutable. Manual edits create new revisions.
    Annotations are hierarchical (tissue → lineage → cell_type).
    """

    __tablename__ = "annotation_revisions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    annotations: Mapped[dict] = mapped_column(JSONType, nullable=False)
    knowledge_pack_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_packs.id", ondelete="SET NULL"),
        nullable=True,
    )
    method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="annotations")
    knowledge_pack: Mapped["KnowledgePack | None"] = relationship()

    __table_args__ = (
        UniqueConstraint("run_id", "revision_number", name="uq_annotation_run_revision"),
        Index("ix_annotation_revisions_created_at", "created_at"),
    )


class KnowledgePack(Base):
    """Versioned collection of reference data.

    Types include cell type markers, pathway databases, and ligand-receptor pairs.
    Versions are immutable to ensure reproducibility.
    """

    __tablename__ = "knowledge_packs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    pack_type: Mapped[KnowledgePackType] = mapped_column(
        Enum(KnowledgePackType, name="knowledge_pack_type"),
        nullable=False,
    )
    s3_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_knowledge_pack_name_version"),
        Index("ix_knowledge_packs_type", "pack_type"),
        Index("ix_knowledge_packs_created_at", "created_at"),
        Index("ix_knowledge_packs_type_name", "pack_type", "name"),
    )
