"""CCI label assignment and ligand-receptor analysis.

# Feature: gap-analysis-and-verification

Assigns interaction-relevant labels based on ligand/receptor expression.
Identifies significant ligand-receptor pairs between cell type pairs.
Postprocesses LR edges: filter, rank, annotate with pathway context.

**Validates: Requirements 18.1, 18.2, 18.3, 18.4**
"""

from __future__ import annotations

import logging
from typing import Any

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default known ligand-receptor pairs with pathway annotations
# ---------------------------------------------------------------------------

_DEFAULT_LR_DB: list[dict[str, Any]] = [
    {"ligand": "TGFB1", "receptor": "TGFBR1", "pathway": "TGFB"},
    {"ligand": "TGFB1", "receptor": "TGFBR2", "pathway": "TGFB"},
    {"ligand": "CXCL12", "receptor": "CXCR4", "pathway": "CXCL/CXCR"},
    {"ligand": "CCL5", "receptor": "CCR5", "pathway": "CCL/CCR"},
    {"ligand": "IFNG", "receptor": "IFNGR1", "pathway": "IFNG/IFNGR"},
    {"ligand": "IL6", "receptor": "IL6R", "pathway": "IL6/IL6R"},
    {"ligand": "TNF", "receptor": "TNFRSF1A", "pathway": "TNF/TNFR"},
    {"ligand": "VEGFA", "receptor": "KDR", "pathway": "VEGF/VEGFR"},
    {"ligand": "CD274", "receptor": "PDCD1", "pathway": "PDCD1/PD-L1"},
    {"ligand": "DLL1", "receptor": "NOTCH1", "pathway": "NOTCH"},
    {"ligand": "EGF", "receptor": "EGFR", "pathway": "EGF/ERBB"},
    {"ligand": "WNT5A", "receptor": "FZD5", "pathway": "WNT"},
    {"ligand": "SPP1", "receptor": "CD44", "pathway": "SPP1/CD44-ITGAV"},
    {"ligand": "GAS6", "receptor": "AXL", "pathway": "GAS6/AXL"},
]

# Default detection threshold for ligand/receptor expression
DEFAULT_DETECTION_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class LRPair(ZernaBaseModel):
    """A ligand-receptor pair with interaction statistics."""

    ligand: str = Field(description="Ligand gene name")
    receptor: str = Field(description="Receptor gene name")
    source_cell_type: str = Field(description="Cell type expressing the ligand")
    target_cell_type: str = Field(description="Cell type expressing the receptor")
    interaction_score: float = Field(description="Interaction strength score")
    p_value: float = Field(ge=0.0, le=1.0, description="Statistical significance")
    pathway_annotations: list[str] = Field(
        default_factory=list,
        description="Pathway context annotations for this LR pair",
    )


class CCIResult(ZernaBaseModel):
    """Result of CCI label assignment."""

    cci_labels: dict[str, str] = Field(description="cell_id -> cci_label mapping")
    lr_pairs: list[LRPair] = Field(
        default_factory=list,
        description="Identified ligand-receptor pairs",
    )


class LRAnalysisResult(ZernaBaseModel):
    """Result of ligand-receptor analysis with postprocessed edges."""

    lr_pairs: list[LRPair] = Field(description="LR pairs sorted by interaction_score descending")
    total_pairs_before_filter: int = Field(default=0, description="Total pairs before filtering")
    total_pairs_after_filter: int = Field(default=0, description="Total pairs after filtering")


# ---------------------------------------------------------------------------
# Pathway database helpers
# ---------------------------------------------------------------------------


def _build_pathway_index(
    lr_db: list[dict[str, Any]] | None = None,
) -> dict[tuple[str, str], list[str]]:
    """Build a lookup from (ligand, receptor) -> list of pathway names."""
    db = lr_db if lr_db is not None else _DEFAULT_LR_DB
    index: dict[tuple[str, str], list[str]] = {}
    for entry in db:
        key = (entry["ligand"], entry["receptor"])
        pathway = entry.get("pathway", "")
        if pathway:
            index.setdefault(key, []).append(pathway)
    return index


def _get_known_ligands(lr_db: list[dict[str, Any]] | None = None) -> set[str]:
    db = lr_db if lr_db is not None else _DEFAULT_LR_DB
    return {e["ligand"] for e in db}


def _get_known_receptors(lr_db: list[dict[str, Any]] | None = None) -> set[str]:
    db = lr_db if lr_db is not None else _DEFAULT_LR_DB
    return {e["receptor"] for e in db}


# ---------------------------------------------------------------------------
# CCI label assignment
# ---------------------------------------------------------------------------


