"""Project model for persistent project listings.

Replaces in-memory project listings with database-backed CRUD.
Projects are organization-scoped containers that group datasets, runs, and DAGs.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base, OrganizationMixin

if TYPE_CHECKING:
    pass

# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class Project(Base, OrganizationMixin):
    """Project model for grouping datasets, runs, and DAG definitions.

    Projects are the top-level organizational unit within an organization.
    All project data is persisted to the database (not in-memory).
    """

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONType, nullable=False, default=dict)
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    dag_definitions: Mapped[list["DAGDefinition"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_projects_org_name", "organization_id", "name"),
        Index("ix_projects_created_at", "created_at"),
    )


class DAGDefinition(Base, OrganizationMixin):
    """DAG definition with version history.

    Each DAG definition is immutable once created. Updates create new versions
    linked to the same project and logical DAG name. This provides full
    version history for pipeline DAG definitions.
    """

    __tablename__ = "dag_definitions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    definition: Mapped[dict] = mapped_column(JSONType, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="dag_definitions")

    __table_args__ = (
        Index("ix_dag_defs_project_name", "project_id", "name"),
        Index("ix_dag_defs_project_name_version", "project_id", "name", "version"),
    )
