"""Performance tests for API endpoint latency.

Measures p50 and p99 latency across multiple iterations to verify
that the API layer meets performance targets:
  - p50 < 100ms
  - p99 < 500ms

Validates: Requirements 17.1, 17.2
"""

import time

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.slow, pytest.mark.asyncio]

ITERATIONS = 100


async def _measure_latencies(client: AsyncClient, method: str, url: str, **kwargs) -> list[float]:
    """Fire ITERATIONS requests and return latencies in seconds."""
    latencies: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        await client.request(method, url, **kwargs)
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)
    return latencies


def _percentile(data: list[float], pct: int) -> float:
    """Return the pct-th percentile of *data* (0-100)."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Health endpoint latency
# ---------------------------------------------------------------------------


class TestHealthEndpointLatency:
    """Health endpoint should be the fastest — no auth, no DB."""

    async def test_health_p50_under_100ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/health")
        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Health p50 latency {p50 * 1000:.1f}ms exceeds 100ms target"

    async def test_health_p99_under_500ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/health")
        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Health p99 latency {p99 * 1000:.1f}ms exceeds 500ms target"


# ---------------------------------------------------------------------------
# Dataset list endpoint latency
# ---------------------------------------------------------------------------


class TestDatasetListLatency:
    """GET /v1/datasets — measures routing + auth middleware + serialization."""

    async def test_dataset_list_p50_under_100ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/v1/datasets")
        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Dataset list p50 latency {p50 * 1000:.1f}ms exceeds 100ms target"

    async def test_dataset_list_p99_under_500ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/v1/datasets")
        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Dataset list p99 latency {p99 * 1000:.1f}ms exceeds 500ms target"


# ---------------------------------------------------------------------------
# Run list endpoint latency
# ---------------------------------------------------------------------------


class TestRunListLatency:
    """GET /v1/runs — measures routing + auth middleware + serialization."""

    async def test_run_list_p50_under_100ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/v1/runs")
        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Run list p50 latency {p50 * 1000:.1f}ms exceeds 100ms target"

    async def test_run_list_p99_under_500ms(self, perf_client: AsyncClient):
        latencies = await _measure_latencies(perf_client, "GET", "/v1/runs")
        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Run list p99 latency {p99 * 1000:.1f}ms exceeds 500ms target"


# ---------------------------------------------------------------------------
# Authentication endpoint latency
# ---------------------------------------------------------------------------


class TestAuthEndpointLatency:
    """POST /v1/auth/login — measures auth processing overhead."""

    async def test_auth_login_p50_under_100ms(self, perf_client: AsyncClient):
        # Login will fail (no real DB), but we measure the request processing time
        payload = {"email": "perf@zerna.test", "password": "testpassword123"}
        latencies = await _measure_latencies(
            perf_client,
            "POST",
            "/v1/auth/login",
            json=payload,
        )
        p50 = _percentile(latencies, 50)
        assert p50 < 0.100, f"Auth login p50 latency {p50 * 1000:.1f}ms exceeds 100ms target"

    async def test_auth_login_p99_under_500ms(self, perf_client: AsyncClient):
        payload = {"email": "perf@zerna.test", "password": "testpassword123"}
        latencies = await _measure_latencies(
            perf_client,
            "POST",
            "/v1/auth/login",
            json=payload,
        )
        p99 = _percentile(latencies, 99)
        assert p99 < 0.500, f"Auth login p99 latency {p99 * 1000:.1f}ms exceeds 500ms target"
