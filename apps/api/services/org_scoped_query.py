"""Organization-scoped query helpers for multi-tenant data isolation.

Provides a mixin and utility functions that enforce organization_id filtering
on all SQLAlchemy queries, preventing cross-tenant data leakage.
"""

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

T = TypeVar("T", bound=DeclarativeBase)


class OrgScopedQueryMixin:
    """Mixin for services that operate on organization-scoped resources.

    Provides helper methods that automatically apply organization_id filters
    to all queries, ensuring strict multi-tenant isolation.

    Usage::

        class MyService(OrgScopedQueryMixin):
            def __init__(self, db: AsyncSession, org_id: UUID):
                self.db = db
                self.org_id = org_id

            async def get_item(self, item_id: UUID):
                return await self.get_by_id(MyModel, item_id)
    """

    db: AsyncSession
    org_id: UUID

    async def get_by_id(
        self,
        model: type[T],
        resource_id: UUID,
        *,
        org_id: UUID | None = None,
    ) -> T | None:
        """Fetch a single resource by ID, scoped to the organization.

        Args:
            model: SQLAlchemy model class (must have organization_id column).
            resource_id: Primary key of the resource.
            org_id: Override organization ID (defaults to self.org_id).

        Returns:
            Model instance if found and belongs to the organization, else None.
        """
        effective_org_id = org_id if org_id is not None else self.org_id
        stmt = select(model).where(
            model.id == resource_id,  # type: ignore[attr-defined]
            model.organization_id == effective_org_id,  # type: ignore[attr-defined]
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_resources(
        self,
        model: type[T],
        *filters: Any,
        org_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[T]:
        """List resources scoped to the organization with optional extra filters.

        Args:
            model: SQLAlchemy model class (must have organization_id column).
            *filters: Additional SQLAlchemy filter expressions.
            org_id: Override organization ID (defaults to self.org_id).
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of model instances belonging to the organization.
        """
        effective_org_id = org_id if org_id is not None else self.org_id
        stmt = (
            select(model)
            .where(
                model.organization_id == effective_org_id,  # type: ignore[attr-defined]
                *filters,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def verify_org_membership(self, resource: Any, org_id: UUID | None = None) -> bool:
        """Check that a resource belongs to the expected organization.

        Args:
            resource: Model instance with organization_id attribute.
            org_id: Override organization ID (defaults to self.org_id).

        Returns:
            True if the resource belongs to the organization.
        """
        effective_org_id = org_id if org_id is not None else self.org_id
        return getattr(resource, "organization_id", None) == effective_org_id


def apply_org_filter(stmt: Any, model: type[T], org_id: UUID) -> Any:
    """Apply an organization_id filter to an existing SQLAlchemy statement.

    Convenience function for use outside of service classes.

    Args:
        stmt: Existing SQLAlchemy select statement.
        model: Model class with organization_id column.
        org_id: Organization ID to filter by.

    Returns:
        Statement with organization filter applied.
    """
    return stmt.where(model.organization_id == org_id)  # type: ignore[attr-defined]
