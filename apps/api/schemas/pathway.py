"""Pathway analysis API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PathwayPatternResponse(BaseModel):
    pathway_name: str
    pathway_id: str
    datasets_present: list[str]
    aggregated_score: float
    p_value: float
    confidence: float


class CrossDatasetPathwayRequest(BaseModel):
    dataset_ids: list[UUID] = Field(..., min_length=2, description="At least 2 datasets required")
    pathway_database: str = Field(default="MSigDB", max_length=100)
    aggregation_method: str = Field(default="meta-analysis", max_length=100)


class CrossDatasetPathwayResponse(BaseModel):
    analysis_id: UUID
    organization_id: UUID
    dataset_ids: list[str]
    pathway_database: str
    aggregation_method: str
    status: str
    pathway_patterns: list[PathwayPatternResponse] | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class InterpretPathwayRequest(BaseModel):
    model: str = Field(
        default="gpt-4", description="LLM model: 'gpt-4' or 'claude-3-opus-20240229'"
    )
    context: str | None = Field(None, max_length=1000, description="Optional biological context")


class InterpretPathwayResponse(BaseModel):
    analysis_id: UUID
    interpretation: str
    hypotheses: list[str]
    suggested_experiments: list[str]
    model_used: str
    cost_usd: float
    from_cache: bool


class ListAnalysesResponse(BaseModel):
    items: list[CrossDatasetPathwayResponse]
    total: int
    page: int
    page_size: int
