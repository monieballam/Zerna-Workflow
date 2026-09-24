"""Property-based tests for myeloid calibration and audit.

# Feature: gap-analysis-and-verification, Property 40: Myeloid calibration output structure
# Feature: gap-analysis-and-verification, Property 41: Myeloid audit report structure

**Validates: Requirements 20.1, 20.3**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.annotation.myeloid_audit import (
    audit,
    calibrate,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_MYELOID_SUBTYPES = [
    "Monocyte_Classical",
    "Monocyte_NonClassical",
    "Macrophage_M1",
    "Macrophage_M2",
    "Dendritic_cDC1",
    "Dendritic_cDC2",
    "Dendritic_pDC",
    "Neutrophil",
    "Mast_Cell",
    "Basophil",
]

_subtype_st = st.sampled_from(_MYELOID_SUBTYPES)

_cell_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _myeloid_annotations_st(draw: st.DrawFn) -> dict[str, dict[str, float | str]]:
    """Generate myeloid annotation data: cell_id -> {subtype, confidence}."""
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=20, unique=True))
    annotations: dict[str, dict[str, float | str]] = {}
    for cid in cell_ids:
        annotations[cid] = {
            "subtype": draw(_subtype_st),
            "confidence": draw(_confidence_st),
        }
    return annotations


@st.composite
def _myeloid_audit_inputs_st(draw: st.DrawFn):
    """Generate consistent audit inputs: annotations + reference panel."""
    annotations = draw(_myeloid_annotations_st())
    cell_ids = list(annotations.keys())

    # Reference panel covers all annotated cells (may assign different subtypes)
    reference_panel: dict[str, str] = {}
    for cid in cell_ids:
        reference_panel[cid] = draw(_subtype_st)

    return annotations, reference_panel


# ---------------------------------------------------------------------------
# Property 40: Myeloid calibration output structure
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestMyeloidCalibrationOutputStructure:
    """Property 40: Myeloid calibration output structure.

    For any myeloid annotation result, the calibration output must contain
    per-subtype confidence distributions and threshold recommendations for
    every identified subtype.
    """

    @given(annotations=_myeloid_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_calibration_covers_all_subtypes(
        self,
        annotations: dict[str, dict[str, float | str]],
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 40: Myeloid calibration output structure

        **Validates: Requirements 20.1**
        """
        distributions, thresholds = calibrate(annotations)

        # Collect all subtypes present in annotations
        annotation_subtypes = {cell_data["subtype"] for cell_data in annotations.values()}

        # Every identified subtype must have a confidence distribution
        for subtype in annotation_subtypes:
            assert subtype in distributions, (
                f"Subtype '{subtype}' missing from confidence_distributions"
            )
            assert isinstance(distributions[subtype], list), (
                f"Distribution for '{subtype}' must be a list"
            )
            assert len(distributions[subtype]) > 0, (
                f"Distribution for '{subtype}' must be non-empty"
            )

        # Every identified subtype must have a threshold recommendation
        for subtype in annotation_subtypes:
            assert subtype in thresholds, (
                f"Subtype '{subtype}' missing from threshold_recommendations"
            )
            assert isinstance(thresholds[subtype], float), (
                f"Threshold for '{subtype}' must be a float"
            )

    @given(annotations=_myeloid_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_confidence_values_in_distributions(
        self,
        annotations: dict[str, dict[str, float | str]],
    ) -> None:
        """Confidence distributions must contain the actual confidence values from annotations."""
        distributions, _ = calibrate(annotations)

        # Count expected values per subtype
        expected_counts: dict[str, int] = {}
        for cell_data in annotations.values():
            st_name = cell_data["subtype"]
            expected_counts[st_name] = expected_counts.get(st_name, 0) + 1

        for subtype, expected_count in expected_counts.items():
            assert len(distributions[subtype]) == expected_count, (
                f"Expected {expected_count} values for '{subtype}', "
                f"got {len(distributions[subtype])}"
            )

    @given(annotations=_myeloid_annotations_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_distributions_are_sorted(
        self,
        annotations: dict[str, dict[str, float | str]],
    ) -> None:
        """Confidence distributions must be sorted ascending."""
        distributions, _ = calibrate(annotations)

        for subtype, scores in distributions.items():
            for i in range(len(scores) - 1):
                assert scores[i] <= scores[i + 1], (
                    f"Distribution for '{subtype}' not sorted: {scores[i]} > {scores[i + 1]}"
                )


# ---------------------------------------------------------------------------
# Property 41: Myeloid audit report structure
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestMyeloidAuditReportStructure:
    """Property 41: Myeloid audit report structure.

    For any completed myeloid audit, the report must contain precision,
    recall, and confusion_counts for every subtype.
    """

    @given(data=_myeloid_audit_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_report_contains_metrics_for_all_subtypes(
        self,
        data: tuple,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 41: Myeloid audit report structure

        **Validates: Requirements 20.3**
        """
        annotations, reference_panel = data

        report = audit(annotations, reference_panel)

        # Collect all subtypes from annotations
        annotation_subtypes = {cell_data["subtype"] for cell_data in annotations.values()}

        # Every annotation subtype must have metrics
        for subtype in annotation_subtypes:
            assert subtype in report.subtype_metrics, (
                f"Subtype '{subtype}' missing from subtype_metrics"
            )
            metrics = report.subtype_metrics[subtype]
            assert isinstance(metrics.precision, float), f"precision for '{subtype}' must be float"
            assert isinstance(metrics.recall, float), f"recall for '{subtype}' must be float"
            assert isinstance(metrics.confusion_counts, dict), (
                f"confusion_counts for '{subtype}' must be dict"
            )

    @given(data=_myeloid_audit_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_metrics_bounds(
        self,
        data: tuple,
    ) -> None:
        """Precision, recall, and F1 must be in [0, 1]."""
        annotations, reference_panel = data

        report = audit(annotations, reference_panel)

        for subtype, metrics in report.subtype_metrics.items():
            assert 0.0 <= metrics.precision <= 1.0, (
                f"precision for '{subtype}' out of bounds: {metrics.precision}"
            )
            assert 0.0 <= metrics.recall <= 1.0, (
                f"recall for '{subtype}' out of bounds: {metrics.recall}"
            )
            assert 0.0 <= metrics.f1 <= 1.0, f"f1 for '{subtype}' out of bounds: {metrics.f1}"

    @given(data=_myeloid_audit_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_report_has_distributions_and_thresholds(
        self,
        data: tuple,
    ) -> None:
        """The full audit report must also include distributions and thresholds for all subtypes."""
        annotations, reference_panel = data

        report = audit(annotations, reference_panel)

        annotation_subtypes = {cell_data["subtype"] for cell_data in annotations.values()}

        for subtype in annotation_subtypes:
            assert subtype in report.confidence_distributions, (
                f"Subtype '{subtype}' missing from confidence_distributions"
            )
            assert subtype in report.threshold_recommendations, (
                f"Subtype '{subtype}' missing from threshold_recommendations"
            )

    @given(data=_myeloid_audit_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_confusion_counts_are_non_negative(
        self,
        data: tuple,
    ) -> None:
        """All confusion counts must be non-negative integers."""
        annotations, reference_panel = data

        report = audit(annotations, reference_panel)

        for subtype, metrics in report.subtype_metrics.items():
            for label, count in metrics.confusion_counts.items():
                assert isinstance(count, int), (
                    f"Confusion count for '{subtype}' -> '{label}' must be int"
                )
                assert count >= 0, f"Confusion count for '{subtype}' -> '{label}' must be >= 0"
