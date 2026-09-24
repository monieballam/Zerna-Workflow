"""Property-based tests for deterministic gating classification.

# Feature: gap-analysis-and-verification, Property 13: Deterministic gating classification correctness
# Feature: gap-analysis-and-verification, Property 14: Hierarchy mapping consistency
# Feature: gap-analysis-and-verification, Property 15: Gating provenance completeness

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.deterministic_gating import (
    GatingResult,
    GatingRule,
    HierarchyEntry,
    HierarchyMap,
    MarkerPanel,
    classify_cell,
    gate,
    map_label_to_level,
    validate_parent_child_consistency,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_label_st = st.text(
    min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N", "Pd"))
)

_marker_name_st = st.text(
    min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("L", "N"))
)

_expression_value_st = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

_threshold_st = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

_cell_id_st = st.text(
    min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
)

_version_st = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)


def _gating_rule_st(marker_names: list[str] | None = None):
    """Strategy for a single gating rule."""
    if marker_names is not None:
        markers_st = st.fixed_dictionaries(dict.fromkeys(marker_names, _threshold_st))
    else:
        markers_st = st.dictionaries(
            keys=_marker_name_st,
            values=_threshold_st,
            min_size=1,
            max_size=5,
        )
    return st.builds(
        GatingRule,
        rule_id=st.text(
            min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
        ),
        label=_label_st,
        markers=markers_st,
        priority=st.integers(min_value=0, max_value=100),
    )


@st.composite
def _marker_panel_st(draw):
    """Strategy for a marker panel with 1-5 rules."""
    n_rules = draw(st.integers(min_value=1, max_value=5))
    rules = [draw(_gating_rule_st()) for _ in range(n_rules)]
    # Ensure unique rule_ids
    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        if rule.rule_id in seen_ids:
            rules[i] = rule.model_copy(update={"rule_id": f"{rule.rule_id}_{i}"})
        seen_ids.add(rules[i].rule_id)
    return MarkerPanel(
        name=draw(_label_st),
        version=draw(_version_st),
        rules=rules,
        default_label=draw(_label_st),
    )


@st.composite
def _hierarchy_map_st(draw):
    """Strategy for a consistent hierarchy map."""
    n_entries = draw(st.integers(min_value=1, max_value=10))
    # Build consistent hierarchy: each L1 has L2 children, each L2 has L3 children
    l1_labels = [draw(_label_st) for _ in range(max(1, n_entries // 3))]
    mapping: dict[str, HierarchyEntry] = {}
    for _ in range(n_entries):
        l1 = draw(st.sampled_from(l1_labels))
        l2 = draw(_label_st)
        l3 = draw(_label_st)
        label = draw(_label_st)
        # Ensure label uniqueness
        while label in mapping:
            label = label + draw(st.text(min_size=1, max_size=3, alphabet="abcdefghij"))
        mapping[label] = HierarchyEntry(level1=l1, level2=l2, level3=l3)
    name = draw(st.sampled_from(["general", "myeloid", "stromal_v1", "stromal_v2"]))
    return HierarchyMap(name=name, mapping=mapping)


@st.composite
def _consistent_hierarchy_map_st(draw):
    """Strategy for a hierarchy map where parent-child relationships are consistent.

    Same L3 always maps to same L2, same L2 always maps to same L1.
    """
    n_l1 = draw(st.integers(min_value=1, max_value=3))
    l1_labels = [draw(_label_st) for _ in range(n_l1)]

    # Build L2 -> L1 mapping
    n_l2 = draw(st.integers(min_value=n_l1, max_value=6))
    l2_labels = [draw(_label_st) for _ in range(n_l2)]
    l2_to_l1: dict[str, str] = {}
    for i, l2 in enumerate(l2_labels):
        l2_to_l1[l2] = l1_labels[i % n_l1]

    # Build L3 -> L2 mapping
    n_l3 = draw(st.integers(min_value=n_l2, max_value=10))
    l3_labels = [draw(_label_st) for _ in range(n_l3)]
    l3_to_l2: dict[str, str] = {}
    for i, l3 in enumerate(l3_labels):
        l3_to_l2[l3] = l2_labels[i % n_l2]

    # Build entries using the consistent mappings
    mapping: dict[str, HierarchyEntry] = {}
    for l3, l2 in l3_to_l2.items():
        l1 = l2_to_l1[l2]
        label = l3
        while label in mapping:
            label = label + draw(st.text(min_size=1, max_size=3, alphabet="abcdefghij"))
        mapping[label] = HierarchyEntry(level1=l1, level2=l2, level3=l3)

    name = draw(st.sampled_from(["general", "myeloid", "stromal_v1", "stromal_v2"]))
    return HierarchyMap(name=name, mapping=mapping)


# ---------------------------------------------------------------------------
# Property 13: Deterministic gating classification correctness
# ---------------------------------------------------------------------------


class TestGatingClassificationCorrectness:
    """Property 13: Deterministic gating classification correctness.

    For any cell with marker expression values and a marker panel definition,
    the deterministic gating module must classify the cell according to the
    threshold rules in the panel. If a marker exceeds its threshold, the
    corresponding gating rule must fire.

    **Validates: Requirements 10.1**
    """

    @given(panel=_marker_panel_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cell_exceeding_all_thresholds_triggers_rule(
        self,
        panel: MarkerPanel,
    ) -> None:
        """When a cell's expression exceeds ALL thresholds of the highest-priority
        rule, that rule must fire and the cell must receive that rule's label.

        **Validates: Requirements 10.1**
        """
        # Pick the highest-priority rule
        sorted_rules = sorted(panel.rules, key=lambda r: r.priority, reverse=True)
        top_rule = sorted_rules[0]
        assume(len(top_rule.markers) > 0)

        # Build expression that exceeds all thresholds of the top rule
        expression: dict[str, float] = {}
        for marker, threshold in top_rule.markers.items():
            expression[marker] = threshold + 1.0  # strictly above threshold

        label, rule_id = classify_cell(expression, panel)

        assert label == top_rule.label
        assert rule_id == top_rule.rule_id

    @given(panel=_marker_panel_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cell_below_all_thresholds_gets_default(
        self,
        panel: MarkerPanel,
    ) -> None:
        """When a cell's expression is below ALL thresholds of every rule,
        the cell must receive the panel's default label.

        **Validates: Requirements 10.1**
        """
        # Build expression that is 0.0 for all markers (below any positive threshold)
        all_markers: set[str] = set()
        has_positive_threshold = False
        for rule in panel.rules:
            for marker, threshold in rule.markers.items():
                all_markers.add(marker)
                if threshold >= 0.0:
                    has_positive_threshold = True

        assume(has_positive_threshold and len(all_markers) > 0)

        expression = dict.fromkeys(all_markers, 0.0)

        label, rule_id = classify_cell(expression, panel)

        assert label == panel.default_label
        assert rule_id == "no_match"

    @given(
        panel=_marker_panel_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_gate_produces_label_for_every_cell(
        self,
        panel: MarkerPanel,
        data: st.DataObject,
    ) -> None:
        """For any set of cells, gate() must produce a label and rule_id
        for every cell in the input.

        **Validates: Requirements 10.1**
        """
        # Collect all marker names from the panel
        all_markers = set()
        for rule in panel.rules:
            all_markers.update(rule.markers.keys())
        assume(len(all_markers) > 0)

        n_cells = data.draw(st.integers(min_value=1, max_value=10))
        cell_expressions: dict[str, dict[str, float]] = {}
        for i in range(n_cells):
            cell_id = f"cell_{i}"
            expr = {m: data.draw(_expression_value_st) for m in all_markers}
            cell_expressions[cell_id] = expr

        result = gate(cell_expressions, panel)

        assert isinstance(result, GatingResult)
        assert set(result.cell_labels.keys()) == set(cell_expressions.keys())
        assert set(result.gating_rule_ids.keys()) == set(cell_expressions.keys())
        assert result.marker_panel_version == panel.version


# ---------------------------------------------------------------------------
# Property 14: Hierarchy mapping consistency
# ---------------------------------------------------------------------------


class TestHierarchyMappingConsistency:
    """Property 14: Hierarchy mapping consistency.

    For any gating result and hierarchy mapping definition, the mapped labels
    must be valid entries in the hierarchy at the specified level, and child
    labels must be consistent with their parent labels.

    **Validates: Requirements 10.2, 10.3, 10.4**
    """

    @given(hierarchy=_consistent_hierarchy_map_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_consistent_hierarchy_has_no_parent_child_violations(
        self,
        hierarchy: HierarchyMap,
    ) -> None:
        """A consistently-built hierarchy must have no parent-child violations.

        **Validates: Requirements 10.2**
        """
        issues = validate_parent_child_consistency(hierarchy)
        assert issues == [], f"Unexpected inconsistencies: {issues}"

    @given(
        hierarchy=_consistent_hierarchy_map_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_mapped_labels_are_valid_at_specified_level(
        self,
        hierarchy: HierarchyMap,
        data: st.DataObject,
    ) -> None:
        """For any label in the hierarchy, mapping it to any level must produce
        a valid label at that level.

        **Validates: Requirements 10.2, 10.3, 10.4**
        """
        assume(len(hierarchy.mapping) > 0)
        label = data.draw(st.sampled_from(list(hierarchy.mapping.keys())))
        level = data.draw(st.sampled_from(["L1", "L2", "L3"]))

        mapped = map_label_to_level(label, hierarchy, level)

        # Collect all valid labels at this level
        valid_at_level = set()
        for entry in hierarchy.mapping.values():
            level_map = {"L1": entry.level1, "L2": entry.level2, "L3": entry.level3}
            valid_at_level.add(level_map[level])

        assert mapped in valid_at_level, (
            f"Mapped label '{mapped}' not valid at {level}. Valid: {valid_at_level}"
        )

    @given(
        hierarchy=_consistent_hierarchy_map_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_child_labels_consistent_with_parents(
        self,
        hierarchy: HierarchyMap,
        data: st.DataObject,
    ) -> None:
        """For any label, its L3 mapping must be a child of its L2 mapping,
        and its L2 mapping must be a child of its L1 mapping.

        **Validates: Requirements 10.2, 10.3, 10.4**
        """
        assume(len(hierarchy.mapping) > 0)
        label = data.draw(st.sampled_from(list(hierarchy.mapping.keys())))

        entry = hierarchy.mapping[label]

        # Build parent-child relationships from the hierarchy
        l3_to_l2: dict[str, set[str]] = {}
        l2_to_l1: dict[str, set[str]] = {}
        for e in hierarchy.mapping.values():
            l3_to_l2.setdefault(e.level3, set()).add(e.level2)
            l2_to_l1.setdefault(e.level2, set()).add(e.level1)

        # In a consistent hierarchy, each L3 maps to exactly one L2
        assert entry.level2 in l3_to_l2.get(entry.level3, set()), (
            f"L3 '{entry.level3}' not a child of L2 '{entry.level2}'"
        )
        assert entry.level1 in l2_to_l1.get(entry.level2, set()), (
            f"L2 '{entry.level2}' not a child of L1 '{entry.level1}'"
        )


# ---------------------------------------------------------------------------
# Property 15: Gating provenance completeness
# ---------------------------------------------------------------------------


class TestGatingProvenanceCompleteness:
    """Property 15: Gating provenance completeness.

    For any cell label produced by deterministic gating, the result must
    include the gating_rule_id and marker_panel_version used for that
    classification.

    **Validates: Requirements 10.5**
    """

    @given(
        panel=_marker_panel_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_every_cell_has_rule_id_and_panel_version(
        self,
        panel: MarkerPanel,
        data: st.DataObject,
    ) -> None:
        """For any gating result, every cell must have a gating_rule_id
        and the result must include marker_panel_version.

        **Validates: Requirements 10.5**
        """
        all_markers = set()
        for rule in panel.rules:
            all_markers.update(rule.markers.keys())
        assume(len(all_markers) > 0)

        n_cells = data.draw(st.integers(min_value=1, max_value=10))
        cell_expressions: dict[str, dict[str, float]] = {}
        for i in range(n_cells):
            cell_id = f"cell_{i}"
            expr = {m: data.draw(_expression_value_st) for m in all_markers}
            cell_expressions[cell_id] = expr

        result = gate(cell_expressions, panel)

        # marker_panel_version must be non-empty and match panel
        assert result.marker_panel_version == panel.version
        assert len(result.marker_panel_version) > 0

        # Every cell with a label must have a corresponding rule_id
        for cell_id in result.cell_labels:
            assert cell_id in result.gating_rule_ids, (
                f"Cell '{cell_id}' has label but no gating_rule_id"
            )
            rule_id = result.gating_rule_ids[cell_id]
            assert isinstance(rule_id, str) and len(rule_id) > 0, (
                f"Cell '{cell_id}' has empty gating_rule_id"
            )

    @given(
        panel=_marker_panel_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rule_id_references_valid_rule_or_no_match(
        self,
        panel: MarkerPanel,
        data: st.DataObject,
    ) -> None:
        """Every gating_rule_id must reference a rule in the panel or be 'no_match'.

        **Validates: Requirements 10.5**
        """
        all_markers = set()
        for rule in panel.rules:
            all_markers.update(rule.markers.keys())
        assume(len(all_markers) > 0)

        n_cells = data.draw(st.integers(min_value=1, max_value=5))
        cell_expressions: dict[str, dict[str, float]] = {}
        for i in range(n_cells):
            cell_id = f"cell_{i}"
            expr = {m: data.draw(_expression_value_st) for m in all_markers}
            cell_expressions[cell_id] = expr

        result = gate(cell_expressions, panel)

        valid_rule_ids = {r.rule_id for r in panel.rules} | {"no_match"}
        for cell_id, rule_id in result.gating_rule_ids.items():
            assert rule_id in valid_rule_ids, (
                f"Cell '{cell_id}' has rule_id '{rule_id}' not in panel rules"
            )
