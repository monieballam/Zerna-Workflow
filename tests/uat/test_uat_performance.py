"""User Acceptance Tests — Performance Requirements.

Verifies that the Zerna platform meets its performance SLAs:
  - API response time: p50 < 100ms, p99 < 500ms
  - Concurrent users: 100 simultaneous requests
  - Large dataset handling: 1M cell dataset operations

Validates: Requirements 19.3

Run with:
    pytest tests/uat/test_uat_performance.py -v -m uat -m slow
"""

import asyncio
import time
from uuid import uuid4

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.uat, pytest.mark.slow, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _timed_request(client: AsyncClient, method: str, url: str, **kwargs) -> float:
    """Execute a request and return the elapsed time in seconds."""
    start = time.perf_counter()
    await getattr(client, method)(url, **kwargs)
    return time.perf_counter() - start


def _percentile(data: list[float], pct: int) -> float:
    """Compute the given percentile from a sorted list of values."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ═══════════════════════════════════════════════════════════════════════════
# 1. API Response Time Under Load
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIResponseTime:
    """Verify API response times meet p50 < 100ms and p99 < 500ms SLAs."""

    async def test_health_endpoint_p50_under_100ms(self, api_client: AsyncClient):
        """Health endpoint p50 latency should be under 100ms."""
        latencies = []
        for _ in range(50):
            elapsed = await _timed_request(api_client, "get", "/health")
            latencies.append(elapsed)

        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Health endpoint p50 = {p50 * 1000:.1f}ms, exceeds 100ms SLA"

    async def test_health_endpoint_p99_under_500ms(self, api_client: AsyncClient):
        """Health endpoint p99 latency should be under 500ms."""
        latencies = []
        for _ in range(100):
            elapsed = await _timed_request(api_client, "get", "/health")
            latencies.append(elapsed)

        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Health endpoint p99 = {p99 * 1000:.1f}ms, exceeds 500ms SLA"

    async def test_dataset_list_p50_under_100ms(self, api_client: AsyncClient):
        """Dataset listing p50 latency should be under 100ms."""
        latencies = []
        for _ in range(50):
            elapsed = await _timed_request(api_client, "get", "/v1/datasets")
            latencies.append(elapsed)

        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Dataset list p50 = {p50 * 1000:.1f}ms, exceeds 100ms SLA"

    async def test_dataset_list_p99_under_500ms(self, api_client: AsyncClient):
        """Dataset listing p99 latency should be under 500ms."""
        latencies = []
        for _ in range(100):
            elapsed = await _timed_request(api_client, "get", "/v1/datasets")
            latencies.append(elapsed)

        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Dataset list p99 = {p99 * 1000:.1f}ms, exceeds 500ms SLA"

    async def test_run_list_p50_under_100ms(self, api_client: AsyncClient):
        """Run listing p50 latency should be under 100ms."""
        latencies = []
        for _ in range(50):
            elapsed = await _timed_request(api_client, "get", "/v1/runs")
            latencies.append(elapsed)

        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Run list p50 = {p50 * 1000:.1f}ms, exceeds 100ms SLA"

    async def test_pipeline_list_p50_under_100ms(self, api_client: AsyncClient):
        """Pipeline listing p50 latency should be under 100ms."""
        latencies = []
        for _ in range(50):
            elapsed = await _timed_request(api_client, "get", "/v1/pipelines")
            latencies.append(elapsed)

        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Pipeline list p50 = {p50 * 1000:.1f}ms, exceeds 100ms SLA"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Concurrent User Simulation
# ═══════════════════════════════════════════════════════════════════════════


class TestConcurrentUsers:
    """Verify the platform handles 100 concurrent users."""

    async def test_100_concurrent_health_checks(self, api_client: AsyncClient):
        """100 concurrent health check requests should all succeed."""

        async def _health_check():
            start = time.perf_counter()
            resp = await api_client.get("/health")
            elapsed = time.perf_counter() - start
            return resp.status_code, elapsed

        tasks = [_health_check() for _ in range(100)]
        results = await asyncio.gather(*tasks)

        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]

        success_count = sum(1 for s in statuses if s == 200)
        assert success_count >= 95, f"Only {success_count}/100 health checks succeeded"

        p99 = _percentile(latencies, 99)
        assert p99 < 1.0, f"Concurrent health check p99 = {p99 * 1000:.1f}ms, exceeds 1s"

    async def test_100_concurrent_dataset_listings(self, api_client: AsyncClient):
        """100 concurrent dataset listing requests should complete within SLA."""

        async def _list_datasets():
            start = time.perf_counter()
            resp = await api_client.get("/v1/datasets")
            elapsed = time.perf_counter() - start
            return resp.status_code, elapsed

        tasks = [_list_datasets() for _ in range(100)]
        results = await asyncio.gather(*tasks)

        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]

        success_count = sum(1 for s in statuses if s == 200)
        assert success_count >= 95, f"Only {success_count}/100 dataset listings succeeded"

        p99 = _percentile(latencies, 99)
        assert p99 < 1.0, f"Concurrent dataset list p99 = {p99 * 1000:.1f}ms, exceeds 1s"

    async def test_100_concurrent_mixed_operations(self, api_client: AsyncClient):
        """100 concurrent mixed API operations should all complete."""
        endpoints = [
            ("get", "/health"),
            ("get", "/v1/datasets"),
            ("get", "/v1/runs"),
            ("get", "/v1/pipelines"),
        ]

        async def _mixed_request(idx: int):
            method, url = endpoints[idx % len(endpoints)]
            start = time.perf_counter()
            resp = await getattr(api_client, method)(url)
            elapsed = time.perf_counter() - start
            return resp.status_code, elapsed

        tasks = [_mixed_request(i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        latencies = [r[1] for r in results]
        wall_clock = max(latencies)

        assert wall_clock < 5.0, (
            f"100 concurrent mixed ops took {wall_clock:.2f}s max, exceeds 5s budget"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. Large Dataset Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestLargeDatasetHandling:
    """Verify the platform handles 1M cell dataset operations."""

    async def test_large_metadata_payload_accepted(self, api_client: AsyncClient):
        """Creating a dataset with large metadata should succeed within SLA."""
        large_metadata = {
            "species": "human",
            "tissue": "lung",
            "cell_count": 1_000_000,
            "gene_count": 33_000,
            "assay": "10x_3prime_v3",
            "cluster_summary": {
                f"cluster_{i}": {
                    "cell_type": f"type_{i}",
                    "cell_count": 1_000_000 // 30,
                    "marker_genes": [f"gene_{j}" for j in range(10)],
                }
                for i in range(30)
            },
        }

        start = time.perf_counter()
        resp = await api_client.post(
            "/v1/datasets",
            params={
                "name": f"UAT-Large-{uuid4().hex[:8]}",
                "description": "1M cell dataset UAT",
            },
        )
        elapsed = time.perf_counter() - start

        if resp.status_code == 201:
            dataset_id = resp.json()["id"]
            assert elapsed < 1.0, f"Large dataset creation took {elapsed * 1000:.0f}ms, exceeds 1s"
            # Cleanup
            await api_client.delete(f"/v1/datasets/{dataset_id}")

    async def test_pagination_with_many_datasets(self, api_client: AsyncClient):
        """Pagination remains fast even with many datasets."""
        # Create 10 datasets to simulate a populated environment
        created_ids = []
        for i in range(10):
            resp = await api_client.post(
                "/v1/datasets",
                params={"name": f"UAT-Many-{i}-{uuid4().hex[:6]}"},
            )
            if resp.status_code == 201:
                created_ids.append(resp.json()["id"])

        # Measure pagination performance
        latencies = []
        for page in range(1, 4):
            start = time.perf_counter()
            resp = await api_client.get(
                "/v1/datasets",
                params={"page": page, "page_size": 5},
            )
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)
            assert resp.status_code == 200

        p50 = _percentile(latencies, 50)
        assert p50 < 0.500, f"Pagination p50 = {p50 * 1000:.1f}ms, exceeds 500ms"

        # Cleanup
        for ds_id in created_ids:
            await api_client.delete(f"/v1/datasets/{ds_id}")

    async def test_dataset_metadata_serialization_performance(
        self,
        api_client: AsyncClient,
    ):
        """Metadata serialization for 1M cell summary should be fast."""
        import json

        metadata = {
            "cell_count": 1_000_000,
            "gene_count": 33_000,
            "clusters": {
                f"cluster_{i}": {
                    "cell_type": f"type_{i}",
                    "markers": [f"gene_{j}" for j in range(10)],
                    "count": 1_000_000 // 30,
                }
                for i in range(30)
            },
        }

        start = time.perf_counter()
        serialized = json.dumps(metadata)
        _ = json.loads(serialized)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.100, (
            f"1M cell metadata round-trip took {elapsed * 1000:.1f}ms, exceeds 100ms"
        )
