"""Load tests for 100 concurrent users per organization.

Simulates 100 concurrent users hitting various API endpoints simultaneously
using asyncio.gather. Measures total throughput and per-request latency
under concurrent load.

Validates: Requirements 17.1, 17.2
"""

import asyncio
import time

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.slow, pytest.mark.asyncio]

CONCURRENT_USERS = 100


def _percentile(data: list[float], pct: int) -> float:
    """Return the pct-th percentile of *data* (0-100)."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


async def _timed_request(client: AsyncClient, method: str, url: str, **kwargs) -> float:
    """Fire a single request and return its latency in seconds."""
    start = time.perf_counter()
    await client.request(method, url, **kwargs)
    return time.perf_counter() - start


# ---------------------------------------------------------------------------
# Concurrent reads — GET /v1/datasets
# ---------------------------------------------------------------------------


class TestConcurrentDatasetReads:
    """100 concurrent users listing datasets simultaneously."""

    async def test_100_concurrent_dataset_list_all_under_2s(self, perf_client: AsyncClient):
        """Every request must complete in < 2s under concurrent load."""
        tasks = [
            _timed_request(perf_client, "GET", "/v1/datasets") for _ in range(CONCURRENT_USERS)
        ]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest request took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )

    async def test_100_concurrent_dataset_list_throughput(self, perf_client: AsyncClient):
        """Total wall-clock time for 100 concurrent requests should be reasonable."""
        wall_start = time.perf_counter()
        tasks = [
            _timed_request(perf_client, "GET", "/v1/datasets") for _ in range(CONCURRENT_USERS)
        ]
        latencies = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        p50 = _percentile(latencies, 50)
        p99 = _percentile(latencies, 99)
        throughput = CONCURRENT_USERS / wall_elapsed

        # Wall-clock should be much less than 100 × sequential time
        assert wall_elapsed < 10.0, (
            f"100 concurrent dataset reads took {wall_elapsed:.2f}s wall-clock "
            f"(p50={p50 * 1000:.0f}ms, p99={p99 * 1000:.0f}ms, throughput={throughput:.0f} req/s)"
        )


# ---------------------------------------------------------------------------
# Concurrent reads — GET /v1/runs
# ---------------------------------------------------------------------------


class TestConcurrentRunReads:
    """100 concurrent users listing runs simultaneously."""

    async def test_100_concurrent_run_list_all_under_2s(self, perf_client: AsyncClient):
        """Every request must complete in < 2s under concurrent load."""
        tasks = [_timed_request(perf_client, "GET", "/v1/runs") for _ in range(CONCURRENT_USERS)]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest request took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )

    async def test_100_concurrent_run_list_throughput(self, perf_client: AsyncClient):
        """Total wall-clock time for 100 concurrent requests should be reasonable."""
        wall_start = time.perf_counter()
        tasks = [_timed_request(perf_client, "GET", "/v1/runs") for _ in range(CONCURRENT_USERS)]
        latencies = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        p50 = _percentile(latencies, 50)
        p99 = _percentile(latencies, 99)

        assert wall_elapsed < 10.0, (
            f"100 concurrent run reads took {wall_elapsed:.2f}s wall-clock "
            f"(p50={p50 * 1000:.0f}ms, p99={p99 * 1000:.0f}ms)"
        )


# ---------------------------------------------------------------------------
# Concurrent writes — POST /v1/runs
# ---------------------------------------------------------------------------


class TestConcurrentRunCreation:
    """100 concurrent users creating runs simultaneously."""

    async def test_100_concurrent_run_creates_all_under_2s(self, perf_client: AsyncClient):
        """Every request must complete in < 2s under concurrent load.

        Run creation will fail (FakeDB), but we measure the request
        processing time through middleware, auth, and validation.
        """
        from uuid import uuid4

        payload = {
            "dataset_version_id": str(uuid4()),
            "template_id": str(uuid4()),
            "parameters": {"resolution": 1.0},
            "random_seed": 42,
        }

        tasks = [
            _timed_request(perf_client, "POST", "/v1/runs", json=payload)
            for _ in range(CONCURRENT_USERS)
        ]
        latencies = await asyncio.gather(*tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest run creation took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )

    async def test_100_concurrent_run_creates_throughput(self, perf_client: AsyncClient):
        """Measure throughput for 100 concurrent write requests."""
        from uuid import uuid4

        payload = {
            "dataset_version_id": str(uuid4()),
            "template_id": str(uuid4()),
            "parameters": {"resolution": 1.0},
        }

        wall_start = time.perf_counter()
        tasks = [
            _timed_request(perf_client, "POST", "/v1/runs", json=payload)
            for _ in range(CONCURRENT_USERS)
        ]
        latencies = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - wall_start

        p50 = _percentile(latencies, 50)
        p99 = _percentile(latencies, 99)

        assert wall_elapsed < 10.0, (
            f"100 concurrent run creates took {wall_elapsed:.2f}s wall-clock "
            f"(p50={p50 * 1000:.0f}ms, p99={p99 * 1000:.0f}ms)"
        )


# ---------------------------------------------------------------------------
# Mixed workload — concurrent reads and writes
# ---------------------------------------------------------------------------


class TestMixedConcurrentWorkload:
    """Simulate realistic mixed workload: 70% reads, 30% writes."""

    async def test_mixed_workload_100_users_all_under_2s(self, perf_client: AsyncClient):
        """Mixed read/write workload — no request should exceed 2s."""
        from uuid import uuid4

        read_tasks = [_timed_request(perf_client, "GET", "/v1/datasets") for _ in range(35)]
        read_tasks += [_timed_request(perf_client, "GET", "/v1/runs") for _ in range(35)]

        payload = {
            "dataset_version_id": str(uuid4()),
            "template_id": str(uuid4()),
            "parameters": {"resolution": 1.0},
        }
        write_tasks = [
            _timed_request(perf_client, "POST", "/v1/runs", json=payload) for _ in range(30)
        ]

        all_tasks = read_tasks + write_tasks
        latencies = await asyncio.gather(*all_tasks)

        max_latency = max(latencies)
        assert max_latency < 2.0, (
            f"Slowest request in mixed workload took {max_latency * 1000:.0f}ms, exceeds 2s limit"
        )
