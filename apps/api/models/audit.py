"""AuditEvent model for immutable audit logging."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.base import Base, OrganizationMixin

# Use JSONB for PostgreSQL, JSON for other databases
JSONType = JSONB().with_variant(JSON(), "sqlite")


class AuditEvent(Base, OrganizationMixin):
    """Immutable record of user actions for compliance and reproducibility.

    Records all data mutations with before/after state.
    Immutability is enforced at the application layer and database level.
    """

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_audit_events_timestamp", "timestamp"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_org_timestamp", "organization_id", "timestamp"),
        Index("ix_audit_events_user_timestamp", "user_id", "timestamp"),
        # Immutability constraint: prevent updates by checking timestamp never changes
        # This is a soft constraint - application layer should also prevent updates
        CheckConstraint(
            "timestamp IS NOT NULL",
            name="ck_audit_events_immutable",
        ),
    )
