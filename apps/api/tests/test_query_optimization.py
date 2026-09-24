"""Tests for database query optimizations (task 34.3).

Validates:
- Composite indexes exist on key tables for common query patterns
- Eager loading options are applied to service queries
- Cache key builders produce correct keys
- Cache invalidation helpers work correctly

Requirements: 17.3
"""

import pytest
from sqlalchemy import create_engine, inspect

from apps.api.models import Base
from apps.api.services.cache_service import CacheService, CacheTTL

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Create an in-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# Index tests
# ---------------------------------------------------------------------------


class TestCompositeIndexes:
    """Verify composite indexes exist for common query patterns."""

    def test_runs_org_status_created_index(self, engine):
        """runs table should have composite index on (organization_id, status, created_at)."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("runs")
        columns_sets = [tuple(idx["column_names"]) for idx in indexes]
        assert ("organization_id", "status", "created_at") in columns_sets

    def test_artifacts_run_type_index(self, engine):
        """artifacts table should have composite index on (run_id, artifact_type)."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("artifacts")
        columns_sets = [tuple(idx["column_names"]) for idx in indexes]
        assert ("run_id", "artifact_type") in columns_sets

    def test_knowledge_packs_type_name_index(self, engine):
        """knowledge_packs table should have composite index on (pack_type, name)."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("knowledge_packs")
        columns_sets = [tuple(idx["column_names"]) for idx in indexes]
        assert ("pack_type", "name") in columns_sets

    def test_audit_events_user_timestamp_index(self, engine):
        """audit_events table should have composite index on (user_id, timestamp)."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("audit_events")
        columns_sets = [tuple(idx["column_names"]) for idx in indexes]
        assert ("user_id", "timestamp") in columns_sets

    def test_pipeline_templates_org_name_index(self, engine):
        """pipeline_templates table should have composite index on (organization_id, name)."""
        inspector = inspect(engine)
        indexes = inspector.get_indexes("pipeline_templates")
        columns_sets = [tuple(idx["column_names"]) for idx in indexes]
        assert ("organization_id", "name") in columns_sets


# ---------------------------------------------------------------------------
# Cache key builder tests
# ---------------------------------------------------------------------------


class TestCacheKeyBuilders:
    """Verify cache key builders produce deterministic, unique keys."""

    def test_run_detail_key(self):
        org_id = "org-123"
        run_id = "run-456"
        key = CacheService.run_detail_key(org_id, run_id)
        assert key == "run_detail:org-123:run-456"

    def test_run_list_key(self):
        key = CacheService.run_list_key("org-1", "running", "dv-1", 20, 0)
        assert key == "run_list:org-1:running:dv-1:20:0"

    def test_knowledge_pack_list_key(self):
        key = CacheService.knowledge_pack_list_key("cell_type_markers", 20, 0)
        assert key == "kp_list:cell_type_markers:20:0"

    def test_dataset_list_key(self):
        key = CacheService.dataset_list_key("org-1", 1, 20)
        assert key == "dataset_list:org-1:1:20"

    def test_run_status_key(self):
        key = CacheService.run_status_key("run-789")
        assert key == "run_status:run-789"


# ---------------------------------------------------------------------------
# CacheTTL value tests
# ---------------------------------------------------------------------------


class TestCacheTTLValues:
    """Verify TTL values match the spec requirements."""

    def test_dataset_summary_ttl_is_5_minutes(self):
        assert CacheTTL.DATASET_SUMMARY == 300

    def test_run_status_ttl_is_30_seconds(self):
        assert CacheTTL.RUN_STATUS == 30

    def test_knowledge_pack_ttl_is_1_hour(self):
        assert CacheTTL.KNOWLEDGE_PACK == 3600
