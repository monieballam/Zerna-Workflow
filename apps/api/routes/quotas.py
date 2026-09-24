"""Quota monitoring API endpoints.

Provides endpoints for querying per-organization quota usage (storage and compute).
Emits OpenTelemetry metrics and logs alerts when organizations approach their limits.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.metrics import record_compute_quota_usage, record_storage_quota_usage
from apps.api.middleware.auth import get_current_user, require_organization_membership
from apps.api.models.organization import User
from apps.api.services.quota_service import QuotaService

router = APIRouter(prefix="/v1/organizations", tags=["quotas"])


class StorageQuotaResponse(BaseModel):
    used_bytes: int
    limit_bytes: int
    used_gb: float
    limit_gb: float
    utilization_pct: float


class ComputeQuotaResponse(BaseModel):
    active_runs: int
    limit_runs: int
    utilization_pct: float


class QuotaUsageResponse(BaseModel):
    organization_id: UUID
    storage: StorageQuotaResponse
    compute: ComputeQuotaResponse


@router.get(
    "/{organization_id}/quota",
    response_model=QuotaUsageResponse,
    summary="Get quota usage for an organization",
)
async def get_quota_usage(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_organization_membership),
) -> QuotaUsageResponse:
    """Return current storage and compute quota usage for an organization.

    Emits OpenTelemetry metrics and logs a warning if usage exceeds 80 % of
    the configured quota.
    """
    quota_service = QuotaService(db)

    try:
        usage = await quota_service.get_quota_usage(organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    storage = usage["storage"]
    compute = usage["compute"]

    # Emit metrics and trigger alerts if approaching limits
    record_storage_quota_usage(
        org_id=str(organization_id),
        used_bytes=storage["used_bytes"],
        limit_bytes=storage["limit_bytes"],
    )
    record_compute_quota_usage(
        org_id=str(organization_id),
        active_runs=compute["active_runs"],
        limit_runs=compute["limit_runs"],
    )

    return QuotaUsageResponse(
        organization_id=organization_id,
        storage=StorageQuotaResponse(**storage),
        compute=ComputeQuotaResponse(**compute),
    )
