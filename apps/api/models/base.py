"""Base SQLAlchemy models and mixins for Zerna platform."""

from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class OrganizationMixin:
    """Mixin for models that are scoped to an organization.

    Provides organization_id foreign key for multi-tenant data isolation.
    All queries should filter by organization_id to enforce tenant boundaries.
    """

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
