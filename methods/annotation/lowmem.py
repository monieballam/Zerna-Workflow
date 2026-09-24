"""Low-memory annotation mode with chunked batch processing.

# Feature: gap-analysis-and-verification

Processes annotation in chunked batches for resource-constrained environments.
Produces results equivalent to processing the full dataset at once.

**Validates: Requirements 17.1**
"""

from __future__ import annotations

import logging

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

from methods.annotation.scoring import MarkerGene, score

logger = logging.getLogger(__name__)


class AnnotationResult(ZernaBaseModel):
    """Result of annotation (chunked or full)."""

    per_cluster_scores: dict[str, float] = Field(
        description="cluster_id -> confidence score in [0.0, 1.0]"
    )
    per_cell_scores: dict[str, float] = Field(
        description="cell_id -> confidence score in [0.0, 1.0]"
    )
    chunk_count: int = Field(default=1, description="Number of chunks processed")


def _clamp(value: float) -> float:
    """Clamp a value to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def annotate_chunked(
    expression_matrix: dict[str, dict[str, float]],
    markers: list[MarkerGene],
    chunk_size: int,
    cluster_assignments: dict[str, str] | None = None,
) -> AnnotationResult:
    """Process annotation in chunked batches for low-memory environments.

    Splits the expression matrix into chunks of ``chunk_size`` cells, scores
    each chunk independently, then merges results.  The merged result is
    equivalent to scoring the full dataset at once because per-cell scores
    are independent and per-cluster scores are recomputed from all cells.

    Args:
        expression_matrix: cell_id -> {gene: expression_value} mapping.
        markers: List of marker genes with cell type associations and weights.
        chunk_size: Maximum number of cells per chunk.  Must be >= 1.
        cluster_assignments: Optional cell_id -> cluster_id mapping.

    Returns:
        AnnotationResult with per-cluster and per-cell scores.

    Raises:
        ValueError: If chunk_size < 1.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    if not expression_matrix:
        return AnnotationResult(
            per_cluster_scores={},
            per_cell_scores={},
            chunk_count=0,
        )

    cell_ids = list(expression_matrix.keys())
    all_per_cell: dict[str, float] = {}
    chunk_count = 0

    for start in range(0, len(cell_ids), chunk_size):
        chunk_ids = cell_ids[start : start + chunk_size]
        chunk_expr = {cid: expression_matrix[cid] for cid in chunk_ids}

        # Build chunk-local cluster assignments
        chunk_clusters: dict[str, str] | None = None
        if cluster_assignments is not None:
            chunk_clusters = {
                cid: cluster_assignments[cid] for cid in chunk_ids if cid in cluster_assignments
            }

        chunk_result = score(chunk_expr, markers, chunk_clusters)
        all_per_cell.update(chunk_result.per_cell_scores)
        chunk_count += 1

    # Recompute per-cluster scores from all collected per-cell scores
    effective_clusters = cluster_assignments or {cid: cid for cid in cell_ids}
    cluster_cells: dict[str, list[float]] = {}
    for cell_id, cell_score in all_per_cell.items():
        cluster_id = effective_clusters.get(cell_id, cell_id)
        cluster_cells.setdefault(cluster_id, []).append(cell_score)

    per_cluster_scores: dict[str, float] = {}
    for cluster_id, scores_list in cluster_cells.items():
        per_cluster_scores[cluster_id] = _clamp(sum(scores_list) / len(scores_list))

    return AnnotationResult(
        per_cluster_scores=per_cluster_scores,
        per_cell_scores=all_per_cell,
        chunk_count=chunk_count,
    )
