"""Evidence scoring and marker index for annotation decisions.

# Feature: gap-analysis-and-verification

Provides:
- Composite confidence scoring from marker expression, reference mapping,
  and ontology alignment
- Searchable marker index across all loaded Knowledge_Packs
"""

from __future__ import annotations

import logging

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class EvidenceScore(ZernaBaseModel):
    """Composite evidence score for a cell type assignment."""

    cell_type: str = Field(description="Cell type label")
    marker_score: float = Field(ge=0.0, le=1.0, description="Marker expression evidence score")
    reference_mapping_score: float = Field(
        ge=0.0, le=1.0, description="Reference mapping evidence score"
    )
    ontology_alignment_score: float = Field(
        ge=0.0, le=1.0, description="Ontology alignment evidence score"
    )
    composite_score: float = Field(
        ge=0.0, le=1.0, description="Weighted composite of all component scores"
    )


class MarkerHit(ZernaBaseModel):
    """A single hit from a marker index search."""

    gene: str = Field(description="Gene symbol")
    cell_types: list[str] = Field(description="Cell types this marker is associated with")
    source: str = Field(description="Knowledge_Pack source identifier")
    version: str = Field(description="Knowledge_Pack version")
    confidence_weight: float = Field(
        ge=0.0, le=1.0, description="Confidence weight for this marker"
    )


class CellTypeAssignment(ZernaBaseModel):
    """Input representing a cell type assignment to be scored."""

    cell_type: str = Field(description="Assigned cell type label")
    marker_expression: dict[str, float] = Field(
        default_factory=dict,
        description="Gene -> expression value for markers relevant to this assignment",
    )
    reference_mapping_confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="Confidence from reference dataset mapping",
    )
    ontology_alignment_confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.0,
        description="Confidence from ontology alignment",
    )


class KnowledgePackMarker(ZernaBaseModel):
    """A marker gene entry within a Knowledge_Pack."""

    gene: str = Field(description="Gene symbol")
    cell_types: list[str] = Field(description="Cell types this gene marks")
    weight: float = Field(ge=0.0, le=1.0, default=1.0, description="Confidence weight")


class KnowledgePack(ZernaBaseModel):
    """A versioned Knowledge_Pack containing marker gene definitions."""

    pack_id: str = Field(description="Pack identifier")
    version: str = Field(description="Pack version")
    markers: list[KnowledgePackMarker] = Field(
        default_factory=list, description="Marker entries in this pack"
    )


class MarkerIndex(ZernaBaseModel):
    """Searchable index of markers across all loaded Knowledge_Packs."""

    entries: dict[str, list[MarkerHit]] = Field(
        default_factory=dict,
        description="gene -> list of MarkerHit from all packs",
    )

    @property
    def all_genes(self) -> set[str]:
        """Return all gene symbols in the index."""
        return set(self.entries.keys())

    def search(self, query: str) -> list[MarkerHit]:
        """Search the index for markers matching the query (case-insensitive).

        Args:
            query: Gene symbol or prefix to search for.

        Returns:
            List of MarkerHit entries matching the query.
        """
        query_lower = query.lower()
        results: list[MarkerHit] = []
        for gene, hits in self.entries.items():
            if gene.lower() == query_lower or gene.lower().startswith(query_lower):
                results.extend(hits)
        return results


# ---------------------------------------------------------------------------
# Evidence scoring (Req 15.1)
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "marker": 0.5,
    "reference_mapping": 0.3,
    "ontology_alignment": 0.2,
}


