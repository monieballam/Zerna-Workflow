"""AuditService for immutable audit event logging.

Records all data mutations with before/after state for compliance and reproducibility.

Requirements: 15.1, 15.2, 15.3, 15.4
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.audit import AuditEvent


class AuditService:
    """Service for creating and querying immutable audit events.

    AuditEvent records are write-only — no update or delete methods are provided.
    This enforces immutability at the application layer (Requirement 15.5).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def audit_log(
        self,
        org_id: UUID,
        user_id: UUID,
        action_type: str,
        resource_type: str,
        resource_id: UUID,
        before_state: dict | None = None,
        after_state: dict | None = None,
    ) -> AuditEvent:
        """Record an immutable audit event.

        Action types follow the "resource.action" convention, e.g.:
          - "dataset.create", "dataset.update", "dataset.delete"
          - "run.create", "run.cancel", "run.complete"
          - "annotation.create", "annotation.edit", "annotation.approve"
          - "auth.login.success", "auth.login.failure"

        Args:
            org_id: Organization ID for tenant scoping.
            user_id: ID of the user performing the action.
            action_type: Dot-separated action identifier.
            resource_type: Type of the affected resource (e.g. "dataset", "run").
            resource_id: ID of the affected resource.
            before_state: Snapshot of resource state before the mutation (None for creates).
            after_state: Snapshot of resource state after the mutation (None for deletes).

        Returns:
            The persisted AuditEvent.
        """
        event = AuditEvent(
            id=uuid4(),
            organization_id=org_id,
            user_id=user_id,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            timestamp=datetime.utcnow(),
        )
        self.db.add(event)
        await self.db.flush()  # persist within the caller's transaction
        return event

    async def list_events(
        self,
        org_id: UUID,
        user_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        """Query audit events with optional filters and pagination.

        Args:
            org_id: Organization ID (required — all queries are org-scoped).
            user_id: Filter by the user who performed the action.
            resource_type: Filter by resource type (e.g. "dataset").
            resource_id: Filter by specific resource ID.
            start_date: Include events at or after this timestamp.
            end_date: Include events at or before this timestamp.
            page: 1-indexed page number.
            page_size: Number of events per page (max 200).

        Returns:
            Tuple of (events list, total count).
        """
        page_size = min(page_size, 200)

        stmt = select(AuditEvent).where(AuditEvent.organization_id == org_id)

        if user_id is not None:
            stmt = stmt.where(AuditEvent.user_id == user_id)
        if resource_type is not None:
            stmt = stmt.where(AuditEvent.resource_type == resource_type)
        if resource_id is not None:
            stmt = stmt.where(AuditEvent.resource_id == resource_id)
        if start_date is not None:
            stmt = stmt.where(AuditEvent.timestamp >= start_date)
        if end_date is not None:
            stmt = stmt.where(AuditEvent.timestamp <= end_date)

        # Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Paginated results, newest first
        offset = (page - 1) * page_size
        page_stmt = stmt.order_by(AuditEvent.timestamp.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(page_stmt)
        events = list(result.scalars().all())

        return events, total
