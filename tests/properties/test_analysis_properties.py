"""Property-based tests for analysis modules.

# Feature: gap-analysis-and-verification, Property 37: Composition proportions sum to one
# Feature: gap-analysis-and-verification, Property 38: DE utility volcano data completeness

**Validates: Requirements 19.1, 19.2**
"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.analysis.composition import CompositionResult, compute_composition
from methods.analysis.de_utils import (
    DEResult,
    RankedGenes,
    VolcanoData,
    rank_genes,
    volcano_data,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_cell_type_st = st.sampled_from(
    [
        "T_cell",
        "B_cell",
        "Macrophage",
        "Fibroblast",
        "Epithelial",
        "NK_cell",
        "Monocyte",
        "Dendritic",
        "Endothelial",
        "Stromal",
    ]
)

_condition_st = st.sampled_from(["control", "treated"])

_cell_id_st = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_gene_name_st = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("Lu",)),
).filter(lambda s: s.strip() != "")


@st.composite
def _obs_data_st(draw: st.DrawFn) -> dict[str, dict[str, str]]:
    """Generate obs dict: {cell_id: {cell_type: ..., condition: ...}}."""
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=30, unique=True))
    obs: dict[str, dict[str, str]] = {}
    for cid in cell_ids:
        obs[cid] = {
            "cell_type": draw(_cell_type_st),
            "condition": draw(_condition_st),
        }
    return obs


@st.composite
def _cell_type_counts_st(draw: st.DrawFn) -> dict[str, int]:
    """Generate non-empty cell type count dict with positive counts."""
    types = draw(st.lists(_cell_type_st, min_size=1, max_size=8, unique=True))
    counts: dict[str, int] = {}
    for ct in types:
        counts[ct] = draw(st.integers(min_value=1, max_value=1000))
    return counts


@st.composite
def _de_results_st(draw: st.DrawFn) -> list[DEResult]:
    """Generate a list of DE results with valid gene names, fold changes, and p-values."""
    genes = draw(st.lists(_gene_name_st, min_size=1, max_size=20, unique=True))
    results: list[DEResult] = []
    for gene in genes:
        lfc = draw(
            st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)
        )
        pval = draw(
            st.floats(min_value=1e-300, max_value=1.0, allow_nan=False, allow_infinity=False)
        )
        results.append(DEResult(gene=gene, log2_fold_change=lfc, p_value=pval))
    return results


# ---------------------------------------------------------------------------
# Property 37: Composition proportions sum to one
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestCompositionProportionsSumToOne:
    """Property 37: Composition proportions sum to one.

    For any set of cell type counts, the computed proportions must sum to 1.0
    (within floating-point tolerance).

    **Validates: Requirements 19.1**
    """

    @given(obs=_obs_data_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_proportions_sum_to_one(self, obs: dict[str, dict[str, str]]) -> None:
        """# Feature: gap-analysis-and-verification, Property 37: Composition proportions sum to one"""
        adata = {"obs": obs}
        result = compute_composition(adata, groupby="cell_type")

        assert isinstance(result, CompositionResult)
        assert len(result.proportions) > 0

        total = sum(result.proportions.values())
        assert abs(total - 1.0) < 1e-9, f"Proportions sum to {total}, expected 1.0"

    @given(obs=_obs_data_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_proportions_non_negative(self, obs: dict[str, dict[str, str]]) -> None:
        """All proportions must be >= 0."""
        adata = {"obs": obs}
        result = compute_composition(adata, groupby="cell_type")

        for ct, prop in result.proportions.items():
            assert prop >= 0.0, f"Proportion for {ct} is negative: {prop}"

    @given(obs=_obs_data_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_cell_types_represented(self, obs: dict[str, dict[str, str]]) -> None:
        """Every cell type present in obs must appear in proportions."""
        adata = {"obs": obs}
        result = compute_composition(adata, groupby="cell_type")

        expected_types = {meta["cell_type"] for meta in obs.values()}
        assert set(result.proportions.keys()) == expected_types

    @given(obs=_obs_data_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_condition_fold_changes_returned(self, obs: dict[str, dict[str, str]]) -> None:
        """When condition is provided, fold_changes and p_values must be populated."""
        adata = {"obs": obs}
        result = compute_composition(adata, groupby="cell_type", condition="condition")

        # With two conditions, fold changes should be computed
        conditions = {meta["condition"] for meta in obs.values()}
        if len(conditions) >= 2:
            assert result.fold_changes is not None
            assert result.p_values is not None


# ---------------------------------------------------------------------------
# Property 38: DE utility volcano data completeness
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestDEUtilityVolcanoDataCompleteness:
    """Property 38: DE utility volcano data completeness.

    For any differential expression result set, the volcano plot data must
    contain log2_fold_change and neg_log10_pvalue for every gene. Gene ranking
    must produce a sorted list.

    **Validates: Requirements 19.2**
    """

    @given(de_results=_de_results_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_volcano_data_contains_all_genes(self, de_results: list[DEResult]) -> None:
        """# Feature: gap-analysis-and-verification, Property 38: DE utility volcano data completeness"""
        result = volcano_data(de_results)

        assert isinstance(result, VolcanoData)
        assert len(result.points) == len(de_results)

        result_genes = {p.gene for p in result.points}
        input_genes = {r.gene for r in de_results}
        assert result_genes == input_genes, (
            f"Missing genes in volcano data: {input_genes - result_genes}"
        )

    @given(de_results=_de_results_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_volcano_points_have_required_fields(self, de_results: list[DEResult]) -> None:
        """Every volcano point must have log2_fold_change and neg_log10_pvalue."""
        result = volcano_data(de_results)

        for point in result.points:
            assert isinstance(point.log2_fold_change, float)
            assert isinstance(point.neg_log10_pvalue, float)
            assert not math.isnan(point.log2_fold_change)
            assert not math.isnan(point.neg_log10_pvalue)
            assert not math.isinf(point.neg_log10_pvalue)
            # neg_log10_pvalue must be non-negative (p in (0, 1])
            assert point.neg_log10_pvalue >= 0.0, (
                f"neg_log10_pvalue must be >= 0, got {point.neg_log10_pvalue}"
            )

    @given(de_results=_de_results_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rank_genes_produces_sorted_list(self, de_results: list[DEResult]) -> None:
        """Gene ranking must produce a list sorted by score in descending order."""
        result = rank_genes(de_results)

        assert isinstance(result, RankedGenes)
        assert len(result.genes) == len(de_results)

        scores = [g.score for g in result.genes]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Genes not sorted descending: score[{i}]={scores[i]} < score[{i + 1}]={scores[i + 1]}"
            )

    @given(de_results=_de_results_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rank_genes_contains_all_genes(self, de_results: list[DEResult]) -> None:
        """Ranked genes must contain every gene from the input."""
        result = rank_genes(de_results)

        result_genes = {g.gene for g in result.genes}
        input_genes = {r.gene for r in de_results}
        assert result_genes == input_genes

    @given(de_results=_de_results_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rank_scores_non_negative(self, de_results: list[DEResult]) -> None:
        """All ranking scores must be non-negative."""
        result = rank_genes(de_results)

        for g in result.genes:
            assert g.score >= 0.0, f"Score for {g.gene} is negative: {g.score}"


# ---------------------------------------------------------------------------
# Additional imports for Property 39
# ---------------------------------------------------------------------------

from uuid import uuid4

from methods.analysis.reporting import (
    AnnotationDebugExport,
    AuditBundle,
    Report,
    generate_annotation_debug_export,
    generate_annotation_summary,
    generate_audit_bundle,
    generate_diagnostic_report,
    generate_qc_report,
)

# ---------------------------------------------------------------------------
# Strategies for Property 39
# ---------------------------------------------------------------------------

_expression_st = st.dictionaries(
    keys=st.sampled_from(["BRCA1", "TP53", "MT-CO1", "MT-ND1", "GAPDH", "ACTB", "CD3D", "CD8A"]),
    values=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=6,
)


@st.composite
def _adata_with_expression_st(draw: st.DrawFn) -> dict:
    """Generate adata dict with obs and X for QC report testing."""
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=20, unique=True))
    obs: dict[str, dict[str, str]] = {}
    x_data: dict[str, dict[str, float]] = {}
    for cid in cell_ids:
        obs[cid] = {
            "cell_type": draw(_cell_type_st),
            "condition": draw(_condition_st),
            "is_doublet": draw(st.booleans()),
        }
        x_data[cid] = draw(_expression_st)
    return {"obs": obs, "X": x_data}


@st.composite
def _adata_with_annotations_st(draw: st.DrawFn) -> dict:
    """Generate adata dict with annotation metadata in obs."""
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=20, unique=True))
    obs: dict[str, dict] = {}
    for cid in cell_ids:
        obs[cid] = {
            "cell_type": draw(_cell_type_st),
            "confidence": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            "markers": draw(
                st.lists(
                    st.sampled_from(["CD3D", "CD8A", "CD4", "MS4A1", "CD14", "EPCAM"]),
                    min_size=0,
                    max_size=3,
                )
            ),
        }
    return {"obs": obs}


@st.composite
def _run_params_st(draw: st.DrawFn) -> dict:
    """Generate run parameters dict for diagnostic report testing."""
    return {
        "parameters": {
            "method": draw(st.sampled_from(["scanpy", "scvi", "harmony"])),
            "n_pcs": draw(st.integers(min_value=5, max_value=50)),
        },
        "step_timings": {
            "qc": draw(st.floats(min_value=0.1, max_value=60.0, allow_nan=False)),
            "clustering": draw(st.floats(min_value=0.1, max_value=300.0, allow_nan=False)),
        },
        "warnings": draw(
            st.lists(
                st.text(
                    min_size=1,
                    max_size=50,
                    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
                ),
                min_size=0,
                max_size=3,
            )
        ),
    }


@st.composite
def _audit_bundle_inputs_st(draw: st.DrawFn) -> dict:
    """Generate inputs for audit bundle generation."""
    return {
        "run_id": uuid4(),
        "qa_metrics": {
            "accuracy": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            "flagged_cells": draw(st.integers(min_value=0, max_value=100)),
        },
        "calibration_data": {
            "threshold": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        },
        "provenance": {
            "method_version": draw(st.sampled_from(["v1.0", "v1.1", "v2.0"])),
            "marker_panel": draw(st.sampled_from(["general_v1", "prostate_v2"])),
        },
    }


# ---------------------------------------------------------------------------
# Property 39: Report and audit bundle completeness
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestReportAndAuditBundleCompleteness:
    """Property 39: Report and audit bundle completeness.

    For any completed run, the QC report must contain all required sections.
    The annotation debug export must contain diagnostic data. The audit bundle
    must contain qa_metrics, calibration_data, and provenance.

    **Validates: Requirements 19.4, 19.5, 19.6**
    """

    # --- QC report completeness ---

    @given(adata=_adata_with_expression_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_qc_report_contains_all_required_sections(self, adata: dict) -> None:
        """# Feature: gap-analysis-and-verification, Property 39: Report and audit bundle completeness"""
        report = generate_qc_report(adata)

        assert isinstance(report, Report)
        assert report.report_type == "qc"

        section_titles = {s.title for s in report.sections}
        required = {
            "cell_counts",
            "gene_counts",
            "mitochondrial_fraction",
            "doublet_summary",
            "quality_filters",
        }
        assert required.issubset(section_titles), (
            f"Missing QC sections: {required - section_titles}"
        )

    @given(adata=_adata_with_expression_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_qc_report_has_generated_at(self, adata: dict) -> None:
        """QC report must have a generated_at timestamp."""
        report = generate_qc_report(adata)
        assert report.generated_at is not None

    # --- Annotation summary completeness ---

    @given(adata=_adata_with_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_annotation_summary_contains_required_sections(self, adata: dict) -> None:
        """Annotation summary must contain label_distribution, confidence_summary, marker_coverage."""
        report = generate_annotation_summary(adata)

        assert isinstance(report, Report)
        assert report.report_type == "annotation_summary"

        section_titles = {s.title for s in report.sections}
        required = {"label_distribution", "confidence_summary", "marker_coverage"}
        assert required.issubset(section_titles), (
            f"Missing annotation summary sections: {required - section_titles}"
        )

    # --- Diagnostic report completeness ---

    @given(run_params=_run_params_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_diagnostic_report_contains_required_sections(self, run_params: dict) -> None:
        """Diagnostic report must contain run_parameters, step_timings, warnings."""
        report = generate_diagnostic_report(run_params)

        assert isinstance(report, Report)
        assert report.report_type == "diagnostic"

        section_titles = {s.title for s in report.sections}
        required = {"run_parameters", "step_timings", "warnings"}
        assert required.issubset(section_titles), (
            f"Missing diagnostic sections: {required - section_titles}"
        )

    # --- Annotation debug export ---

    @given(adata=_adata_with_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_annotation_debug_export_contains_diagnostic_data(self, adata: dict) -> None:
        """Annotation debug export must contain non-empty diagnostic_data."""
        export = generate_annotation_debug_export(adata)

        assert isinstance(export, AnnotationDebugExport)
        assert len(export.diagnostic_data) > 0, "diagnostic_data must not be empty"
        assert export.cell_count == len(adata.get("obs", {}))
        assert export.generated_at is not None

    @given(adata=_adata_with_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_annotation_debug_export_label_distribution_matches_obs(self, adata: dict) -> None:
        """Debug export label distribution must account for all cells."""
        export = generate_annotation_debug_export(adata)

        total_in_dist = sum(export.label_distribution.values())
        assert total_in_dist == export.cell_count

    # --- Audit bundle completeness ---

    @given(inputs=_audit_bundle_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_audit_bundle_contains_required_fields(self, inputs: dict) -> None:
        """Audit bundle must contain qa_metrics, calibration_data, and provenance."""
        bundle = generate_audit_bundle(**inputs)

        assert isinstance(bundle, AuditBundle)
        assert bundle.run_id == inputs["run_id"]
        assert bundle.qa_metrics is not None and len(bundle.qa_metrics) > 0
        assert bundle.calibration_data is not None and len(bundle.calibration_data) > 0
        assert bundle.provenance is not None and len(bundle.provenance) > 0
        assert bundle.generated_at is not None

    @given(inputs=_audit_bundle_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_audit_bundle_preserves_input_data(self, inputs: dict) -> None:
        """Audit bundle must faithfully preserve the input qa_metrics, calibration_data, provenance."""
        bundle = generate_audit_bundle(**inputs)

        assert bundle.qa_metrics == inputs["qa_metrics"]
        assert bundle.calibration_data == inputs["calibration_data"]
        assert bundle.provenance == inputs["provenance"]
