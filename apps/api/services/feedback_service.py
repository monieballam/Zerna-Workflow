"""Feedback service for end-user submissions and admin review."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.feedback import Feedback
from apps.api.models.organization import User
from apps.api.models.pipeline import Run
from apps.api.services.audit_service import AuditService


class FeedbackService:
    """Create and query feedback records."""

    def __init__(
        self,
        db: AsyncSession,
        audit_service: AuditService | None = None,
    ) -> None:
        self.db = db
        self.audit = audit_service or AuditService(db)

    async def create_feedback(
        self,
        *,
        org_id: UUID,
        user: User,
        scope: str,
        category: str,
        title: str | None,
        message: str,
        run_id: UUID | None = None,
    ) -> Feedback:
        """Persist one feedback record with run snapshots when applicable."""
        run: Run | None = None
        if scope == "run":
            if run_id is None:
                raise ValueError("run_id is required when scope='run'")

            run_stmt = select(Run).where(
                Run.id == run_id,
                Run.organization_id == org_id,
            )
            run_result = await self.db.execute(run_stmt)
            run = run_result.scalar_one_or_none()
            if run is None:
                raise ValueError(f"Run {run_id} not found")

        feedback = Feedback(
            id=uuid4(),
            organization_id=org_id,
            user_id=user.id,
            user_email_snapshot=user.email,
            scope=scope,
            category=category,
            title=title,
            message=message,
            run_id=run.id if run is not None else None,
            dataset_id_snapshot=run.source_dataset_id if run is not None else None,
            dataset_name_snapshot=run.dataset_name if run is not None else None,
            template_id_snapshot=run.template_id if run is not None else None,
            run_parameters_snapshot=run.parameters if run is not None else None,
            run_status_snapshot=run.status.value if run is not None else None,
        )
        self.db.add(feedback)
        await self.db.flush()

        await self.audit.audit_log(
            org_id=org_id,
            user_id=user.id,
            action_type="feedback.create",
            resource_type="feedback",
            resource_id=feedback.id,
            after_state={
                "scope": scope,
                "category": category,
                "run_id": str(run.id) if run is not None else None,
                "dataset_id": str(run.source_dataset_id)
                if run is not None and run.source_dataset_id
                else None,
            },
        )
        await self.db.commit()
        await self.db.refresh(feedback)
        return feedback

    async def list_feedback(
        self,
        *,
        org_id: UUID,
        user_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        scope: str | None = None,
        category: str | None = None,
    ) -> tuple[list[Feedback], int]:
        """List feedback for one organization."""
        base_stmt = select(Feedback).where(Feedback.organization_id == org_id)
        if user_id is not None:
            base_stmt = base_stmt.where(Feedback.user_id == user_id)
        if scope:
            base_stmt = base_stmt.where(Feedback.scope == scope)
        if category:
            base_stmt = base_stmt.where(Feedback.category == category)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        offset = max(page - 1, 0) * page_size
        stmt = base_stmt.order_by(Feedback.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total