def assign_cci_labels(
    expression_matrix: dict[str, dict[str, float]],
    cell_type_assignments: dict[str, str] | None = None,
    detection_threshold: float = DEFAULT_DETECTION_THRESHOLD,
    lr_db: list[dict[str, Any]] | None = None,
) -> CCIResult:
    """Assign interaction-relevant CCI labels based on ligand/receptor expression.

    For each cell, if any known ligand or receptor gene is expressed above
    ``detection_threshold``, the cell receives an interaction-relevant label
    indicating its communication role (ligand_sender, receptor_receiver, or
    ligand_receptor_both). Cells below threshold for all LR genes receive
    the label "non_interacting".

    Args:
        expression_matrix: cell_id -> {gene: expression_value}.
        cell_type_assignments: Optional cell_id -> cell_type mapping.
        detection_threshold: Minimum expression to consider a gene detected.
        lr_db: Optional custom LR database entries.

    Returns:
        CCIResult with per-cell CCI labels and identified LR pairs.
    """
    known_ligands = _get_known_ligands(lr_db)
    known_receptors = _get_known_receptors(lr_db)

    cci_labels: dict[str, str] = {}

    for cell_id, expr in expression_matrix.items():
        has_ligand = any(expr.get(g, 0.0) > detection_threshold for g in known_ligands)
        has_receptor = any(expr.get(g, 0.0) > detection_threshold for g in known_receptors)

        if has_ligand and has_receptor:
            cci_labels[cell_id] = "ligand_receptor_both"
        elif has_ligand:
            cci_labels[cell_id] = "ligand_sender"
        elif has_receptor:
            cci_labels[cell_id] = "receptor_receiver"
        else:
            cci_labels[cell_id] = "non_interacting"

    # Identify LR pairs between cell types if cell type assignments provided
    lr_pairs: list[LRPair] = []
    if cell_type_assignments:
        lr_pairs = _identify_lr_pairs(
            expression_matrix,
            cell_type_assignments,
            detection_threshold,
            lr_db,
        )

    return CCIResult(cci_labels=cci_labels, lr_pairs=lr_pairs)


# ---------------------------------------------------------------------------
# LR pair identification
# ---------------------------------------------------------------------------


def _identify_lr_pairs(
    expression_matrix: dict[str, dict[str, float]],
    cell_type_assignments: dict[str, str],
    detection_threshold: float,
    lr_db: list[dict[str, Any]] | None = None,
) -> list[LRPair]:
    """Identify significant LR pairs between cell type pairs.

    For each known LR pair in the database, compute the mean expression of
    the ligand in each source cell type and the receptor in each target cell
    type. If both exceed the detection threshold, create an LR pair entry
    with an interaction score (product of mean expressions) and a simple
    p-value proxy based on the proportion of expressing cells.
    """
    db = lr_db if lr_db is not None else _DEFAULT_LR_DB
    pathway_index = _build_pathway_index(lr_db)

    # Group cells by cell type
    ct_cells: dict[str, list[str]] = {}
    for cell_id, ct in cell_type_assignments.items():
        if cell_id in expression_matrix:
            ct_cells.setdefault(ct, []).append(cell_id)

    cell_types = list(ct_cells.keys())
    pairs: list[LRPair] = []

    for entry in db:
        ligand = entry["ligand"]
        receptor = entry["receptor"]

        for source_ct in cell_types:
            # Mean ligand expression in source cell type
            source_cells = ct_cells[source_ct]
            lig_values = [expression_matrix[c].get(ligand, 0.0) for c in source_cells]
            mean_lig = sum(lig_values) / len(lig_values) if lig_values else 0.0
            prop_lig = (
                sum(1 for v in lig_values if v > detection_threshold) / len(lig_values)
                if lig_values
                else 0.0
            )

            if mean_lig <= detection_threshold:
                continue

            for target_ct in cell_types:
                target_cells = ct_cells[target_ct]
                rec_values = [expression_matrix[c].get(receptor, 0.0) for c in target_cells]
                mean_rec = sum(rec_values) / len(rec_values) if rec_values else 0.0
                prop_rec = (
                    sum(1 for v in rec_values if v > detection_threshold) / len(rec_values)
                    if rec_values
                    else 0.0
                )

                if mean_rec <= detection_threshold:
                    continue

                interaction_score = mean_lig * mean_rec
                # Simple p-value proxy: 1 - (proportion expressing in both)
                p_value = max(0.0, min(1.0, 1.0 - (prop_lig * prop_rec)))

                pathway_anns = pathway_index.get((ligand, receptor), [])

                pairs.append(
                    LRPair(
                        ligand=ligand,
                        receptor=receptor,
                        source_cell_type=source_ct,
                        target_cell_type=target_ct,
                        interaction_score=interaction_score,
                        p_value=p_value,
                        pathway_annotations=list(pathway_anns),
                    )
                )

    return pairs


# ---------------------------------------------------------------------------
# LR analysis (full pipeline with postprocessing)
# ---------------------------------------------------------------------------


def analyze_lr(
    expression_matrix: dict[str, dict[str, float]],
    cell_type_assignments: dict[str, str],
    detection_threshold: float = DEFAULT_DETECTION_THRESHOLD,
    lr_db: list[dict[str, Any]] | None = None,
    p_value_cutoff: float = 1.0,
    min_interaction_score: float = 0.0,
) -> LRAnalysisResult:
    """Run full LR analysis with postprocessing: filter, rank, pathway annotate.

    Args:
        expression_matrix: cell_id -> {gene: expression_value}.
        cell_type_assignments: cell_id -> cell_type mapping.
        detection_threshold: Minimum expression to consider a gene detected.
        lr_db: Optional custom LR database entries.
        p_value_cutoff: Maximum p-value to retain (filter step).
        min_interaction_score: Minimum interaction score to retain (filter step).

    Returns:
        LRAnalysisResult with postprocessed, sorted LR pairs.
    """
    raw_pairs = _identify_lr_pairs(
        expression_matrix,
        cell_type_assignments,
        detection_threshold,
        lr_db,
    )
    total_before = len(raw_pairs)

    # --- Postprocessing ---

    # 1. Filter by p-value and interaction score
    filtered = [
        p
        for p in raw_pairs
        if p.p_value <= p_value_cutoff and p.interaction_score >= min_interaction_score
    ]

    # 2. Ensure pathway annotations are present (already done during identification)
    # 3. Rank by interaction score descending
    filtered.sort(key=lambda p: p.interaction_score, reverse=True)

    return LRAnalysisResult(
        lr_pairs=filtered,
        total_pairs_before_filter=total_before,
        total_pairs_after_filter=len(filtered),
    )
