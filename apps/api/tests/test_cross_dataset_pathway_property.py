"""Property-based tests for cross-dataset pathway pattern identification.

**Property 38: Cross-Dataset Pathway Pattern Identification**
**Validates: Requirements 25.6, 25.7, 25.10**
"""

from uuid import uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from apps.api.services.pathway_service import PathwayService

# ── Strategies ─────────────────────────────────────────────────────────────────

pathway_id_st = st.text(
    min_size=3,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
)

score_st = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)

pathway_scores_st = st.dictionaries(
    pathway_id_st,
    score_st,
    min_size=1,
    max_size=10,
)

dataset_summary_st = st.fixed_dictionaries(
    {
        "dataset_id": st.uuids().map(str),
        "pathway_scores": pathway_scores_st,
    }
)

dataset_summaries_st = st.lists(dataset_summary_st, min_size=2, max_size=6)


# ── Helper ─────────────────────────────────────────────────────────────────────


def make_service() -> PathwayService:
    """Create a PathwayService without a DB (aggregate_pathway_scores is pure)."""
    return PathwayService(db=None)  # type: ignore[arg-type]


# ── Properties ─────────────────────────────────────────────────────────────────


@pytest.mark.property
class TestCrossDatasetPathwayPatternIdentification:
    """Property 38: Cross-Dataset Pathway Pattern Identification

    For any collection of ≥2 datasets with pathway scores, the aggregation
    should only return patterns present in ≥2 datasets, with valid statistical
    measures, and cross-reference patterns not visible in single datasets.
    """

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_patterns_only_from_multi_dataset_pathways(self, dataset_summaries):
        """Property: every returned pattern must appear in at least 2 datasets.

        **Validates: Requirements 25.6, 25.7**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        for pattern in patterns:
            assert len(pattern["datasets_present"]) >= 2, (
                f"Pattern '{pattern['pathway_id']}' appears in only "
                f"{len(pattern['datasets_present'])} dataset(s), expected ≥2"
            )

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_aggregated_score_within_input_range(self, dataset_summaries):
        """Property: aggregated_score is within the range of input scores for that pathway.

        **Validates: Requirements 25.7**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        # Build a lookup of all scores per pathway
        all_scores: dict = {}
        for summary in dataset_summaries:
            for pid, score in summary.get("pathway_scores", {}).items():
                all_scores.setdefault(pid, []).append(score)

        for pattern in patterns:
            pid = pattern["pathway_id"]
            scores = all_scores.get(pid, [])
            if not scores:
                continue
            assert min(scores) - 1e-9 <= pattern["aggregated_score"] <= max(scores) + 1e-9, (
                f"Aggregated score {pattern['aggregated_score']} for '{pid}' "
                f"is outside input range [{min(scores)}, {max(scores)}]"
            )

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_p_value_in_valid_range(self, dataset_summaries):
        """Property: p_value is in [0, 1] for all patterns.

        **Validates: Requirements 25.7**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        for pattern in patterns:
            assert 0.0 <= pattern["p_value"] <= 1.0, (
                f"p_value {pattern['p_value']} for '{pattern['pathway_id']}' is outside [0, 1]"
            )

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_confidence_in_valid_range(self, dataset_summaries):
        """Property: confidence is in (0, 1] for all patterns.

        **Validates: Requirements 25.7**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        for pattern in patterns:
            assert 0.0 < pattern["confidence"] <= 1.0, (
                f"confidence {pattern['confidence']} for '{pattern['pathway_id']}' "
                f"is outside (0, 1]"
            )

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_patterns_sorted_by_p_value_ascending(self, dataset_summaries):
        """Property: patterns are sorted by p_value ascending (most significant first).

        **Validates: Requirements 25.7**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        p_values = [p["p_value"] for p in patterns]
        assert p_values == sorted(p_values), (
            f"Patterns are not sorted by p_value ascending: {p_values}"
        )

    @given(dataset_summaries=dataset_summaries_st)
    @settings(max_examples=200)
    def test_cross_dataset_patterns_not_visible_in_single_dataset(self, dataset_summaries):
        """Property: patterns spanning multiple datasets reveal cross-dataset insights
        that cannot be seen from any single dataset alone.

        **Validates: Requirements 25.10**
        """
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        # Collect pathways visible in each individual dataset
        single_dataset_pathways = [
            set(s.get("pathway_scores", {}).keys()) for s in dataset_summaries
        ]

        for pattern in patterns:
            pid = pattern["pathway_id"]
            datasets_with_pathway = [
                i for i, pws in enumerate(single_dataset_pathways) if pid in pws
            ]
            # The cross-dataset view aggregates across multiple datasets —
            # the pattern must span at least 2, providing insight beyond any single dataset
            assert len(datasets_with_pathway) >= 2, (
                f"Pattern '{pid}' should span ≥2 datasets for cross-dataset insight"
            )

    @given(
        shared_pathway=pathway_id_st,
        shared_score=score_st,
        n_datasets=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=100)
    def test_pathway_present_in_all_datasets_has_max_confidence(
        self, shared_pathway, shared_score, n_datasets
    ):
        """Property: a pathway present in ALL datasets has confidence = 1.0.

        **Validates: Requirements 25.7**
        """
        dataset_summaries = [
            {"dataset_id": str(uuid4()), "pathway_scores": {shared_pathway: shared_score}}
            for _ in range(n_datasets)
        ]
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        matching = [p for p in patterns if p["pathway_id"] == shared_pathway]
        assert len(matching) == 1, f"Expected exactly 1 pattern for '{shared_pathway}'"
        assert matching[0]["confidence"] == 1.0, (
            f"Pathway present in all {n_datasets} datasets should have confidence=1.0, "
            f"got {matching[0]['confidence']}"
        )

    @given(
        pathway_a=pathway_id_st,
        pathway_b=pathway_id_st,
        score_a=score_st,
        score_b=score_st,
    )
    @settings(max_examples=100)
    def test_single_dataset_pathway_excluded(self, pathway_a, pathway_b, score_a, score_b):
        """Property: a pathway present in only 1 dataset is excluded from results.

        **Validates: Requirements 25.6**
        """
        assume(pathway_a != pathway_b)

        # pathway_a is in both datasets; pathway_b is only in dataset 1
        dataset_summaries = [
            {
                "dataset_id": str(uuid4()),
                "pathway_scores": {pathway_a: score_a, pathway_b: score_b},
            },
            {"dataset_id": str(uuid4()), "pathway_scores": {pathway_a: score_a}},
        ]
        svc = make_service()
        patterns = svc.aggregate_pathway_scores(dataset_summaries)

        pattern_ids = {p["pathway_id"] for p in patterns}
        assert pathway_a in pattern_ids, f"'{pathway_a}' (in 2 datasets) should be included"
        assert pathway_b not in pattern_ids, (
            f"'{pathway_b}' (in only 1 dataset) should be excluded from cross-dataset patterns"
        )
