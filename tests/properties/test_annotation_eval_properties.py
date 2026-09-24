"""Property-based tests for annotation evaluation and provenance.

# Feature: gap-analysis-and-verification, Property 27: Annotation layer consistency
# Feature: gap-analysis-and-verification, Property 28: Marker provenance tracking completeness

**Validates: Requirements 14.1, 14.3**
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.evaluation import (
    HierarchyDefinition,
    LayerAnnotation,
    evaluate_layers,
    track_provenance,
    validate_provenance_completeness,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_label_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_nonempty_str_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip() != "")


@st.composite
def _hierarchy_st(draw):
    """Strategy for a HierarchyDefinition with valid parent-child mappings."""
    # Generate L1 labels
    n_l1 = draw(st.integers(min_value=1, max_value=4))
    l1_labels: list[str] = []
    used = set()
    for _ in range(n_l1 + 5):
        lbl = draw(_label_st)
        if lbl not in used:
            l1_labels.append(lbl)
            used.add(lbl)
        if len(l1_labels) >= n_l1:
            break
    assume(len(l1_labels) >= 1)

    # Generate L2 children for each L1
    l1_to_l2: dict[str, list[str]] = {}
    all_l2: list[str] = []
    for l1 in l1_labels:
        n_children = draw(st.integers(min_value=1, max_value=3))
        children: list[str] = []
        for _ in range(n_children + 5):
            lbl = draw(_label_st)
            if lbl not in used:
                children.append(lbl)
                used.add(lbl)
            if len(children) >= n_children:
                break
        assume(len(children) >= 1)
        l1_to_l2[l1] = children
        all_l2.extend(children)

    assume(len(all_l2) >= 1)

    # Generate L3 children for each L2
    l2_to_l3: dict[str, list[str]] = {}
    for l2 in all_l2:
        n_children = draw(st.integers(min_value=1, max_value=3))
        children: list[str] = []
        for _ in range(n_children + 5):
            lbl = draw(_label_st)
            if lbl not in used:
                children.append(lbl)
                used.add(lbl)
            if len(children) >= n_children:
                break
        assume(len(children) >= 1)
        l2_to_l3[l2] = children

    return HierarchyDefinition(l1_to_l2=l1_to_l2, l2_to_l3=l2_to_l3)


@st.composite
def _consistent_annotations_st(draw, hierarchy: HierarchyDefinition):
    """Strategy for annotations that are consistent with the hierarchy."""
    n_cells = draw(st.integers(min_value=1, max_value=10))
    annotations: list[LayerAnnotation] = []

    l1_labels = list(hierarchy.l1_to_l2.keys())
    assume(len(l1_labels) >= 1)

    for i in range(n_cells):
        l1 = draw(st.sampled_from(l1_labels))
        l2_options = hierarchy.l1_to_l2[l1]
        assume(len(l2_options) >= 1)
        l2 = draw(st.sampled_from(l2_options))
        l3_options = hierarchy.l2_to_l3.get(l2, [])
        assume(len(l3_options) >= 1)
        l3 = draw(st.sampled_from(l3_options))
        annotations.append(LayerAnnotation(cell_id=f"cell_{i}", l1=l1, l2=l2, l3=l3))

    return annotations


@st.composite
def _marker_provenance_dict_st(draw):
    """Strategy for a valid marker provenance dict."""
    return {
        "gene": draw(_nonempty_str_st),
        "source": draw(_nonempty_str_st),
        "version": draw(st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True)),
        "citation": draw(_nonempty_str_st),
    }


# ---------------------------------------------------------------------------
# Property 27: Annotation layer consistency
# ---------------------------------------------------------------------------


class TestAnnotationLayerConsistency:
    """Property 27: Annotation layer consistency.

    For any set of annotations with L1, L2, and L3 layers, every L3 label
    must be a valid child of its L2 label, and every L2 label must be a
    valid child of its L1 label in the hierarchy.

    # Feature: gap-analysis-and-verification, Property 27: Annotation layer consistency

    **Validates: Requirements 14.1**
    """

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_consistent_annotations_produce_no_violations(self, data: st.DataObject) -> None:
        """Annotations built from valid hierarchy paths must have zero violations.

        **Validates: Requirements 14.1**
        """
        hierarchy = data.draw(_hierarchy_st())
        annotations = data.draw(_consistent_annotations_st(hierarchy))
        assume(len(annotations) >= 1)

        report = evaluate_layers(annotations, hierarchy)

        assert report.total_cells == len(annotations)
        assert report.consistent_cells == len(annotations)
        assert len(report.violations) == 0
        assert report.consistency_rate == 1.0

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_invalid_l2_detected(self, data: st.DataObject) -> None:
        """An L2 label not in the L1's children must produce a violation.

        **Validates: Requirements 14.1**
        """
        hierarchy = data.draw(_hierarchy_st())
        l1_labels = list(hierarchy.l1_to_l2.keys())
        assume(len(l1_labels) >= 1)

        l1 = data.draw(st.sampled_from(l1_labels))
        valid_l2 = hierarchy.l1_to_l2[l1]

        # Generate an L2 label that is NOT in the valid set
        bad_l2 = data.draw(_label_st)
        assume(bad_l2 not in valid_l2)

        # Pick a valid L3 for some L2 (doesn't matter which, we're testing L1->L2)
        all_l2_with_l3 = [l2 for l2 in hierarchy.l2_to_l3 if hierarchy.l2_to_l3[l2]]
        assume(len(all_l2_with_l3) >= 1)
        some_l2 = data.draw(st.sampled_from(all_l2_with_l3))
        l3 = data.draw(st.sampled_from(hierarchy.l2_to_l3[some_l2]))

        ann = LayerAnnotation(cell_id="cell_bad", l1=l1, l2=bad_l2, l3=l3)
        report = evaluate_layers([ann], hierarchy)

        # Must detect at least the L1->L2 violation
        l1_l2_violations = [
            v for v in report.violations if v.parent_layer == "L1" and v.cell_id == "cell_bad"
        ]
        assert len(l1_l2_violations) >= 1
        assert report.consistent_cells == 0

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_invalid_l3_detected(self, data: st.DataObject) -> None:
        """An L3 label not in the L2's children must produce a violation.

        **Validates: Requirements 14.1**
        """
        hierarchy = data.draw(_hierarchy_st())
        l1_labels = list(hierarchy.l1_to_l2.keys())
        assume(len(l1_labels) >= 1)

        l1 = data.draw(st.sampled_from(l1_labels))
        valid_l2 = hierarchy.l1_to_l2[l1]
        assume(len(valid_l2) >= 1)
        l2 = data.draw(st.sampled_from(valid_l2))

        valid_l3 = hierarchy.l2_to_l3.get(l2, [])
        bad_l3 = data.draw(_label_st)
        assume(bad_l3 not in valid_l3)

        ann = LayerAnnotation(cell_id="cell_bad_l3", l1=l1, l2=l2, l3=bad_l3)
        report = evaluate_layers([ann], hierarchy)

        l2_l3_violations = [
            v for v in report.violations if v.parent_layer == "L2" and v.cell_id == "cell_bad_l3"
        ]
        assert len(l2_l3_violations) >= 1

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_consistency_rate_bounds(self, data: st.DataObject) -> None:
        """Consistency rate must always be in [0.0, 1.0].

        **Validates: Requirements 14.1**
        """
        hierarchy = data.draw(_hierarchy_st())
        annotations = data.draw(_consistent_annotations_st(hierarchy))

        report = evaluate_layers(annotations, hierarchy)

        assert 0.0 <= report.consistency_rate <= 1.0
        assert report.consistent_cells <= report.total_cells


# ---------------------------------------------------------------------------
# Property 28: Marker provenance tracking completeness
# ---------------------------------------------------------------------------


class TestMarkerProvenanceTrackingCompleteness:
    """Property 28: Marker provenance tracking completeness.

    For any marker gene used in annotation, the provenance record must
    include source, version, and citation fields.

    # Feature: gap-analysis-and-verification, Property 28: Marker provenance tracking completeness

    **Validates: Requirements 14.3**
    """

    @given(marker_dicts=st.lists(_marker_provenance_dict_st(), min_size=1, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_provenance_records_have_all_required_fields(
        self, marker_dicts: list[dict[str, str]]
    ) -> None:
        """Every provenance record must include source, version, and citation.

        **Validates: Requirements 14.3**
        """
        records = track_provenance(marker_dicts)

        assert len(records) == len(marker_dicts)
        for record in records:
            assert record.source is not None and len(record.source) > 0
            assert record.version is not None and len(record.version) > 0
            assert record.citation is not None and len(record.citation) > 0
            assert record.gene is not None and len(record.gene) > 0

    @given(marker_dicts=st.lists(_marker_provenance_dict_st(), min_size=1, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_provenance_completeness_validation_passes(
        self, marker_dicts: list[dict[str, str]]
    ) -> None:
        """Valid provenance records must pass completeness validation.

        **Validates: Requirements 14.3**
        """
        records = track_provenance(marker_dicts)
        is_complete, errors = validate_provenance_completeness(records)

        assert is_complete is True
        assert len(errors) == 0

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_field_raises_error(self, data: st.DataObject) -> None:
        """A marker dict missing a required field must raise ValueError.

        **Validates: Requirements 14.3**
        """
        full_dict = data.draw(_marker_provenance_dict_st())
        field_to_remove = data.draw(st.sampled_from(["source", "version", "citation"]))
        del full_dict[field_to_remove]

        try:
            track_provenance([full_dict])
            assert False, "Expected ValueError for missing field"
        except ValueError as e:
            assert field_to_remove in str(e)

    @given(marker_dicts=st.lists(_marker_provenance_dict_st(), min_size=1, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_provenance_preserves_gene_identity(self, marker_dicts: list[dict[str, str]]) -> None:
        """Provenance records must preserve the gene name from input.

        **Validates: Requirements 14.3**
        """
        records = track_provenance(marker_dicts)

        for original, record in zip(marker_dicts, records):
            assert record.gene == original["gene"]
            assert record.source == original["source"]
            assert record.version == original["version"]
            assert record.citation == original["citation"]
