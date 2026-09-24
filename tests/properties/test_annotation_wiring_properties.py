"""Property-based tests for annotation workflow auto-wiring from completed runs.

# Feature: gap-analysis-and-verification, Property 12: Annotation workflow auto-wiring from completed runs

**Validates: Requirements 9.1**
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from workflows.annotation.auto_wiring import (
    AnnotationInput,
    ClusterResults,
    InMemoryRunResultStore,
    auto_wire_annotation,
    get_cluster_results,
    manual_override,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_cell_ids = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
)

_cluster_labels = st.dictionaries(
    keys=_cell_ids,
    values=st.integers(min_value=0, max_value=50),
    min_size=1,
    max_size=50,
)

_method_name = st.sampled_from(["leiden", "louvain", "kmeans", "spectral"])

_parameters = st.fixed_dictionaries(
    {},
    optional={
        "resolution": st.floats(min_value=0.1, max_value=5.0, allow_nan=False),
        "n_neighbors": st.integers(min_value=5, max_value=100),
    },
)


def _make_cluster_artifact(
    cluster_labels: dict[str, int],
    method: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a raw cluster artifact dict as stored by the pipeline."""
    n_clusters = len(set(cluster_labels.values())) if cluster_labels else 0
    return {
        "cluster_labels": cluster_labels,
        "n_clusters": n_clusters,
        "method": method,
        "parameters": parameters or {},
        "completed_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestAnnotationWorkflowAutoWiring:
    """Property 12: Annotation workflow auto-wiring from completed runs.

    For any pipeline run that has completed clustering, the annotation
    workflow must be able to retrieve cluster results without manual JSON
    input.
    """

    @given(
        cluster_labels=_cluster_labels,
        method=_method_name,
        params=_parameters,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_auto_wire_retrieves_cluster_results_without_manual_input(
        self,
        cluster_labels: dict[str, int],
        method: str,
        params: dict[str, Any],
    ) -> None:
        """For any completed run with clustering, auto_wire_annotation must
        return an AnnotationInput with source='auto' and matching cluster
        data — no manual JSON required."""
        run_id = uuid4()
        store = InMemoryRunResultStore()
        artifact = _make_cluster_artifact(cluster_labels, method, params)
        store.seed_run(run_id, "completed", artifact)

        result = asyncio.get_event_loop().run_until_complete(auto_wire_annotation(run_id, store))

        assert isinstance(result, AnnotationInput)
        assert result.source == "auto"
        assert result.run_id == run_id
        assert result.cluster_labels == cluster_labels
        assert result.method == method
        assert result.n_clusters == artifact["n_clusters"]

    @given(
        cluster_labels=_cluster_labels,
        method=_method_name,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_get_cluster_results_returns_valid_model(
        self,
        cluster_labels: dict[str, int],
        method: str,
    ) -> None:
        """get_cluster_results must return a valid ClusterResults for any
        completed run with a clustering artifact."""
        run_id = uuid4()
        store = InMemoryRunResultStore()
        artifact = _make_cluster_artifact(cluster_labels, method)
        store.seed_run(run_id, "completed", artifact)

        result = asyncio.get_event_loop().run_until_complete(get_cluster_results(run_id, store))

        assert isinstance(result, ClusterResults)
        assert result.run_id == run_id
        assert result.cluster_labels == cluster_labels
        assert result.method == method
        assert result.n_clusters == artifact["n_clusters"]

    @given(
        status=st.sampled_from(["queued", "running", "failed", "cancelled"]),
        cluster_labels=_cluster_labels,
        method=_method_name,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_non_completed_run_raises_error(
        self,
        status: str,
        cluster_labels: dict[str, int],
        method: str,
    ) -> None:
        """Runs that have not completed must not yield cluster results."""
        run_id = uuid4()
        store = InMemoryRunResultStore()
        artifact = _make_cluster_artifact(cluster_labels, method)
        store.seed_run(run_id, status, artifact)

        with pytest.raises(ValueError, match="status"):
            asyncio.get_event_loop().run_until_complete(auto_wire_annotation(run_id, store))

    def test_missing_run_raises_error(self) -> None:
        """A non-existent run must raise ValueError."""
        store = InMemoryRunResultStore()
        with pytest.raises(ValueError, match="not found"):
            asyncio.get_event_loop().run_until_complete(auto_wire_annotation(uuid4(), store))

    @given(
        cluster_labels=_cluster_labels,
        method=_method_name,
        params=_parameters,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_manual_override_produces_manual_source(
        self,
        cluster_labels: dict[str, int],
        method: str,
        params: dict[str, Any],
    ) -> None:
        """manual_override must produce an AnnotationInput with
        source='manual_override'."""
        n_clusters = len(set(cluster_labels.values())) if cluster_labels else 0
        json_input: dict[str, Any] = {
            "cluster_labels": cluster_labels,
            "n_clusters": n_clusters,
            "method": method,
            "parameters": params,
        }

        result = manual_override(json_input)

        assert isinstance(result, AnnotationInput)
        assert result.source == "manual_override"
        assert result.cluster_labels == cluster_labels
        assert result.method == method
        assert result.n_clusters == n_clusters

    def test_manual_override_rejects_missing_fields(self) -> None:
        """manual_override must reject JSON missing required fields."""
        with pytest.raises(ValueError, match="missing required fields"):
            manual_override({"cluster_labels": {"c1": 0}})
