"""Stromal resolution: disambiguate broad "Stromal" labels into specific subtypes.

# Feature: gap-analysis-and-verification

Disambiguates broad "Stromal" labels into specific subtypes using marker
evidence and hierarchical rules.  Produces per-cell subtype labels with
confidence scores and the marker evidence used for each assignment.

**Validates: Requirements 21.1, 21.2**
"""

from __future__ import annotations

import logging

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class StromalResolutionResult(ZernaBaseModel):
    """Result of stromal subtype disambiguation."""

    subtype_labels: dict[str, str] = Field(
        description="cell_id -> resolved subtype label",
    )
    confidence_scores: dict[str, float] = Field(
        description="cell_id -> confidence score in [0, 1]",
    )
    marker_evidence: dict[str, dict[str, float]] = Field(
        description="cell_id -> {marker_gene: expression_score}",
    )


# ---------------------------------------------------------------------------
# Marker panels for stromal subtypes
# ---------------------------------------------------------------------------

STROMAL_MARKER_PANELS: dict[str, list[str]] = {
    "Fibroblast": ["DCN", "LUM", "COL1A1", "COL1A2", "COL3A1"],
    "Pericyte": ["RGS5", "PDGFRB", "CSPG4", "MCAM", "DES"],
    "SMC": ["ACTA2", "TAGLN", "MYH11"],
    "Endothelial": ["PECAM1", "VWF", "CDH5", "ERG"],
}

# All known stromal subtypes that can be resolved
STROMAL_SUBTYPES = list(STROMAL_MARKER_PANELS.keys())

# Minimum mean marker score to consider a subtype assignment valid
_MIN_EVIDENCE_THRESHOLD = 0.1


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------


def _compute_marker_scores(
    cell_id: str,
    marker_expressions: dict[str, float],
    panel: list[str],
) -> tuple[float, dict[str, float]]:
    """Compute mean score and per-marker evidence for a single panel.

    Args:
        cell_id: Identifier of the cell.
        marker_expressions: gene -> expression value for this cell.
        panel: List of marker genes for a subtype.

    Returns:
        Tuple of (mean_score, evidence_dict) where evidence_dict maps
        marker gene -> expression value for genes present in the cell.
    """
    evidence: dict[str, float] = {}
    for gene in panel:
        if gene in marker_expressions:
            evidence[gene] = marker_expressions[gene]

    if not evidence:
        return 0.0, evidence

    mean_score = sum(evidence.values()) / len(evidence)
    return mean_score, evidence


def _resolve_single_cell(
    cell_id: str,
    marker_expressions: dict[str, float],
) -> tuple[str, float, dict[str, float]]:
    """Resolve a single stromal cell to a specific subtype.

    Scores each subtype panel against the cell's marker expression and
    picks the best-scoring subtype above the evidence threshold.

    Args:
        cell_id: Cell identifier.
        marker_expressions: gene -> expression value for this cell.

    Returns:
        Tuple of (subtype_label, confidence, marker_evidence).
    """
    best_subtype = "Stromal"
    best_score = 0.0
    best_evidence: dict[str, float] = {}
    all_scores: dict[str, float] = {}

    for subtype, panel in STROMAL_MARKER_PANELS.items():
        score, evidence = _compute_marker_scores(cell_id, marker_expressions, panel)
        all_scores[subtype] = score

        if score > best_score:
            best_score = score
            best_subtype = subtype
            best_evidence = evidence

    # If best score is below threshold, keep as generic "Stromal"
    if best_score < _MIN_EVIDENCE_THRESHOLD:
        # Still collect whatever evidence we have
        combined_evidence: dict[str, float] = {}
        for panel in STROMAL_MARKER_PANELS.values():
            for gene in panel:
                if gene in marker_expressions:
                    combined_evidence[gene] = marker_expressions[gene]
        return "Stromal", 0.0, combined_evidence

    # Compute confidence as ratio of best score to sum of all scores
    total = sum(v for v in all_scores.values() if v > 0)
    confidence = best_score / total if total > 0 else 0.0
    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, confidence))

    return best_subtype, confidence, best_evidence


def resolve(
    adata: dict[str, dict[str, float]],
    stromal_cells: list[str],
) -> StromalResolutionResult:
    """Resolve broad "Stromal" labels into specific subtypes.

    Args:
        adata: Dict-based representation of marker expressions.
            Maps cell_id -> {gene: expression_value}.
        stromal_cells: List of cell IDs that have been labeled "Stromal".

    Returns:
        StromalResolutionResult with per-cell subtype labels, confidence
        scores, and marker evidence.
    """
    subtype_labels: dict[str, str] = {}
    confidence_scores: dict[str, float] = {}
    marker_evidence: dict[str, dict[str, float]] = {}

    for cell_id in stromal_cells:
        expressions = adata.get(cell_id, {})
        subtype, confidence, evidence = _resolve_single_cell(cell_id, expressions)

        subtype_labels[cell_id] = subtype
        confidence_scores[cell_id] = confidence
        marker_evidence[cell_id] = evidence

    return StromalResolutionResult(
        subtype_labels=subtype_labels,
        confidence_scores=confidence_scores,
        marker_evidence=marker_evidence,
    )
