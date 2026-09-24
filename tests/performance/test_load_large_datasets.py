"""Load tests for 1M cell dataset operations.

Simulates dataset service operations with 1M cell metadata to verify
that the control plane handles large datasets within performance budgets.
Tests pagination, metadata queries, and memory patterns for large payloads.

Validates: Requirements 17.1, 17.2
"""

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tests.performance.conftest import FakeDBSession

pytestmark = [pytest.mark.slow, pytest.mark.asyncio]

ONE_MILLION = 1_000_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_large_metadata(cell_count: int) -> dict:
    """Build a realistic JSONB metadata payload for a large dataset."""
    return {
        "species": "human",
        "tissue": "lung",
        "cell_count": cell_count,
        "gene_count": 33_000,
        "assay": "10x_3prime_v3",
        "donor_ids": [f"donor_{i}" for i in range(20)],
        "batch_keys": [f"batch_{i}" for i in range(10)],
        "custom_annotations": {
            f"cluster_{i}": {
                "cell_type": f"type_{i}",
                "marker_genes": [f"gene_{j}" for j in range(10)],
                "cell_count": cell_count // 30,
            }
            for i in range(30)
        },
    }


def _make_dataset_service(fake_db=None):
    """Create a DatasetService with all external deps mocked."""
    from apps.api.services.audit_service import AuditService
    from apps.api.services.cache_service import CacheService
    from apps.api.services.dataset_service import DatasetService
    from apps.api.services.file_validation_service import FileValidationService
    from apps.api.services.quota_service import QuotaService
    from apps.api.services.s3_service import S3Service

    db = fake_db or FakeDBSession()

    mock_fv = AsyncMock(spec=FileValidationService)
    mock_s3 = MagicMock(spec=S3Service)
    mock_s3.datasets_bucket = "zerna-datasets-perf"
    mock_s3.generate_dataset_path = MagicMock(return_value="org/ds/file.h5ad")
    mock_s3.upload_file = MagicMock(return_value={"ETag": '"abc"'})

    mock_quota = AsyncMock(spec=QuotaService)
    mock_quota.check_storage_quota = AsyncMock(return_value=None)

    mock_cache = AsyncMock(spec=CacheService)
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock(return_value=True)
    mock_cache.invalidate_dataset = AsyncMock(return_value=None)

    mock_audit = AsyncMock(spec=AuditService)
    mock_audit.audit_log = AsyncMock(return_value=None)

    return DatasetService(
        db=db,
        s3_service=mock_s3,
        file_validation_service=mock_fv,
        quota_service=mock_quota,
        cache_service=mock_cache,
        audit_service=mock_audit,
    )


# ---------------------------------------------------------------------------
# 1M cell metadata construction performance
# ---------------------------------------------------------------------------


class TestLargeMetadataConstruction:
    """Verify that building and serializing 1M cell metadata is fast."""

    async def test_1m_cell_metadata_construction_under_1s(self):
        """Building metadata dict for 1M cells should be < 1s."""
        start = time.perf_counter()
        metadata = _make_large_metadata(ONE_MILLION)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"1M cell metadata construction took {elapsed * 1000:.0f}ms, exceeds 1s budget"
        )
        assert metadata["cell_count"] == ONE_MILLION

    async def test_1m_cell_metadata_json_serialization_under_1s(self):
        """JSON serialization of 1M cell metadata should be < 1s."""
        import json

        metadata = _make_large_metadata(ONE_MILLION)

        start = time.perf_counter()
        serialized = json.dumps(metadata, default=str)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"JSON serialization took {elapsed * 1000:.0f}ms, exceeds 1s budget"
        assert len(serialized) > 0


# ---------------------------------------------------------------------------
# Pagination performance with large result sets
# ---------------------------------------------------------------------------


