"""Property-based tests for stromal resolution.

# Feature: gap-analysis-and-verification, Property 42: Stromal resolution produces specific subtypes with evidence

**Validates: Requirements 21.1, 21.2**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from methods.annotation.stromal_resolution import (
    _MIN_EVIDENCE_THRESHOLD,
    STROMAL_MARKER_PANELS,
    STROMAL_SUBTYPES,
    StromalResolutionResult,
    resolve,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_cell_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_expression_st = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# All marker genes across all panels
_ALL_MARKERS: list[str] = []
for _panel in STROMAL_MARKER_PANELS.values():
    for _gene in _panel:
        if _gene not in _ALL_MARKERS:
            _ALL_MARKERS.append(_gene)


@st.composite
def _stromal_cell_expressions_with_evidence(draw: st.DrawFn) -> dict[str, dict[str, float]]:
    """Generate cell expression data where cells have sufficient marker evidence.

    Each cell gets expression values for markers from at least one stromal
    subtype panel, with values above the evidence threshold.
    """
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=15, unique=True))
    adata: dict[str, dict[str, float]] = {}

    for cid in cell_ids:
        # Pick a subtype panel to give strong evidence for
        subtype = draw(st.sampled_from(STROMAL_SUBTYPES))
        panel = STROMAL_MARKER_PANELS[subtype]

        expressions: dict[str, float] = {}
        # Give meaningful expression for the chosen panel markers
        for gene in panel:
            # Ensure values are above the threshold so mean will be >= _MIN_EVIDENCE_THRESHOLD
            expressions[gene] = draw(
                st.floats(
                    min_value=_MIN_EVIDENCE_THRESHOLD + 0.01,
                    max_value=10.0,
                    allow_nan=False,
                    allow_infinity=False,
                )
            )

        # Optionally add some noise markers from other panels at lower values
        for other_subtype, other_panel in STROMAL_MARKER_PANELS.items():
            if other_subtype != subtype and draw(st.booleans()):
                for gene in other_panel:
                    if gene not in expressions:
                        expressions[gene] = draw(
                            st.floats(
                                min_value=0.0,
                                max_value=0.5,
                                allow_nan=False,
                                allow_infinity=False,
                            )
                        )

        adata[cid] = expressions

    return adata


# ---------------------------------------------------------------------------
# Property 42: Stromal resolution produces specific subtypes with evidence
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestStromalResolutionProducesSubtypesWithEvidence:
    """Property 42: Stromal resolution produces specific subtypes with evidence.

    For any cell labeled "Stromal" with sufficient marker evidence, the
    resolution module must produce a specific subtype label, a confidence
    score in [0, 1], and non-empty marker evidence.
    """

    @given(adata=_stromal_cell_expressions_with_evidence())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_resolution_produces_specific_subtypes(
        self,
        adata: dict[str, dict[str, float]],
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 42: Stromal resolution produces specific subtypes with evidence

        **Validates: Requirements 21.1, 21.2**

        Cells with sufficient marker evidence must be resolved to a specific
        subtype (not the generic "Stromal" label).
        """
        stromal_cells = list(adata.keys())
        result = resolve(adata, stromal_cells)

        assert isinstance(result, StromalResolutionResult)

        for cell_id in stromal_cells:
            # Must have a subtype label
            assert cell_id in result.subtype_labels, f"Cell '{cell_id}' missing from subtype_labels"
            label = result.subtype_labels[cell_id]
            assert isinstance(label, str) and len(label) > 0, (
                f"Subtype label for '{cell_id}' must be a non-empty string"
            )
            # With sufficient evidence, should resolve to a specific subtype
            assert label in STROMAL_SUBTYPES, (
                f"Cell '{cell_id}' should resolve to a known subtype, got '{label}'"
            )

    @given(adata=_stromal_cell_expressions_with_evidence())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_confidence_scores_in_bounds(
        self,
        adata: dict[str, dict[str, float]],
    ) -> None:
        """Confidence scores must be in [0, 1] for all resolved cells."""
        stromal_cells = list(adata.keys())
        result = resolve(adata, stromal_cells)

        for cell_id in stromal_cells:
            assert cell_id in result.confidence_scores, (
                f"Cell '{cell_id}' missing from confidence_scores"
            )
            score = result.confidence_scores[cell_id]
            assert isinstance(score, float), (
                f"Confidence for '{cell_id}' must be float, got {type(score)}"
            )
            assert 0.0 <= score <= 1.0, f"Confidence for '{cell_id}' out of bounds: {score}"

    @given(adata=_stromal_cell_expressions_with_evidence())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_marker_evidence_non_empty(
        self,
        adata: dict[str, dict[str, float]],
    ) -> None:
        """Resolved cells must have non-empty marker evidence."""
        stromal_cells = list(adata.keys())
        result = resolve(adata, stromal_cells)

        for cell_id in stromal_cells:
            assert cell_id in result.marker_evidence, (
                f"Cell '{cell_id}' missing from marker_evidence"
            )
            evidence = result.marker_evidence[cell_id]
            assert isinstance(evidence, dict), f"Evidence for '{cell_id}' must be a dict"
            assert len(evidence) > 0, f"Evidence for '{cell_id}' must be non-empty"

    @given(adata=_stromal_cell_expressions_with_evidence())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_stromal_cells_covered(
        self,
        adata: dict[str, dict[str, float]],
    ) -> None:
        """Every input stromal cell must appear in all output dictionaries."""
        stromal_cells = list(adata.keys())
        result = resolve(adata, stromal_cells)

        assert set(result.subtype_labels.keys()) == set(stromal_cells), (
            "subtype_labels keys must match input stromal_cells"
        )
        assert set(result.confidence_scores.keys()) == set(stromal_cells), (
            "confidence_scores keys must match input stromal_cells"
        )
        assert set(result.marker_evidence.keys()) == set(stromal_cells), (
            "marker_evidence keys must match input stromal_cells"
        )
