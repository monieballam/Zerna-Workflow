"""Feedback model for run-scoped and system-scoped user submissions."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base, OrganizationMixin

if TYPE_CHECKING:
    from apps.api.models.organization import User
    from apps.api.models.pipeline import Run


JSONType = JSONB().with_variant(JSON(), "sqlite")


class Feedback(Base, OrganizationMixin):
    """User feedback submitted against a run or against the system overall."""

    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_id_snapshot: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    dataset_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_id_snapshot: Mapped[UUID | None] = mapped_column(nullable=True)
    run_parameters_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    run_status_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    user: Mapped["User | None"] = relationship()
    run: Mapped["Run | None"] = relationship()

    __table_args__ = (
        Index("ix_feedback_org_created_at", "organization_id", "created_at"),
        Index("ix_feedback_org_scope", "organization_id", "scope"),
        Index("ix_feedback_org_run", "organization_id", "run_id"),
    )