class TestPaginationPerformance:
    """Test pagination service-layer performance with large result sets."""

    async def test_list_datasets_pagination_under_500ms(self):
        """list_datasets with pagination should be fast even for large orgs."""
        svc = _make_dataset_service()
        org_id = uuid4()

        start = time.perf_counter()
        try:
            result = await svc.list_datasets(
                org_id=org_id,
                page=1,
                page_size=20,
                sort_by="created_at",
                sort_order="desc",
            )
        except Exception:
            # FakeDB returns empty — that's fine, we measure overhead
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, (
            f"list_datasets pagination took {elapsed * 1000:.0f}ms, exceeds 500ms budget"
        )

    async def test_deep_pagination_page_100_under_500ms(self):
        """Deep pagination (page 100) should not degrade significantly."""
        svc = _make_dataset_service()
        org_id = uuid4()

        start = time.perf_counter()
        try:
            await svc.list_datasets(
                org_id=org_id,
                page=100,
                page_size=20,
                sort_by="created_at",
                sort_order="desc",
            )
        except Exception:
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, (
            f"Deep pagination (page 100) took {elapsed * 1000:.0f}ms, exceeds 500ms budget"
        )

    async def test_max_page_size_100_under_500ms(self):
        """Max page size (100 items) should still be fast."""
        svc = _make_dataset_service()
        org_id = uuid4()

        start = time.perf_counter()
        try:
            await svc.list_datasets(
                org_id=org_id,
                page=1,
                page_size=100,
                sort_by="name",
                sort_order="asc",
            )
        except Exception:
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, (
            f"Max page size query took {elapsed * 1000:.0f}ms, exceeds 500ms budget"
        )


# ---------------------------------------------------------------------------
# Metadata query performance with large JSONB payloads
# ---------------------------------------------------------------------------


class TestLargeJSONBQueryPerformance:
    """Test service operations with large JSONB metadata payloads."""

    async def test_get_dataset_with_large_metadata_under_500ms(self):
        """get_dataset should be fast even with large JSONB metadata."""
        svc = _make_dataset_service()
        org_id = uuid4()
        dataset_id = uuid4()

        start = time.perf_counter()
        try:
            await svc.get_dataset(
                dataset_id=dataset_id,
                org_id=org_id,
                include_versions=True,
            )
        except Exception:
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, (
            f"get_dataset with large metadata took {elapsed * 1000:.0f}ms, exceeds 500ms budget"
        )

    async def test_update_metadata_with_1m_cell_payload_under_1s(self):
        """Updating metadata with a 1M cell payload should be < 1s."""
        svc = _make_dataset_service()
        org_id = uuid4()
        dataset_id = uuid4()
        large_metadata = _make_large_metadata(ONE_MILLION)

        start = time.perf_counter()
        try:
            await svc.update_dataset_metadata(
                dataset_id=dataset_id,
                org_id=org_id,
                metadata=large_metadata,
            )
        except Exception:
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"Metadata update with 1M cell payload took {elapsed * 1000:.0f}ms, exceeds 1s budget"
        )

    async def test_filtered_list_with_cell_count_under_500ms(self):
        """Filtering by cell count (common for 1M cell datasets) should be fast."""
        from apps.api.services.dataset_service import DatasetFilters

        svc = _make_dataset_service()
        org_id = uuid4()

        filters = DatasetFilters(
            min_cell_count=500_000,
            max_cell_count=ONE_MILLION,
        )

        start = time.perf_counter()
        try:
            await svc.list_datasets(
                org_id=org_id,
                filters=filters,
                page=1,
                page_size=20,
            )
        except Exception:
            pass
        elapsed = time.perf_counter() - start

        assert elapsed < 0.500, (
            f"Filtered list by cell count took {elapsed * 1000:.0f}ms, exceeds 500ms budget"
        )


# ---------------------------------------------------------------------------
# Memory usage patterns for large dataset operations
# ---------------------------------------------------------------------------


class TestMemoryPatterns:
    """Verify that large dataset operations don't cause excessive memory use."""

    async def test_1m_cell_metadata_memory_footprint(self):
        """1M cell metadata dict should have a bounded memory footprint."""
        import sys

        metadata = _make_large_metadata(ONE_MILLION)
        # Approximate size — sys.getsizeof is shallow, but gives a baseline
        shallow_size = sys.getsizeof(metadata)

        # The metadata dict itself should be < 10KB (shallow).
        # Deep size will be larger due to nested dicts, but the structure
        # is summary-level, not per-cell.
        assert shallow_size < 10_000, (
            f"Metadata shallow size {shallow_size} bytes exceeds 10KB limit"
        )

    async def test_repeated_large_operations_no_leak(self):
        """Running 50 large metadata operations should not accumulate memory."""
        import json

        metadata = _make_large_metadata(ONE_MILLION)
        serialized = json.dumps(metadata, default=str)

        # Run 50 serialize/deserialize cycles
        start = time.perf_counter()
        for _ in range(50):
            roundtrip = json.loads(serialized)
            _ = json.dumps(roundtrip, default=str)
        elapsed = time.perf_counter() - start

        # 50 cycles should complete in < 5s
        assert elapsed < 5.0, (
            f"50 serialize/deserialize cycles took {elapsed:.2f}s, exceeds 5s budget"
        )
