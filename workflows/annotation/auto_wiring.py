"""Annotation workflow auto-wiring from completed pipeline runs.

Automatically retrieves cluster results from completed runs so that the
annotation workflow can be started without manual JSON input.  An advanced-mode
manual JSON override is also supported.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ClusterResults(ZernaBaseModel):
    """Cluster results produced by a pipeline clustering step."""

    run_id: UUID
    cluster_labels: dict[str, int]  # cell_id -> cluster_id
    n_clusters: int
    method: str  # e.g. "leiden", "louvain"
    parameters: dict[str, Any] = {}
    completed_at: datetime


class AnnotationInput(ZernaBaseModel):
    """Input contract for the annotation workflow."""

    run_id: UUID | None = None
    cluster_labels: dict[str, int]
    n_clusters: int
    method: str
    parameters: dict[str, Any] = {}
    source: str  # "auto" or "manual_override"


# ---------------------------------------------------------------------------
# Run result store (abstraction over the persistence layer)
# ---------------------------------------------------------------------------


class RunResultStore:
    """Abstract interface for retrieving completed run results.

    In production this would query the database / S3 artifacts.  For
    testing and standalone use, an in-memory implementation is provided.
    """

    async def get_run_status(self, run_id: UUID) -> str | None:
        """Return the run status string, or None if the run does not exist."""
        raise NotImplementedError

    async def get_cluster_artifact(self, run_id: UUID) -> dict[str, Any] | None:
        """Return the raw cluster artifact dict for a completed run, or None."""
        raise NotImplementedError


class InMemoryRunResultStore(RunResultStore):
    """Simple in-memory store for testing."""

    def __init__(self) -> None:
        self._runs: dict[UUID, dict[str, Any]] = {}

    def seed_run(
        self,
        run_id: UUID,
        status: str,
        cluster_artifact: dict[str, Any] | None = None,
    ) -> None:
        self._runs[run_id] = {
            "status": status,
            "cluster_artifact": cluster_artifact,
        }

    async def get_run_status(self, run_id: UUID) -> str | None:
        entry = self._runs.get(run_id)
        return entry["status"] if entry else None

    async def get_cluster_artifact(self, run_id: UUID) -> dict[str, Any] | None:
        entry = self._runs.get(run_id)
        if entry is None:
            return None
        return entry.get("cluster_artifact")


# ---------------------------------------------------------------------------
# Core auto-wiring functions
# ---------------------------------------------------------------------------


async def get_cluster_results(
    run_id: UUID,
    store: RunResultStore,
) -> ClusterResults:
    """Retrieve cluster results from a completed pipeline run.

    Raises:
        ValueError: If the run does not exist, has not completed, or has
            no clustering artifact.
    """
    status = await store.get_run_status(run_id)
    if status is None:
        raise ValueError(f"Run {run_id} not found")
    if status != "completed":
        raise ValueError(
            f"Run {run_id} has status '{status}'; clustering results are only "
            "available for completed runs"
        )

    artifact = await store.get_cluster_artifact(run_id)
    if artifact is None:
        raise ValueError(f"Run {run_id} has no clustering artifact")

    return ClusterResults(
        run_id=run_id,
        cluster_labels=artifact["cluster_labels"],
        n_clusters=artifact["n_clusters"],
        method=artifact["method"],
        parameters=artifact.get("parameters", {}),
        completed_at=datetime.fromisoformat(artifact["completed_at"])
        if isinstance(artifact.get("completed_at"), str)
        else artifact.get("completed_at", datetime.utcnow()),
    )


async def auto_wire_annotation(
    run_id: UUID,
    store: RunResultStore,
) -> AnnotationInput:
    """Auto-wire annotation input from a completed pipeline run.

    Retrieves cluster results and converts them into the annotation
    workflow input contract so that no manual JSON is required.

    Raises:
        ValueError: Propagated from ``get_cluster_results`` when the run
            is missing, incomplete, or lacks clustering output.
    """
    cluster = await get_cluster_results(run_id, store)
    return AnnotationInput(
        run_id=cluster.run_id,
        cluster_labels=cluster.cluster_labels,
        n_clusters=cluster.n_clusters,
        method=cluster.method,
        parameters=cluster.parameters,
        source="auto",
    )


def manual_override(json_input: dict[str, Any]) -> AnnotationInput:
    """Create annotation input from a manual JSON payload (advanced mode).

    This allows power users to bypass auto-wiring and supply their own
    cluster score / label payload directly.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    required = {"cluster_labels", "n_clusters", "method"}
    missing = required - set(json_input.keys())
    if missing:
        raise ValueError(f"Manual override JSON missing required fields: {missing}")

    return AnnotationInput(
        run_id=json_input.get("run_id"),
        cluster_labels=json_input["cluster_labels"],
        n_clusters=json_input["n_clusters"],
        method=json_input["method"],
        parameters=json_input.get("parameters", {}),
        source="manual_override",
    )
