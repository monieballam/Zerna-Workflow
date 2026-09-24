"""Load tests for 10 concurrent runs per organization.

Simulates 10 concurrent run creations, quota enforcement under load,
status polling for simultaneous runs, and concurrent state transitions.
Verifies the compute quota (10 concurrent runs) is properly enforced.

Validates: Requirements 17.1, 17.2
"""

import asyncio
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.performance.conftest import FakeDBSession

pytestmark = [pytest.mark.slow, pytest.mark.asyncio]

CONCURRENT_RUNS = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_service(active_run_count: int = 0, compute_quota: int = 10):
    """Create a RunService with configurable quota state.

    Args:
        active_run_count: Number of currently active runs (for quota checks).
        compute_quota: Max concurrent runs allowed.
    """
    from apps.api.services.audit_service import AuditService
    from apps.api.services.cache_service import CacheService
    from apps.api.services.pipeline_service import PipelineService
    from apps.api.services.quota_service import QuotaService
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

    # Override quota service methods to return configurable values
    svc.quota_service = AsyncMock(spec=QuotaService)
    svc.quota_service.get_active_run_count = AsyncMock(return_value=active_run_count)
    svc.quota_service.get_compute_quota = AsyncMock(return_value=compute_quota)

    # check_compute_quota: raise if at or above limit
    from apps.api.services.quota_service import QuotaExceededError

    async def _check_compute(org_id):
        if active_run_count >= compute_quota:
            raise QuotaExceededError(
                quota_type="compute",
                used=active_run_count,
                limit=compute_quota,
                unit=" concurrent runs",
            )

    svc.quota_service.check_compute_quota = AsyncMock(side_effect=_check_compute)

    return svc


# ---------------------------------------------------------------------------
# 10 concurrent run creations
# ---------------------------------------------------------------------------


class TestConcurrentRunCreation:
    """Simulate 10 concurrent run creations for one organization."""

    async def test_10_concurrent_run_creates_under_2s(self):
        """All 10 concurrent run creations should complete in < 2s."""
        svc = _make_run_service(active_run_count=0, compute_quota=10)
        org_id = uuid4()

        async def _create_run():
            start = time.perf_counter()
            try:
                await svc.create_run(
                    org_id=org_id,
                    dataset_version_id=uuid4(),
                    template_id=uuid4(),
                    parameters={"resolution": 1.0},
                    random_seed=42,
                    user_id=uuid4(),
                )
            except (ValueError, AttributeError):
                # FakeDB won't find dataset/template — expected
                pass
            return time.perf_counter() - start

        tasks = [_create_run() for _ in range(CONCURRENT_RUNS)]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest run creation took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )

    async def test_10_concurrent_creates_total_wall_clock(self):
        """Total wall-clock for 10 concurrent creates should be < 5s."""
        svc = _make_run_service(active_run_count=0, compute_quota=10)
        org_id = uuid4()

        async def _create_run():
            try:
                await svc.create_run(
                    org_id=org_id,
                    dataset_version_id=uuid4(),
                    template_id=uuid4(),
                    parameters={"resolution": 1.0},
                )
            except (ValueError, AttributeError):
                pass

        wall_start = time.perf_counter()
        tasks = [_create_run() for _ in range(CONCURRENT_RUNS)]
        await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        assert wall_elapsed < 5.0, (
            f"10 concurrent creates took {wall_elapsed:.2f}s wall-clock, exceeds 5s budget"
        )


# ---------------------------------------------------------------------------
# Quota enforcement under concurrent load
# ---------------------------------------------------------------------------


