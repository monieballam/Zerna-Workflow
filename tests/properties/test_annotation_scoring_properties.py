"""Property-based tests for annotation scoring utilities.

# Feature: gap-analysis-and-verification, Property 23: Annotation confidence score bounds
# Feature: gap-analysis-and-verification, Property 24: Marker pack and taxonomy loader round-trip
# Feature: gap-analysis-and-verification, Property 25: Subtype refinement hierarchy consistency
# Feature: gap-analysis-and-verification, Property 26: Annotation robustness under perturbation

**Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.scoring import (
    MarkerGene,
    MarkerPanel,
    Taxonomy,
    TaxonomyNode,
    assign_subtypes,
    evaluate_robustness,
    load_markers,
    load_taxonomy,
    score,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_gene_st = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_cell_type_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip() != "")

_cell_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)

_expression_value_st = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

_weight_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _marker_gene_st(draw):
    """Strategy for a single MarkerGene."""
    gene = draw(_gene_st)
    n_types = draw(st.integers(min_value=1, max_value=3))
    cell_types = [draw(_cell_type_st) for _ in range(n_types)]
    weight = draw(_weight_st)
    return MarkerGene(gene=gene, cell_types=cell_types, weight=weight)


@st.composite
def _marker_list_st(draw, min_size=1, max_size=10):
    """Strategy for a list of MarkerGene entries."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(_marker_gene_st()) for _ in range(n)]


@st.composite
def _expression_matrix_st(draw, min_cells=1, max_cells=10, min_genes=1, max_genes=5):
    """Strategy for an expression matrix: cell_id -> {gene: value}."""
    n_cells = draw(st.integers(min_value=min_cells, max_value=max_cells))
    n_genes = draw(st.integers(min_value=min_genes, max_value=max_genes))
    genes = [draw(_gene_st) for _ in range(n_genes)]

    matrix: dict[str, dict[str, float]] = {}
    for i in range(n_cells):
        cell_id = f"cell_{i}"
        expr = {g: draw(_expression_value_st) for g in genes}
        matrix[cell_id] = expr
    return matrix


@st.composite
def _marker_panel_st(draw):
    """Strategy for a MarkerPanel."""
    pack_id = draw(st.text(min_size=1, max_size=15, alphabet="abcdefghij0123456789"))
    version = draw(st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True))
    markers = draw(_marker_list_st(min_size=1, max_size=8))
    return MarkerPanel(pack_id=pack_id, version=version, markers=markers)


@st.composite
def _taxonomy_node_st(draw, depth=0, max_depth=2):
    """Strategy for a TaxonomyNode with bounded depth."""
    label = draw(_cell_type_st)
    if depth >= max_depth:
        return TaxonomyNode(label=label, children=[])
    n_children = draw(st.integers(min_value=0, max_value=3))
    children = []
    used_labels = {label}
    for _ in range(n_children):
        child = draw(_taxonomy_node_st(depth=depth + 1, max_depth=max_depth))
        # Ensure unique labels within siblings
        if child.label not in used_labels:
            children.append(child)
            used_labels.add(child.label)
    return TaxonomyNode(label=label, children=children)


@st.composite
def _taxonomy_st(draw):
    """Strategy for a Taxonomy."""
    name = draw(st.text(min_size=1, max_size=15, alphabet="abcdefghij"))
    version = draw(st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True))
    root = draw(_taxonomy_node_st(depth=0, max_depth=2))
    return Taxonomy(name=name, version=version, root=root)


@st.composite
def _taxonomy_with_children_st(draw):
    """Strategy for a Taxonomy guaranteed to have at least one parent with children."""
    parent_label = draw(_cell_type_st)
    n_children = draw(st.integers(min_value=2, max_value=5))
    child_labels: list[str] = []
    used = {parent_label}
    for _ in range(n_children + 3):
        cl = draw(_cell_type_st)
        if cl not in used:
            child_labels.append(cl)
            used.add(cl)
        if len(child_labels) >= n_children:
            break
    assume(len(child_labels) >= 2)

    children = [TaxonomyNode(label=cl, children=[]) for cl in child_labels]
    root = TaxonomyNode(label=parent_label, children=children)

    name = draw(st.text(min_size=1, max_size=10, alphabet="abcdefghij"))
    version = draw(st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True))
    return Taxonomy(name=name, version=version, root=root)


# ---------------------------------------------------------------------------
# Property 23: Annotation confidence score bounds
# ---------------------------------------------------------------------------


