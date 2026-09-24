"""Property-based tests for CCI label assignment and LR analysis.

# Feature: gap-analysis-and-verification, Property 35: CCI label assignment from expression
# Feature: gap-analysis-and-verification, Property 36: LR analysis output completeness and ranking

**Validates: Requirements 18.1, 18.2, 18.3, 18.4**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.annotation.cci_labels import (
    _DEFAULT_LR_DB,
    DEFAULT_DETECTION_THRESHOLD,
    _get_known_ligands,
    _get_known_receptors,
    analyze_lr,
    assign_cci_labels,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_KNOWN_LIGANDS = list(_get_known_ligands())
_KNOWN_RECEPTORS = list(_get_known_receptors())
_ALL_LR_GENES = list(set(_KNOWN_LIGANDS) | set(_KNOWN_RECEPTORS))

_cell_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_cell_type_st = st.sampled_from(["Immune", "Stromal", "Epithelial", "Endothelial", "Fibroblast"])

_expression_st = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# Expression value guaranteed above default threshold
_high_expression_st = st.floats(
    min_value=DEFAULT_DETECTION_THRESHOLD + 0.01,
    max_value=50.0,
    allow_nan=False,
    allow_infinity=False,
)

# Expression value guaranteed below default threshold
_low_expression_st = st.floats(
    min_value=0.0,
    max_value=DEFAULT_DETECTION_THRESHOLD - 0.01,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _expression_matrix_with_lr_genes(draw: st.DrawFn) -> dict[str, dict[str, float]]:
    """Generate expression matrix that includes some known LR genes."""
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=15, unique=True))
    # Include a mix of known LR genes and random genes
    extra_genes = draw(
        st.lists(
            st.text(min_size=1, max_size=8, alphabet=st.characters(whitelist_categories=("Lu",))),
            min_size=0,
            max_size=3,
            unique=True,
        )
    )
    lr_genes = draw(st.lists(st.sampled_from(_ALL_LR_GENES), min_size=1, max_size=6, unique=True))
    all_genes = list(set(lr_genes + extra_genes))

    matrix: dict[str, dict[str, float]] = {}
    for cid in cell_ids:
        expr: dict[str, float] = {}
        for g in all_genes:
            expr[g] = draw(_expression_st)
        matrix[cid] = expr
    return matrix


@st.composite
def _cell_type_assignments_st(draw: st.DrawFn, cell_ids: list[str]) -> dict[str, str]:
    """Generate cell type assignments for given cell IDs."""
    return {cid: draw(_cell_type_st) for cid in cell_ids}


@st.composite
def _cci_inputs_st(draw: st.DrawFn):
    """Generate consistent CCI inputs: expression matrix + cell type assignments."""
    matrix = draw(_expression_matrix_with_lr_genes())
    cell_ids = list(matrix.keys())
    ct_assignments = draw(_cell_type_assignments_st(cell_ids))
    return matrix, ct_assignments


# ---------------------------------------------------------------------------
# Property 35: CCI label assignment from expression
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestCCILabelAssignment:
    """Property 35: CCI label assignment from expression.

    For any cell with ligand or receptor expression above the detection
    threshold, the CCI module must assign an interaction-relevant label.
    """

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cells_above_threshold_get_interaction_label(
        self,
        data: tuple,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 35: CCI label assignment from expression"""
        matrix, ct_assignments = data
        threshold = DEFAULT_DETECTION_THRESHOLD

        result = assign_cci_labels(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
            detection_threshold=threshold,
        )

        known_ligands = _get_known_ligands()
        known_receptors = _get_known_receptors()
        interaction_labels = {"ligand_sender", "receptor_receiver", "ligand_receptor_both"}

        for cell_id, expr in matrix.items():
            has_ligand = any(expr.get(g, 0.0) > threshold for g in known_ligands)
            has_receptor = any(expr.get(g, 0.0) > threshold for g in known_receptors)

            label = result.cci_labels[cell_id]

            if has_ligand or has_receptor:
                assert label in interaction_labels, (
                    f"Cell {cell_id} has ligand={has_ligand} receptor={has_receptor} "
                    f"above threshold but got label '{label}'"
                )

            if has_ligand and has_receptor:
                assert label == "ligand_receptor_both"
            elif has_ligand:
                assert label == "ligand_sender"
            elif has_receptor:
                assert label == "receptor_receiver"
            else:
                assert label == "non_interacting"

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_cells_receive_labels(
        self,
        data: tuple,
    ) -> None:
        """Every cell in the expression matrix must receive a CCI label."""
        matrix, ct_assignments = data

        result = assign_cci_labels(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
        )

        assert set(result.cci_labels.keys()) == set(matrix.keys()), (
            "Every cell must receive a CCI label"
        )

    @given(
        cell_ids=st.lists(_cell_id_st, min_size=1, max_size=10, unique=True),
        ligand=st.sampled_from(_KNOWN_LIGANDS),
        high_val=_high_expression_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cell_with_high_ligand_gets_sender_label(
        self,
        cell_ids: list[str],
        ligand: str,
        high_val: float,
    ) -> None:
        """A cell expressing only a ligand above threshold must be labeled ligand_sender."""
        # Build matrix where cells only express the ligand gene (no receptors)
        known_receptors = _get_known_receptors()
        matrix = {cid: {ligand: high_val} for cid in cell_ids}

        result = assign_cci_labels(expression_matrix=matrix)

        for cid in cell_ids:
            # ligand is above threshold, no receptor genes present
            assert result.cci_labels[cid] in {"ligand_sender", "ligand_receptor_both"}


# ---------------------------------------------------------------------------
# Property 36: LR analysis output completeness and ranking
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestLRAnalysisCompletenessAndRanking:
    """Property 36: LR analysis output completeness and ranking.

    For any ligand-receptor analysis result, every LR pair must include
    interaction_score, p_value, and pathway_annotations. The pairs must be
    sorted by interaction score in descending order after postprocessing.
    """

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_lr_pairs_have_required_fields(
        self,
        data: tuple,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 36: LR analysis output completeness and ranking"""
        matrix, ct_assignments = data

        result = analyze_lr(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
        )

        for pair in result.lr_pairs:
            # interaction_score must be present (float)
            assert isinstance(pair.interaction_score, float), (
                f"interaction_score must be float, got {type(pair.interaction_score)}"
            )
            # p_value must be present and in [0, 1]
            assert isinstance(pair.p_value, float), (
                f"p_value must be float, got {type(pair.p_value)}"
            )
            assert 0.0 <= pair.p_value <= 1.0, f"p_value must be in [0, 1], got {pair.p_value}"
            # pathway_annotations must be a list
            assert isinstance(pair.pathway_annotations, list), (
                f"pathway_annotations must be list, got {type(pair.pathway_annotations)}"
            )
            # ligand and receptor must be non-empty strings
            assert pair.ligand and isinstance(pair.ligand, str)
            assert pair.receptor and isinstance(pair.receptor, str)
            # source and target cell types must be non-empty
            assert pair.source_cell_type and isinstance(pair.source_cell_type, str)
            assert pair.target_cell_type and isinstance(pair.target_cell_type, str)

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_lr_pairs_sorted_by_interaction_score_descending(
        self,
        data: tuple,
    ) -> None:
        """After postprocessing, LR pairs must be sorted by interaction_score descending."""
        matrix, ct_assignments = data

        result = analyze_lr(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
        )

        scores = [p.interaction_score for p in result.lr_pairs]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"LR pairs not sorted descending: score[{i}]={scores[i]} < score[{i + 1}]={scores[i + 1]}"
            )

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_filter_counts_consistent(
        self,
        data: tuple,
    ) -> None:
        """total_pairs_after_filter must equal len(lr_pairs) and <= total_pairs_before_filter."""
        matrix, ct_assignments = data

        result = analyze_lr(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
        )

        assert result.total_pairs_after_filter == len(result.lr_pairs)
        assert result.total_pairs_after_filter <= result.total_pairs_before_filter

    @given(data=_cci_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_pathway_annotations_from_known_db(
        self,
        data: tuple,
    ) -> None:
        """Pathway annotations must come from the known LR database."""
        matrix, ct_assignments = data

        known_pathways = {e["pathway"] for e in _DEFAULT_LR_DB if "pathway" in e}

        result = analyze_lr(
            expression_matrix=matrix,
            cell_type_assignments=ct_assignments,
        )

        for pair in result.lr_pairs:
            for ann in pair.pathway_annotations:
                assert ann in known_pathways, f"Unknown pathway annotation '{ann}' not in known DB"
