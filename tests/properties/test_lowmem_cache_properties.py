"""Property-based tests for low-memory annotation mode and marker cache.

# Feature: gap-analysis-and-verification, Property 33: Low-memory mode equivalence
# Feature: gap-analysis-and-verification, Property 34: Marker cache round-trip

**Validates: Requirements 17.1, 17.2, 17.3**
"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.lowmem import annotate_chunked
from methods.annotation.marker_cache import MarkerExpressionCache
from methods.annotation.scoring import MarkerGene, score

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_gene_st = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("Lu",)),
).filter(lambda s: s.strip() != "")

_cell_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_cluster_id_st = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_expression_st = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

_weight_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

_dataset_version_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_score_value_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _marker_gene_st(draw: st.DrawFn) -> MarkerGene:
    gene = draw(_gene_st)
    cell_types = draw(st.lists(_cluster_id_st, min_size=1, max_size=3, unique=True))
    weight = draw(_weight_st)
    return MarkerGene(gene=gene, cell_types=cell_types, weight=weight)


@st.composite
def _expression_matrix_st(draw: st.DrawFn) -> dict[str, dict[str, float]]:
    """Generate a small expression matrix with unique cell IDs."""
    genes = draw(st.lists(_gene_st, min_size=1, max_size=5, unique=True))
    cell_ids = draw(st.lists(_cell_id_st, min_size=1, max_size=20, unique=True))
    matrix: dict[str, dict[str, float]] = {}
    for cid in cell_ids:
        expr: dict[str, float] = {}
        for g in genes:
            expr[g] = draw(_expression_st)
        matrix[cid] = expr
    return matrix


@st.composite
def _cluster_assignments_st(draw: st.DrawFn, cell_ids: list[str]) -> dict[str, str]:
    """Generate cluster assignments for given cell IDs."""
    clusters = draw(st.lists(_cluster_id_st, min_size=1, max_size=4, unique=True))
    return {cid: draw(st.sampled_from(clusters)) for cid in cell_ids}


@st.composite
def _scoring_inputs_st(draw: st.DrawFn):
    """Generate a consistent set of expression matrix, markers, and cluster assignments."""
    matrix = draw(_expression_matrix_st())
    markers = draw(st.lists(_marker_gene_st(), min_size=1, max_size=5))
    cell_ids = list(matrix.keys())
    use_clusters = draw(st.booleans())
    clusters = draw(_cluster_assignments_st(cell_ids)) if use_clusters else None
    return matrix, markers, clusters


# ---------------------------------------------------------------------------
# Property 33: Low-memory mode equivalence
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestLowMemoryModeEquivalence:
    """Property 33: Low-memory mode equivalence.

    For any dataset, processing annotation in chunked low-memory mode must
    produce results equivalent to processing the full dataset at once.
    """

    @given(data=_scoring_inputs_st(), chunk_size=st.integers(min_value=1, max_value=25))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_chunked_equals_full(
        self,
        data: tuple,
        chunk_size: int,
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 33: Low-memory mode equivalence"""
        matrix, markers, clusters = data

        # Full (non-chunked) scoring
        full_result = score(matrix, markers, clusters)

        # Chunked scoring
        chunked_result = annotate_chunked(matrix, markers, chunk_size, clusters)

        # Per-cell scores must be identical
        assert set(chunked_result.per_cell_scores.keys()) == set(
            full_result.per_cell_scores.keys()
        ), "Chunked and full results must have the same cell IDs"

        for cell_id in full_result.per_cell_scores:
            assert math.isclose(
                chunked_result.per_cell_scores[cell_id],
                full_result.per_cell_scores[cell_id],
                abs_tol=1e-9,
            ), (
                f"Cell {cell_id} score mismatch: chunked={chunked_result.per_cell_scores[cell_id]} vs full={full_result.per_cell_scores[cell_id]}"
            )

        # Per-cluster scores must be equivalent
        assert set(chunked_result.per_cluster_scores.keys()) == set(
            full_result.per_cluster_scores.keys()
        ), "Chunked and full results must have the same cluster IDs"

        for cluster_id in full_result.per_cluster_scores:
            assert math.isclose(
                chunked_result.per_cluster_scores[cluster_id],
                full_result.per_cluster_scores[cluster_id],
                abs_tol=1e-9,
            ), f"Cluster {cluster_id} score mismatch"

    @given(data=_scoring_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_chunk_size_one_equals_full(self, data: tuple) -> None:
        """Chunk size 1 (extreme) must still produce equivalent results."""
        matrix, markers, clusters = data

        full_result = score(matrix, markers, clusters)
        chunked_result = annotate_chunked(matrix, markers, 1, clusters)

        assert chunked_result.chunk_count == len(matrix)

        for cell_id in full_result.per_cell_scores:
            assert math.isclose(
                chunked_result.per_cell_scores[cell_id],
                full_result.per_cell_scores[cell_id],
                abs_tol=1e-9,
            )

    @given(data=_scoring_inputs_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_chunk_size_larger_than_dataset(self, data: tuple) -> None:
        """Chunk size larger than dataset should process in a single chunk."""
        matrix, markers, clusters = data

        full_result = score(matrix, markers, clusters)
        chunked_result = annotate_chunked(matrix, markers, len(matrix) + 100, clusters)

        assert chunked_result.chunk_count == 1

        for cell_id in full_result.per_cell_scores:
            assert math.isclose(
                chunked_result.per_cell_scores[cell_id],
                full_result.per_cell_scores[cell_id],
                abs_tol=1e-9,
            )


# ---------------------------------------------------------------------------
# Property 34: Marker cache round-trip
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestMarkerCacheRoundTrip:
    """Property 34: Marker cache round-trip.

    For any marker scores computed for a dataset version, storing them in the
    cache and retrieving them must return identical scores.
    """

    @given(
        dataset_version_id=_dataset_version_st,
        markers=st.lists(_gene_st, min_size=1, max_size=10, unique=True),
        per_cluster_scores=st.dictionaries(
            keys=_cluster_id_st,
            values=_score_value_st,
            min_size=1,
            max_size=10,
        ),
        per_cell_scores=st.dictionaries(
            keys=_cell_id_st,
            values=_score_value_st,
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_put_then_get_returns_identical_scores(
        self,
        dataset_version_id: str,
        markers: list[str],
        per_cluster_scores: dict[str, float],
        per_cell_scores: dict[str, float],
    ) -> None:
        """# Feature: gap-analysis-and-verification, Property 34: Marker cache round-trip"""
        cache = MarkerExpressionCache()

        # Store
        cache.put(dataset_version_id, markers, per_cluster_scores, per_cell_scores)

        # Retrieve
        result = cache.get(dataset_version_id, markers)

        assert result is not None, "Cache get must return a result after put"
        assert result.dataset_version_id == dataset_version_id
        assert result.per_cluster_scores == per_cluster_scores
        assert result.per_cell_scores == per_cell_scores

    @given(
        dataset_version_id=_dataset_version_st,
        markers=st.lists(_gene_st, min_size=1, max_size=10, unique=True),
        per_cluster_scores=st.dictionaries(
            keys=_cluster_id_st,
            values=_score_value_st,
            min_size=1,
            max_size=10,
        ),
        per_cell_scores=st.dictionaries(
            keys=_cell_id_st,
            values=_score_value_st,
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_marker_order_independence(
        self,
        dataset_version_id: str,
        markers: list[str],
        per_cluster_scores: dict[str, float],
        per_cell_scores: dict[str, float],
    ) -> None:
        """Cache key must be independent of marker list order."""
        assume(len(markers) >= 2)

        cache = MarkerExpressionCache()
        cache.put(dataset_version_id, markers, per_cluster_scores, per_cell_scores)

        # Retrieve with reversed marker order
        reversed_markers = list(reversed(markers))
        result = cache.get(dataset_version_id, reversed_markers)

        assert result is not None, "Cache must be order-independent for markers"
        assert result.per_cluster_scores == per_cluster_scores
        assert result.per_cell_scores == per_cell_scores

    @given(
        dataset_version_id=_dataset_version_st,
        markers=st.lists(_gene_st, min_size=1, max_size=10, unique=True),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_cache_miss_returns_none(
        self,
        dataset_version_id: str,
        markers: list[str],
    ) -> None:
        """An empty cache must return None for any query."""
        cache = MarkerExpressionCache()
        result = cache.get(dataset_version_id, markers)
        assert result is None
