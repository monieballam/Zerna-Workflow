"""Organization, User, and OrganizationUser models."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from zerna_contracts.enums import UserRole
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base

if TYPE_CHECKING:
    from apps.api.models.dataset import Dataset


# Association table for many-to-many relationship between users and organizations
organization_users = Table(
    "organization_users",
    Base.metadata,
    Column("organization_id", ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", Enum(UserRole, name="user_role"), nullable=False, default=UserRole.MEMBER),
    Column("joined_at", DateTime, nullable=False, default=datetime.utcnow),
)


class Organization(Base):
    """Organization model for multi-tenant isolation.

    Each organization has its own storage and compute quotas.
    All resources (datasets, runs, etc.) are scoped to an organization.
    """

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_quota_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    compute_quota_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    users: Mapped[list["User"]] = relationship(
        secondary=organization_users,
        back_populates="organizations",
    )
    datasets: Mapped[list["Dataset"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class User(Base):
    """User model for authentication and authorization.

    Users can belong to multiple organizations with different roles.
    Role-based access control is enforced at the organization level.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    organizations: Mapped[list["Organization"]] = relationship(
        secondary=organization_users,
        back_populates="users",
    )


# Type alias for the association table to enable querying
OrganizationUser = organization_users
