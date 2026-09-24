"""Schemas for cross-dataset pathway analysis workflow."""

from uuid import UUID

from pydantic import BaseModel


class CrossDatasetPathwayInput(BaseModel):
    """Input for cross-dataset pathway analysis workflow."""

    analysis_id: UUID
    organization_id: UUID
    dataset_ids: list[UUID]
    pathway_database: str = "MSigDB"
    aggregation_method: str = "meta-analysis"
    llm_model: str | None = None  # None means skip LLM interpretation


class PathwayPattern(BaseModel):
    """A pathway pattern identified across multiple datasets."""

    pathway_name: str
    pathway_id: str
    datasets_present: list[str]  # UUID strings
    aggregated_score: float
    p_value: float
    confidence: float


class CrossDatasetPathwayOutput(BaseModel):
    """Output from cross-dataset pathway analysis workflow."""

    analysis_id: UUID
    status: str  # "completed" or "failed"
    patterns: list[PathwayPattern]
    interpretation: str | None = None
    hypotheses: list[str] = []
    llm_model_used: str | None = None
    llm_cost_usd: float | None = None
    error_message: str | None = None
