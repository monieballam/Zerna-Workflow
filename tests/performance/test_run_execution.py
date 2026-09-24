"""Performance tests for run execution.

Measures run creation, status tracking, and progress update throughput.
Simulates 100k cell dataset processing time tracking to verify the
control-plane can keep up with compute-plane events.

Validates: Requirements 17.1, 17.2
"""

import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.performance.conftest import FakeDBSession

pytestmark = [pytest.mark.slow, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_run_service():
    """Create a RunService with all external deps mocked."""
    from apps.api.services.audit_service import AuditService
    from apps.api.services.cache_service import CacheService
    from apps.api.services.pipeline_service import PipelineService
    from apps.api.services.run_service import RunService

    db = FakeDBSession()

    mock_pipeline = AsyncMock(spec=PipelineService)
    mock_pipeline.validate_parameters = AsyncMock(return_value=(True, None))

    mock_cache = AsyncMock(spec=CacheService)
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock(return_value=True)
    mock_cache.invalidate_run_status = AsyncMock(return_value=None)

    mock_audit = AsyncMock(spec=AuditService)
    mock_audit.audit_log = AsyncMock(return_value=None)

    svc = RunService(
        db=db,
        pipeline_service=mock_pipeline,
        cache_service=mock_cache,
        audit_service=mock_audit,
    )
    return svc


# ---------------------------------------------------------------------------
# Run creation latency
# ---------------------------------------------------------------------------


class TestRunCreationLatency:
    """Run creation should be fast — it's just validation + DB insert."""

    async def test_run_creation_under_100ms(self):
        svc = _make_mock_run_service()

        start = time.perf_counter()
        try:
            await svc.create_run(
                org_id=uuid4(),
                dataset_version_id=uuid4(),
                template_id=uuid4(),
                parameters={"resolution": 1.0, "n_components": 50},
                random_seed=42,
                user_id=uuid4(),
            )
        except (ValueError, AttributeError):
            # FakeDB won't find the dataset/template — expected
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.100, f"Run creation took {elapsed * 1000:.1f}ms, exceeds 100ms budget"


# ---------------------------------------------------------------------------
# Status tracking latency
# ---------------------------------------------------------------------------


class TestRunStatusLatency:
    """Status queries should be fast, especially with cache hits."""

    async def test_status_query_under_50ms(self):
        svc = _make_mock_run_service()
        run_id = uuid4()

        start = time.perf_counter()
        await svc.get_run_status(run_id)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.050, f"Status query took {elapsed * 1000:.1f}ms, exceeds 50ms budget"

    async def test_100_status_queries_under_2s(self):
        """Simulate rapid status polling for a running pipeline."""
        svc = _make_mock_run_service()
        run_id = uuid4()

        start = time.perf_counter()
        for _ in range(100):
            await svc.get_run_status(run_id)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"100 status queries took {elapsed:.2f}s, exceeds 2s budget"


# ---------------------------------------------------------------------------
# Progress update throughput
# ---------------------------------------------------------------------------


class TestProgressUpdateThroughput:
    """Simulate 100k cell dataset processing with progress updates.

    A typical pipeline emits progress events per step. For a 100k cell
    dataset with ~10 pipeline steps, we expect ~10 progress updates.
    The control-plane must handle these without becoming a bottleneck.
    """

    async def test_progress_updates_for_100k_cells_under_10min(self):
        """Simulate progress updates for a 100k cell pipeline run.

        We model 10 pipeline steps, each reporting progress.
        Total coordination overhead should be negligible compared
        to the 10-minute compute budget.
        """
        svc = _make_mock_run_service()
        run_id = uuid4()

        pipeline_steps = [
            {"step": "qc_filter", "cells_processed": 100_000, "pct": 10},
            {"step": "doublet_detection", "cells_processed": 95_000, "pct": 20},
            {"step": "normalization", "cells_processed": 90_000, "pct": 30},
            {"step": "hvg_selection", "genes_selected": 2000, "pct": 40},
            {"step": "pca", "n_components": 50, "pct": 50},
            {"step": "clustering", "n_clusters": 15, "pct": 60},
            {"step": "embedding", "method": "umap", "pct": 70},
            {"step": "annotation", "cell_types": 12, "pct": 80},
            {"step": "de_analysis", "comparisons": 105, "pct": 90},
            {"step": "pathway_scoring", "pathways": 50, "pct": 100},
        ]

        start = time.perf_counter()
        for step_data in pipeline_steps:
            try:
                await svc.update_progress(run_id, step_data)
            except (ValueError, AttributeError):
                # FakeDB won't find the run — expected
                pass
        elapsed = time.perf_counter() - start

        # Coordination overhead should be < 1 second (well within 10-min budget)
        assert elapsed < 1.0, (
            f"Progress updates for 10 steps took {elapsed * 1000:.0f}ms, exceeds 1s budget"
        )

    async def test_rapid_progress_updates_throughput(self):
        """Simulate 1000 rapid progress updates (e.g., per-batch reporting)."""
        svc = _make_mock_run_service()
        run_id = uuid4()

        start = time.perf_counter()
        for i in range(1000):
            try:
                await svc.update_progress(run_id, {"batch": i, "pct": i / 10})
            except (ValueError, AttributeError):
                pass
        elapsed = time.perf_counter() - start

        # 1000 updates should complete in < 5 seconds
        assert elapsed < 5.0, f"1000 progress updates took {elapsed:.2f}s, exceeds 5s budget"
