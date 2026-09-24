"""Quota enforcement service for multi-tenancy resource isolation.

Handles storage quota (artifact bytes) and compute quota (concurrent runs)
per organization. Raises QuotaExceededError when limits are reached.
"""

from uuid import UUID

from zerna_contracts.enums import RunStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.organization import Organization
from apps.api.models.pipeline import Artifact, Run


class QuotaExceededError(Exception):
    """Raised when an organization exceeds its resource quota."""

    def __init__(self, quota_type: str, used: int | float, limit: int | float, unit: str = ""):
        self.quota_type = quota_type
        self.used = used
        self.limit = limit
        self.unit = unit
        super().__init__(f"{quota_type} quota exceeded: {used}{unit} used of {limit}{unit} limit")


class QuotaService:
    """Service for checking and enforcing per-organization resource quotas."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Storage quota
    # ------------------------------------------------------------------

    async def get_storage_used_bytes(self, org_id: UUID) -> int:
        """Return total artifact bytes consumed by an organization.

        Sums size_bytes across all Artifacts whose parent Run belongs to org_id.
        NULL size_bytes values are treated as 0.
        """
        stmt = (
            select(func.coalesce(func.sum(Artifact.size_bytes), 0))
            .join(Run, Artifact.run_id == Run.id)
            .where(Run.organization_id == org_id)
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def get_storage_quota_bytes(self, org_id: UUID) -> int:
        """Return the storage quota in bytes for an organization."""
        stmt = select(Organization.storage_quota_gb).where(Organization.id == org_id)
        result = await self.db.execute(stmt)
        quota_gb = result.scalar_one_or_none()
        if quota_gb is None:
            raise ValueError(f"Organization {org_id} not found")
        return quota_gb * 1024 * 1024 * 1024  # GB -> bytes

    async def check_storage_quota(self, org_id: UUID, additional_bytes: int = 0) -> None:
        """Raise QuotaExceededError if adding additional_bytes would exceed the quota.

        Args:
            org_id: Organization to check.
            additional_bytes: Bytes about to be added (e.g. upload size).

        Raises:
            QuotaExceededError: When current + additional > quota.
        """
        used = await self.get_storage_used_bytes(org_id)
        limit = await self.get_storage_quota_bytes(org_id)
        if used + additional_bytes > limit:
            used_gb = round((used + additional_bytes) / (1024**3), 2)
            limit_gb = round(limit / (1024**3), 2)
            raise QuotaExceededError(
                quota_type="storage",
                used=used_gb,
                limit=limit_gb,
                unit=" GB",
            )

    # ------------------------------------------------------------------
    # Compute quota
    # ------------------------------------------------------------------

    async def get_active_run_count(self, org_id: UUID) -> int:
        """Return the number of currently active (QUEUED or RUNNING) runs."""
        stmt = (
            select(func.count())
            .select_from(Run)
            .where(
                Run.organization_id == org_id,
                Run.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one())

    async def get_compute_quota(self, org_id: UUID) -> int:
        """Return the maximum concurrent runs allowed for an organization."""
        stmt = select(Organization.compute_quota_runs).where(Organization.id == org_id)
        result = await self.db.execute(stmt)
        quota = result.scalar_one_or_none()
        if quota is None:
            raise ValueError(f"Organization {org_id} not found")
        return int(quota)

    async def check_compute_quota(self, org_id: UUID) -> None:
        """Raise QuotaExceededError if the org has reached its concurrent run limit.

        Raises:
            QuotaExceededError: When active runs >= compute_quota_runs.
        """
        active = await self.get_active_run_count(org_id)
        limit = await self.get_compute_quota(org_id)
        if active >= limit:
            raise QuotaExceededError(
                quota_type="compute",
                used=active,
                limit=limit,
                unit=" concurrent runs",
            )

    # ------------------------------------------------------------------
    # Quota usage summary
    # ------------------------------------------------------------------

    async def get_quota_usage(self, org_id: UUID) -> dict:
        """Return a summary of quota usage for an organization.

        Returns:
            Dict with storage and compute usage/limit information.
        """
        storage_used = await self.get_storage_used_bytes(org_id)
        storage_limit = await self.get_storage_quota_bytes(org_id)
        active_runs = await self.get_active_run_count(org_id)
        compute_limit = await self.get_compute_quota(org_id)

        return {
            "storage": {
                "used_bytes": storage_used,
                "limit_bytes": storage_limit,
                "used_gb": round(storage_used / (1024**3), 4),
                "limit_gb": round(storage_limit / (1024**3), 4),
                "utilization_pct": round(storage_used / storage_limit * 100, 2)
                if storage_limit
                else 0,
            },
            "compute": {
                "active_runs": active_runs,
                "limit_runs": compute_limit,
                "utilization_pct": round(active_runs / compute_limit * 100, 2)
                if compute_limit
                else 0,
            },
        }