def _clamp(value: float) -> float:
    """Clamp a value to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def compute_evidence(
    assignment: CellTypeAssignment,
    marker_genes: list[KnowledgePackMarker] | None = None,
    weights: dict[str, float] | None = None,
) -> EvidenceScore:
    """Compute composite evidence score for a cell type assignment.

    The composite score is a weighted combination of:
    - marker_score: derived from marker expression values
    - reference_mapping_score: from reference dataset mapping confidence
    - ontology_alignment_score: from ontology alignment confidence

    All component scores and the composite are clamped to [0.0, 1.0].

    Args:
        assignment: The cell type assignment to score.
        marker_genes: Optional marker gene definitions for computing marker_score.
            If None, marker_score is derived from mean expression values.
        weights: Optional weight dict with keys 'marker', 'reference_mapping',
            'ontology_alignment'. Defaults to 0.5/0.3/0.2.

    Returns:
        EvidenceScore with all component scores and composite.
    """
    w = weights or _DEFAULT_WEIGHTS
    w_marker = w.get("marker", _DEFAULT_WEIGHTS["marker"])
    w_ref = w.get("reference_mapping", _DEFAULT_WEIGHTS["reference_mapping"])
    w_onto = w.get("ontology_alignment", _DEFAULT_WEIGHTS["ontology_alignment"])

    # Compute marker score
    marker_score = _compute_marker_score(assignment, marker_genes)

    # Reference mapping and ontology alignment come directly from the assignment
    ref_score = _clamp(assignment.reference_mapping_confidence)
    onto_score = _clamp(assignment.ontology_alignment_confidence)

    # Composite: weighted average, normalized by total weight
    total_weight = w_marker + w_ref + w_onto
    if total_weight == 0:
        composite = 0.0
    else:
        composite = (
            w_marker * marker_score + w_ref * ref_score + w_onto * onto_score
        ) / total_weight

    composite = _clamp(composite)

    return EvidenceScore(
        cell_type=assignment.cell_type,
        marker_score=marker_score,
        reference_mapping_score=ref_score,
        ontology_alignment_score=onto_score,
        composite_score=composite,
    )


def _compute_marker_score(
    assignment: CellTypeAssignment,
    marker_genes: list[KnowledgePackMarker] | None,
) -> float:
    """Compute marker expression score for an assignment.

    If marker_genes are provided, uses weighted mean of expression for
    markers relevant to the assigned cell type. Otherwise, uses mean
    of all expression values normalized to [0, 1].
    """
    expr = assignment.marker_expression

    if not expr:
        return 0.0

    if marker_genes:
        # Filter markers relevant to this cell type
        relevant: list[tuple[str, float]] = []
        for mg in marker_genes:
            if assignment.cell_type in mg.cell_types:
                relevant.append((mg.gene, mg.weight))

        if relevant:
            total_weight = sum(w for _, w in relevant)
            if total_weight == 0:
                return 0.0
            weighted_sum = 0.0
            for gene, weight in relevant:
                val = expr.get(gene, 0.0)
                normalized = _clamp(val / 100.0) if val >= 0 else 0.0
                weighted_sum += normalized * weight
            return _clamp(weighted_sum / total_weight)

    # Fallback: mean of all expression values, normalized
    raw_mean = sum(expr.values()) / len(expr)
    return _clamp(raw_mean / 100.0)


# ---------------------------------------------------------------------------
# Marker index (Req 15.2, 15.3)
# ---------------------------------------------------------------------------


def build_marker_index(packs: list[KnowledgePack]) -> MarkerIndex:
    """Build a searchable marker index from a list of Knowledge_Packs.

    Every marker from every pack is included in the index. Each entry
    records the gene, associated cell types, source pack, version,
    and confidence weight.

    Args:
        packs: List of KnowledgePack objects to index.

    Returns:
        MarkerIndex with all markers indexed by gene symbol.
    """
    entries: dict[str, list[MarkerHit]] = {}

    for pack in packs:
        for marker in pack.markers:
            hit = MarkerHit(
                gene=marker.gene,
                cell_types=marker.cell_types,
                source=pack.pack_id,
                version=pack.version,
                confidence_weight=_clamp(marker.weight),
            )
            entries.setdefault(marker.gene, []).append(hit)

    return MarkerIndex(entries=entries)


def search_markers(index: MarkerIndex, query: str) -> list[MarkerHit]:
    """Search the marker index for a gene query.

    Args:
        index: The MarkerIndex to search.
        query: Gene symbol or prefix to search for.

    Returns:
        List of MarkerHit entries matching the query.
    """
    return index.search(query)