class TestAnnotationConfidenceScoreBounds:
    """Property 23: Annotation confidence score bounds.

    For any set of marker expressions, the annotation scoring utilities must
    produce confidence scores in the range [0.0, 1.0] for both per-cluster
    and per-cell scores.

    # Feature: gap-analysis-and-verification, Property 23: Annotation confidence score bounds

    **Validates: Requirements 13.1**
    """

    @given(
        expression_matrix=_expression_matrix_st(),
        markers=_marker_list_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_per_cell_scores_in_bounds(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
    ) -> None:
        """Per-cell confidence scores must be in [0.0, 1.0].

        **Validates: Requirements 13.1**
        """
        result = score(expression_matrix, markers)

        for cell_id, cell_score in result.per_cell_scores.items():
            assert 0.0 <= cell_score <= 1.0, (
                f"Per-cell score for '{cell_id}' is {cell_score}, expected in [0.0, 1.0]"
            )

    @given(
        expression_matrix=_expression_matrix_st(),
        markers=_marker_list_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_per_cluster_scores_in_bounds(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
    ) -> None:
        """Per-cluster confidence scores must be in [0.0, 1.0].

        **Validates: Requirements 13.1**
        """
        result = score(expression_matrix, markers)

        for cluster_id, cluster_score in result.per_cluster_scores.items():
            assert 0.0 <= cluster_score <= 1.0, (
                f"Per-cluster score for '{cluster_id}' is {cluster_score}, expected in [0.0, 1.0]"
            )

    @given(
        expression_matrix=_expression_matrix_st(),
        markers=_marker_list_st(),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_scores_in_bounds_with_cluster_assignments(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
        data: st.DataObject,
    ) -> None:
        """Scores remain in [0.0, 1.0] even with explicit cluster assignments.

        **Validates: Requirements 13.1**
        """
        cell_ids = list(expression_matrix.keys())
        assume(len(cell_ids) > 0)

        n_clusters = data.draw(st.integers(min_value=1, max_value=max(1, len(cell_ids))))
        cluster_ids = [f"cluster_{i}" for i in range(n_clusters)]
        cluster_assignments = {cid: data.draw(st.sampled_from(cluster_ids)) for cid in cell_ids}

        result = score(expression_matrix, markers, cluster_assignments)

        for cell_id, cell_score in result.per_cell_scores.items():
            assert 0.0 <= cell_score <= 1.0, f"Per-cell score for '{cell_id}' is {cell_score}"
        for cluster_id, cluster_score in result.per_cluster_scores.items():
            assert 0.0 <= cluster_score <= 1.0, (
                f"Per-cluster score for '{cluster_id}' is {cluster_score}"
            )


# ---------------------------------------------------------------------------
# Property 24: Marker pack and taxonomy loader round-trip
# ---------------------------------------------------------------------------


class TestMarkerPackTaxonomyRoundTrip:
    """Property 24: Marker pack and taxonomy loader round-trip.

    For any valid Knowledge_Pack bundle, loading markers and then serializing
    them back must produce an equivalent marker panel. Similarly, loading a
    taxonomy and serializing it must preserve the hierarchy structure.

    # Feature: gap-analysis-and-verification, Property 24: Marker pack and taxonomy loader round-trip

    **Validates: Requirements 13.2, 13.3**
    """

    @given(panel=_marker_panel_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_marker_panel_round_trip(self, panel: MarkerPanel) -> None:
        """Serializing and deserializing a MarkerPanel must produce an equivalent panel.

        **Validates: Requirements 13.2**
        """
        serialized = panel.to_dict()
        restored = MarkerPanel.from_dict(serialized)

        assert restored.pack_id == panel.pack_id
        assert restored.version == panel.version
        assert len(restored.markers) == len(panel.markers)
        for orig, rest in zip(panel.markers, restored.markers):
            assert rest.gene == orig.gene
            assert rest.cell_types == orig.cell_types
            assert rest.weight == pytest.approx(orig.weight, abs=1e-9)

    @given(panel=_marker_panel_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_marker_load_from_dict_round_trip(self, panel: MarkerPanel) -> None:
        """Loading markers from a dict and serializing back must be equivalent.

        **Validates: Requirements 13.2**
        """
        source_dict = {
            "version": panel.version,
            "markers": [
                {
                    "gene": m.gene,
                    "cell_types": m.cell_types,
                    "weight": m.weight,
                }
                for m in panel.markers
            ],
        }
        loaded = load_markers(panel.pack_id, source=source_dict)

        assert loaded.pack_id == panel.pack_id
        assert loaded.version == panel.version
        assert len(loaded.markers) == len(panel.markers)

    @given(taxonomy=_taxonomy_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_taxonomy_round_trip(self, taxonomy: Taxonomy) -> None:
        """Serializing and deserializing a Taxonomy must preserve the hierarchy.

        **Validates: Requirements 13.3**
        """
        serialized = taxonomy.to_dict()
        restored = Taxonomy.from_dict(serialized)

        assert restored.name == taxonomy.name
        assert restored.version == taxonomy.version
        assert restored.get_all_labels() == taxonomy.get_all_labels()

        # Verify hierarchy structure is preserved
        self._assert_nodes_equal(taxonomy.root, restored.root)

    def _assert_nodes_equal(self, a: TaxonomyNode, b: TaxonomyNode) -> None:
        assert a.label == b.label
        assert len(a.children) == len(b.children)
        for ac, bc in zip(
            sorted(a.children, key=lambda n: n.label),
            sorted(b.children, key=lambda n: n.label),
        ):
            self._assert_nodes_equal(ac, bc)

    @given(taxonomy=_taxonomy_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_taxonomy_load_from_dict_round_trip(self, taxonomy: Taxonomy) -> None:
        """Loading a taxonomy from a dict and serializing back must be equivalent.

        **Validates: Requirements 13.3**
        """
        source_dict = taxonomy.to_dict()
        loaded = load_taxonomy(source_dict)

        assert loaded.name == taxonomy.name
        assert loaded.version == taxonomy.version
        assert loaded.get_all_labels() == taxonomy.get_all_labels()


# ---------------------------------------------------------------------------
# Property 25: Subtype refinement hierarchy consistency
# ---------------------------------------------------------------------------


class TestSubtypeRefinementHierarchyConsistency:
    """Property 25: Subtype refinement hierarchy consistency.

    For any broad cell type label refined to a subtype, the subtype must be
    a valid child of the broad label in the cell type hierarchy.

    # Feature: gap-analysis-and-verification, Property 25: Subtype refinement hierarchy consistency

    **Validates: Requirements 13.4**
    """

    @given(taxonomy=_taxonomy_with_children_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_subtype_is_valid_child_of_broad_label(
        self,
        taxonomy: Taxonomy,
        data: st.DataObject,
    ) -> None:
        """Assigned subtypes must be valid children of the broad label in the hierarchy.

        **Validates: Requirements 13.4**
        """
        parent_label = taxonomy.root.label
        children = taxonomy.get_children(parent_label)
        assume(len(children) >= 2)

        # Create markers for each child subtype
        markers: list[MarkerGene] = []
        for child in children:
            gene = f"marker_{child[:5]}"
            markers.append(MarkerGene(gene=gene, cell_types=[child], weight=1.0))

        # Create cells with the broad label and expression for child markers
        n_cells = data.draw(st.integers(min_value=1, max_value=5))
        broad_labels: dict[str, str] = {}
        expression_matrix: dict[str, dict[str, float]] = {}

        for i in range(n_cells):
            cell_id = f"cell_{i}"
            broad_labels[cell_id] = parent_label
            # Give expression for at least one child's markers
            expr: dict[str, float] = {}
            for m in markers:
                expr[m.gene] = data.draw(_expression_value_st)
            expression_matrix[cell_id] = expr

        results = assign_subtypes(broad_labels, expression_matrix, taxonomy, markers)

        for cell_id, assignment in results.items():
            assert assignment.broad_label == parent_label
            # Subtype must be either the broad label itself or a valid child
            if assignment.subtype != parent_label:
                assert taxonomy.is_valid_child(parent_label, assignment.subtype), (
                    f"Subtype '{assignment.subtype}' is not a valid child of "
                    f"'{parent_label}'. Valid children: {children}"
                )
            assert 0.0 <= assignment.confidence <= 1.0

    @given(taxonomy=_taxonomy_with_children_st(), data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_subtype_assignment_confidence_in_bounds(
        self,
        taxonomy: Taxonomy,
        data: st.DataObject,
    ) -> None:
        """Subtype assignment confidence must be in [0.0, 1.0].

        **Validates: Requirements 13.4**
        """
        parent_label = taxonomy.root.label
        children = taxonomy.get_children(parent_label)
        assume(len(children) >= 1)

        markers = [MarkerGene(gene=f"g_{c[:4]}", cell_types=[c], weight=1.0) for c in children]

        broad_labels = {"cell_0": parent_label}
        expression_matrix = {"cell_0": {m.gene: data.draw(_expression_value_st) for m in markers}}

        results = assign_subtypes(broad_labels, expression_matrix, taxonomy, markers)

        for assignment in results.values():
            assert 0.0 <= assignment.confidence <= 1.0


# ---------------------------------------------------------------------------
# Property 26: Annotation robustness under perturbation
# ---------------------------------------------------------------------------


class TestAnnotationRobustnessUnderPerturbation:
    """Property 26: Annotation robustness under perturbation.

    For any annotation result, applying small perturbations (e.g., 5% cell
    subsampling) and re-annotating must produce labels that agree with the
    original on at least 90% of the shared cells.

    # Feature: gap-analysis-and-verification, Property 26: Annotation robustness under perturbation

    **Validates: Requirements 13.5**
    """

    @given(
        expression_matrix=_expression_matrix_st(min_cells=5, max_cells=20),
        markers=_marker_list_st(min_size=1, max_size=5),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_agreement_rate_above_threshold(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
        data: st.DataObject,
    ) -> None:
        """Agreement rate on shared cells must be >= 90% with 5% subsampling.

        **Validates: Requirements 13.5**
        """
        cell_ids = list(expression_matrix.keys())
        assume(len(cell_ids) >= 5)

        # Assign labels (use cell_id as cluster for simplicity)
        labels = {cid: f"type_{i % 3}" for i, cid in enumerate(cell_ids)}
        seed = data.draw(st.integers(min_value=0, max_value=10000))

        result = evaluate_robustness(
            expression_matrix=expression_matrix,
            markers=markers,
            labels=labels,
            subsample_fraction=0.95,
            seed=seed,
        )

        assert result.agreement_rate >= 0.9, (
            f"Agreement rate {result.agreement_rate} is below 0.9 threshold"
        )

    @given(
        expression_matrix=_expression_matrix_st(min_cells=5, max_cells=20),
        markers=_marker_list_st(min_size=1, max_size=5),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_agreement_rate_in_bounds(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
        data: st.DataObject,
    ) -> None:
        """Agreement rate must be in [0.0, 1.0].

        **Validates: Requirements 13.5**
        """
        cell_ids = list(expression_matrix.keys())
        assume(len(cell_ids) >= 2)

        labels = {cid: f"type_{i % 2}" for i, cid in enumerate(cell_ids)}
        seed = data.draw(st.integers(min_value=0, max_value=10000))

        result = evaluate_robustness(
            expression_matrix=expression_matrix,
            markers=markers,
            labels=labels,
            subsample_fraction=0.95,
            seed=seed,
        )

        assert 0.0 <= result.agreement_rate <= 1.0
        assert result.shared_cell_count >= 0

    @given(
        expression_matrix=_expression_matrix_st(min_cells=5, max_cells=15),
        markers=_marker_list_st(min_size=1, max_size=5),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_shared_cells_are_subset_of_original(
        self,
        expression_matrix: dict[str, dict[str, float]],
        markers: list[MarkerGene],
        data: st.DataObject,
    ) -> None:
        """Shared cells in the robustness result must be a subset of original cells.

        **Validates: Requirements 13.5**
        """
        cell_ids = list(expression_matrix.keys())
        assume(len(cell_ids) >= 3)

        labels = {cid: f"type_{i % 2}" for i, cid in enumerate(cell_ids)}
        seed = data.draw(st.integers(min_value=0, max_value=10000))

        result = evaluate_robustness(
            expression_matrix=expression_matrix,
            markers=markers,
            labels=labels,
            subsample_fraction=0.95,
            seed=seed,
        )

        # All cells in perturbed_labels must be in original labels
        for cell_id in result.perturbed_labels:
            assert cell_id in labels, f"Perturbed cell '{cell_id}' not in original labels"


# ---------------------------------------------------------------------------
# Imports for Properties 29-30 (Evidence Scoring and Marker Index)
# ---------------------------------------------------------------------------

from methods.annotation.evidence_scoring import (
    CellTypeAssignment,
    KnowledgePack,
    KnowledgePackMarker,
    build_marker_index,
    compute_evidence,
    search_markers,
)

# ---------------------------------------------------------------------------
# Strategies for Properties 29-30
# ---------------------------------------------------------------------------

_pack_id_st = st.text(min_size=1, max_size=15, alphabet="abcdefghij0123456789")

_version_st = st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True)


@st.composite
def _knowledge_pack_marker_st(draw):
    """Strategy for a KnowledgePackMarker."""
    gene = draw(_gene_st)
    n_types = draw(st.integers(min_value=1, max_value=3))
    cell_types = [draw(_cell_type_st) for _ in range(n_types)]
    weight = draw(_weight_st)
    return KnowledgePackMarker(gene=gene, cell_types=cell_types, weight=weight)


@st.composite
def _knowledge_pack_st(draw, min_markers=1, max_markers=8):
    """Strategy for a KnowledgePack."""
    pack_id = draw(_pack_id_st)
    version = draw(_version_st)
    n = draw(st.integers(min_value=min_markers, max_value=max_markers))
    markers = [draw(_knowledge_pack_marker_st()) for _ in range(n)]
    return KnowledgePack(pack_id=pack_id, version=version, markers=markers)


@st.composite
def _cell_type_assignment_st(draw):
    """Strategy for a CellTypeAssignment with valid bounded inputs."""
    cell_type = draw(_cell_type_st)
    n_genes = draw(st.integers(min_value=0, max_value=5))
    marker_expression = {draw(_gene_st): draw(_expression_value_st) for _ in range(n_genes)}
    ref_conf = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    onto_conf = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    return CellTypeAssignment(
        cell_type=cell_type,
        marker_expression=marker_expression,
        reference_mapping_confidence=ref_conf,
        ontology_alignment_confidence=onto_conf,
    )


# ---------------------------------------------------------------------------
# Property 29: Evidence scoring composite bounds and components
# ---------------------------------------------------------------------------


class TestEvidenceScoringCompositeBounds:
    """Property 29: Evidence scoring composite bounds and components.

    For any cell type assignment, the composite evidence score must be in
    [0.0, 1.0] and must be a function of marker_score, reference_mapping_score,
    and ontology_alignment_score, all of which must also be in [0.0, 1.0].

    # Feature: gap-analysis-and-verification, Property 29: Evidence scoring composite bounds and components

    **Validates: Requirements 15.1**
    """

    @given(assignment=_cell_type_assignment_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_component_scores_in_bounds(
        self,
        assignment: CellTypeAssignment,
    ) -> None:
        """All component scores must be in [0.0, 1.0].

        **Validates: Requirements 15.1**
        """
        result = compute_evidence(assignment)

        assert 0.0 <= result.marker_score <= 1.0, (
            f"marker_score {result.marker_score} out of bounds"
        )
        assert 0.0 <= result.reference_mapping_score <= 1.0, (
            f"reference_mapping_score {result.reference_mapping_score} out of bounds"
        )
        assert 0.0 <= result.ontology_alignment_score <= 1.0, (
            f"ontology_alignment_score {result.ontology_alignment_score} out of bounds"
        )

    @given(assignment=_cell_type_assignment_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_composite_score_in_bounds(
        self,
        assignment: CellTypeAssignment,
    ) -> None:
        """Composite score must be in [0.0, 1.0].

        **Validates: Requirements 15.1**
        """
        result = compute_evidence(assignment)

        assert 0.0 <= result.composite_score <= 1.0, (
            f"composite_score {result.composite_score} out of bounds"
        )

    @given(
        assignment=_cell_type_assignment_st(),
        marker_genes=st.lists(_knowledge_pack_marker_st(), min_size=0, max_size=5),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_scores_in_bounds_with_marker_genes(
        self,
        assignment: CellTypeAssignment,
        marker_genes: list[KnowledgePackMarker],
    ) -> None:
        """All scores remain in [0.0, 1.0] when marker genes are provided.

        **Validates: Requirements 15.1**
        """
        result = compute_evidence(assignment, marker_genes=marker_genes)

        assert 0.0 <= result.marker_score <= 1.0
        assert 0.0 <= result.reference_mapping_score <= 1.0
        assert 0.0 <= result.ontology_alignment_score <= 1.0
        assert 0.0 <= result.composite_score <= 1.0

    @given(assignment=_cell_type_assignment_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_composite_is_function_of_components(
        self,
        assignment: CellTypeAssignment,
    ) -> None:
        """Composite score must be derivable from the three component scores.

        Specifically, the composite must equal the weighted average of the
        components using the default weights (0.5, 0.3, 0.2).

        **Validates: Requirements 15.1**
        """
        result = compute_evidence(assignment)

        expected = (
            0.5 * result.marker_score
            + 0.3 * result.reference_mapping_score
            + 0.2 * result.ontology_alignment_score
        )
        assert result.composite_score == pytest.approx(expected, abs=1e-9), (
            f"composite_score {result.composite_score} != expected {expected}"
        )

    @given(assignment=_cell_type_assignment_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cell_type_preserved(
        self,
        assignment: CellTypeAssignment,
    ) -> None:
        """The cell_type in the result must match the assignment input.

        **Validates: Requirements 15.1**
        """
        result = compute_evidence(assignment)
        assert result.cell_type == assignment.cell_type


# ---------------------------------------------------------------------------
# Property 30: Marker index completeness and search
# ---------------------------------------------------------------------------


class TestMarkerIndexCompletenessAndSearch:
    """Property 30: Marker index completeness and search.

    For any set of loaded Knowledge_Packs, the marker index must contain
    every marker from every pack. For any query matching a known marker,
    the search result must include cell_types, source, and confidence_weight.

    # Feature: gap-analysis-and-verification, Property 30: Marker index completeness and search

    **Validates: Requirements 15.2, 15.3**
    """

    @given(packs=st.lists(_knowledge_pack_st(), min_size=1, max_size=5))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_index_contains_every_marker_from_every_pack(
        self,
        packs: list[KnowledgePack],
    ) -> None:
        """The marker index must contain every marker from every pack.

        **Validates: Requirements 15.2**
        """
        index = build_marker_index(packs)

        for pack in packs:
            for marker in pack.markers:
                assert marker.gene in index.entries, (
                    f"Gene '{marker.gene}' from pack '{pack.pack_id}' not found in index"
                )
                # Verify this specific pack's entry exists
                hits_for_gene = index.entries[marker.gene]
                matching = [
                    h
                    for h in hits_for_gene
                    if h.source == pack.pack_id and h.version == pack.version
                ]
                assert len(matching) >= 1, (
                    f"No hit for gene '{marker.gene}' from pack '{pack.pack_id}' v{pack.version}"
                )

    @given(packs=st.lists(_knowledge_pack_st(), min_size=1, max_size=5))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_search_returns_required_fields(
        self,
        packs: list[KnowledgePack],
    ) -> None:
        """Search results must include cell_types, source, and confidence_weight.

        **Validates: Requirements 15.3**
        """
        index = build_marker_index(packs)

        # Pick a known gene from the first pack
        assume(len(packs[0].markers) > 0)
        known_gene = packs[0].markers[0].gene

        results = search_markers(index, known_gene)
        assert len(results) >= 1, f"Search for known gene '{known_gene}' returned no results"

        for hit in results:
            assert isinstance(hit.cell_types, list), "cell_types must be a list"
            assert isinstance(hit.source, str) and hit.source, "source must be non-empty"
            assert 0.0 <= hit.confidence_weight <= 1.0, (
                f"confidence_weight {hit.confidence_weight} out of bounds"
            )

    @given(packs=st.lists(_knowledge_pack_st(), min_size=1, max_size=3))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_total_index_entry_count(
        self,
        packs: list[KnowledgePack],
    ) -> None:
        """Total number of index entries must equal total markers across all packs.

        **Validates: Requirements 15.2**
        """
        index = build_marker_index(packs)

        total_markers = sum(len(pack.markers) for pack in packs)
        total_hits = sum(len(hits) for hits in index.entries.values())
        assert total_hits == total_markers, (
            f"Index has {total_hits} entries but packs have {total_markers} markers"
        )

    @given(packs=st.lists(_knowledge_pack_st(), min_size=1, max_size=3))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_search_hit_fields_match_source_pack(
        self,
        packs: list[KnowledgePack],
    ) -> None:
        """Each search hit's source and version must match an originating pack.

        **Validates: Requirements 15.2, 15.3**
        """
        index = build_marker_index(packs)

        # Build a set of valid (pack_id, version) pairs
        valid_pack_ids = {(p.pack_id, p.version) for p in packs}

        for gene, hits in index.entries.items():
            for hit in hits:
                assert (hit.source, hit.version) in valid_pack_ids, (
                    f"Hit (source='{hit.source}', version='{hit.version}') not in known packs"
                )
