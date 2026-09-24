"""Audit event API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    """Audit event response schema."""

    id: UUID
    organization_id: UUID
    user_id: UUID
    action_type: str
    resource_type: str
    resource_id: UUID
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    timestamp: datetime

    class Config:
        from_attributes = True


class ListAuditEventsResponse(BaseModel):
    """Paginated list of audit events."""

    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
