"""Annotation and KnowledgePack API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from zerna_contracts.enums import KnowledgePackType
from pydantic import BaseModel, Field

# ── KnowledgePack schemas ──────────────────────────────────────────────────────


class KnowledgePackResponse(BaseModel):
    id: UUID
    name: str
    version: str
    pack_type: KnowledgePackType
    s3_path: str
    schema_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="extra_metadata")
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class CreateKnowledgePackRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=50)
    pack_type: KnowledgePackType
    s3_path: str = Field(..., min_length=1, max_length=1024)
    schema_version: str | None = Field(None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListKnowledgePacksResponse(BaseModel):
    items: list[KnowledgePackResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── AnnotationRevision schemas ─────────────────────────────────────────────────


class AnnotationRevisionResponse(BaseModel):
    id: UUID
    run_id: UUID
    revision_number: int
    annotations: dict[str, Any]
    knowledge_pack_id: UUID | None = None
    method: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_by: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class CreateAnnotationRevisionRequest(BaseModel):
    annotations: dict[str, Any]
    method: str | None = Field(None, max_length=100)
    knowledge_pack_id: UUID | None = None


class EditAnnotationsRequest(BaseModel):
    edits: dict[str, Any] = Field(..., description="Key-value pairs to merge into annotations")


class ListAnnotationRevisionsResponse(BaseModel):
    items: list[AnnotationRevisionResponse]
    total: int