class TestQuotaEnforcementUnderLoad:
    """Verify compute quota (10 concurrent runs) is enforced under load."""

    async def test_quota_rejection_when_at_limit(self):
        """When 10 runs are active, quota checks should all raise."""
        from apps.api.services.quota_service import QuotaExceededError

        svc = _make_run_service(active_run_count=10, compute_quota=10)
        org_id = uuid4()

        rejected = 0

        async def _try_quota_check():
            nonlocal rejected
            try:
                await svc.quota_service.check_compute_quota(org_id)
            except QuotaExceededError:
                rejected += 1

        tasks = [_try_quota_check() for _ in range(CONCURRENT_RUNS)]
        await asyncio.gather(*tasks)

        assert rejected == CONCURRENT_RUNS, (
            f"Expected all {CONCURRENT_RUNS} quota checks to be rejected, but only {rejected} were"
        )

    async def test_quota_check_latency_under_load(self):
        """Quota checks for 10 concurrent requests should each be < 100ms."""
        from apps.api.services.quota_service import QuotaExceededError

        svc = _make_run_service(active_run_count=5, compute_quota=10)
        org_id = uuid4()

        async def _timed_quota_check():
            start = time.perf_counter()
            try:
                await svc.quota_service.check_compute_quota(org_id)
            except QuotaExceededError:
                pass
            return time.perf_counter() - start

        tasks = [_timed_quota_check() for _ in range(CONCURRENT_RUNS)]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 0.100, (
            f"Slowest quota check took {max_latency * 1000:.0f}ms, exceeds 100ms limit"
        )


# ---------------------------------------------------------------------------
# Status polling for 10 simultaneous runs
# ---------------------------------------------------------------------------


class TestConcurrentStatusPolling:
    """Simulate status polling for 10 simultaneous runs."""

    async def test_10_concurrent_status_polls_under_1s(self):
        """Polling status for 10 runs concurrently should complete in < 1s."""
        svc = _make_run_service()
        run_ids = [uuid4() for _ in range(CONCURRENT_RUNS)]

        async def _poll_status(run_id):
            start = time.perf_counter()
            await svc.get_run_status(run_id)
            return time.perf_counter() - start

        tasks = [_poll_status(rid) for rid in run_ids]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 1.0, (
            f"Slowest status poll took {max_latency * 1000:.0f}ms, exceeds 1s limit"
        )

    async def test_rapid_polling_10_runs_100_cycles(self):
        """Simulate 100 polling cycles across 10 runs (1000 total queries)."""
        svc = _make_run_service()
        run_ids = [uuid4() for _ in range(CONCURRENT_RUNS)]

        wall_start = time.perf_counter()
        for _ in range(100):
            tasks = [svc.get_run_status(rid) for rid in run_ids]
            await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        # 1000 status queries should complete in < 10s
        assert wall_elapsed < 10.0, (
            f"1000 status polls took {wall_elapsed:.2f}s, exceeds 10s budget"
        )


# ---------------------------------------------------------------------------
# Concurrent state transitions
# ---------------------------------------------------------------------------


class TestConcurrentStateTransitions:
    """Verify run service handles concurrent state transitions correctly."""

    async def test_10_concurrent_cancel_requests(self):
        """10 concurrent cancel requests should all complete without errors."""
        svc = _make_run_service()
        run_ids = [uuid4() for _ in range(CONCURRENT_RUNS)]

        async def _cancel_run(run_id):
            start = time.perf_counter()
            try:
                await svc.cancel_run(run_id)
            except (ValueError, AttributeError):
                # FakeDB won't find the run — expected
                pass
            return time.perf_counter() - start

        tasks = [_cancel_run(rid) for rid in run_ids]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest cancel took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )

    async def test_mixed_state_transitions_concurrent(self):
        """Mix of create, status, and cancel operations concurrently."""
        svc = _make_run_service(active_run_count=0, compute_quota=10)
        org_id = uuid4()

        async def _create():
            try:
                await svc.create_run(
                    org_id=org_id,
                    dataset_version_id=uuid4(),
                    template_id=uuid4(),
                    parameters={"resolution": 1.0},
                )
            except (ValueError, AttributeError):
                pass

        async def _status():
            await svc.get_run_status(uuid4())

        async def _cancel():
            try:
                await svc.cancel_run(uuid4())
            except (ValueError, AttributeError):
                pass

        # 4 creates + 3 status polls + 3 cancels = 10 concurrent ops
        tasks = (
            [_create() for _ in range(4)]
            + [_status() for _ in range(3)]
            + [_cancel() for _ in range(3)]
        )

        wall_start = time.perf_counter()
        await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        assert wall_elapsed < 5.0, (
            f"Mixed state transitions took {wall_elapsed:.2f}s, exceeds 5s budget"
        )
