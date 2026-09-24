"""Property-based tests for metadata caching.

**Property 29: Metadata Caching**

For any cached value, the cache must:
1. Return the stored value on a cache hit.
2. Return None on a cache miss.
3. Expire entries after the configured TTL.
4. Invalidate related keys when a mutation occurs.
5. Remain isolated between different organisations.

**Validates: Requirements 17.3**
"""

import asyncio
import time
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.services.cache_service import CacheService, CacheTTL

# ---------------------------------------------------------------------------
# Helpers: in-memory fake Redis for synchronous property tests
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal in-memory Redis substitute for property tests."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}  # key → (value, expiry_ts)

    async def get(self, key: str) -> bytes | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if expiry is not None and time.monotonic() > expiry:
            del self._store[key]
            return None
        return value.encode() if isinstance(value, str) else value

    async def setex(self, key: str, ttl: int, value: Any) -> None:
        expiry = time.monotonic() + ttl
        self._store[key] = (value, expiry)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                deleted += 1
        return deleted

    async def keys(self, pattern: str) -> list[str]:
        import fnmatch

        return [k for k in self._store if fnmatch.fnmatch(k, pattern)]

    def _force_expire(self, key: str) -> None:
        """Force a key to appear expired (for TTL tests)."""
        if key in self._store:
            value, _ = self._store[key]
            self._store[key] = (value, time.monotonic() - 1)


def make_cache() -> tuple[CacheService, FakeRedis]:
    redis = FakeRedis()
    return CacheService(redis), redis  # type: ignore[arg-type]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestMetadataCaching:
    """Property 29: Metadata Caching."""

    @given(
        value=st.one_of(
            st.text(min_size=1, max_size=100),
            st.integers(),
            st.dictionaries(
                st.text(min_size=1, max_size=10), st.text(min_size=0, max_size=20), max_size=5
            ),
            st.lists(st.integers(), max_size=5),
        ),
        ttl=st.integers(min_value=1, max_value=3600),
    )
    @settings(max_examples=60)
    def test_set_then_get_returns_same_value(self, value, ttl):
        """Property: A value stored with set() is returned unchanged by get()."""
        cache, _ = make_cache()
        key = f"test:{uuid4()}"

        run(cache.set(key, value, ttl=ttl))
        result = run(cache.get(key))

        assert result == value, f"Expected {value!r}, got {result!r}"

    @given(key=st.text(min_size=1, max_size=50))
    @settings(max_examples=40)
    def test_get_missing_key_returns_none(self, key):
        """Property: get() on a key that was never set returns None."""
        cache, _ = make_cache()
        result = run(cache.get(f"missing:{key}:{uuid4()}"))
        assert result is None

    @given(
        value=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=30)
    def test_delete_removes_key(self, value):
        """Property: After delete(), get() returns None."""
        cache, _ = make_cache()
        key = f"del:{uuid4()}"

        run(cache.set(key, value, ttl=300))
        assert run(cache.get(key)) == value

        deleted = run(cache.delete(key))
        assert deleted is True
        assert run(cache.get(key)) is None

    @given(value=st.text(min_size=1, max_size=50))
    @settings(max_examples=30)
    def test_expired_entry_returns_none(self, value):
        """Property: An entry past its TTL is treated as a cache miss."""
        cache, redis = make_cache()
        key = f"exp:{uuid4()}"

        run(cache.set(key, value, ttl=60))
        # Force expiry
        redis._force_expire(key)

        result = run(cache.get(key))
        assert result is None

    @given(
        org_id_a=st.uuids(),
        org_id_b=st.uuids(),
        dataset_id=st.uuids(),
        value_a=st.text(min_size=1, max_size=50),
        value_b=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=40)
    def test_dataset_keys_are_isolated_per_org(
        self, org_id_a, org_id_b, dataset_id, value_a, value_b
    ):
        """Property: Dataset cache keys are scoped per organisation — no cross-org leakage."""
        cache, _ = make_cache()

        key_a = CacheService.dataset_key(str(org_id_a), str(dataset_id))
        key_b = CacheService.dataset_key(str(org_id_b), str(dataset_id))

        run(cache.set(key_a, value_a, ttl=300))
        run(cache.set(key_b, value_b, ttl=300))

        assert run(cache.get(key_a)) == value_a
        assert run(cache.get(key_b)) == value_b

    @given(
        org_id=st.uuids(),
        dataset_id=st.uuids(),
        value=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=30)
    def test_invalidate_dataset_clears_entry_and_list(self, org_id, dataset_id, value):
        """Property: invalidate_dataset() removes the dataset entry and all list pages."""
        cache, _ = make_cache()
        org_str = str(org_id)
        ds_str = str(dataset_id)

        # Populate dataset entry and a list page
        run(cache.set(CacheService.dataset_key(org_str, ds_str), value, ttl=300))
        run(cache.set(CacheService.dataset_list_key(org_str, 1, 20), [value], ttl=300))

        run(cache.invalidate_dataset(org_str, ds_str))

        assert run(cache.get(CacheService.dataset_key(org_str, ds_str))) is None
        assert run(cache.get(CacheService.dataset_list_key(org_str, 1, 20))) is None

    @given(
        run_id=st.uuids(),
        status=st.sampled_from(["queued", "running", "completed", "failed", "cancelled"]),
    )
    @settings(max_examples=40)
    def test_run_status_cache_round_trip(self, run_id, status):
        """Property: Run status stored in cache is returned unchanged."""
        cache, _ = make_cache()
        key = CacheService.run_status_key(str(run_id))

        run(cache.set(key, status, ttl=CacheTTL.RUN_STATUS))
        result = run(cache.get(key))

        assert result == status

    @given(
        run_id=st.uuids(),
        status=st.sampled_from(["queued", "running", "completed"]),
    )
    @settings(max_examples=30)
    def test_invalidate_run_status_clears_entry(self, run_id, status):
        """Property: invalidate_run_status() removes the cached status."""
        cache, _ = make_cache()
        key = CacheService.run_status_key(str(run_id))

        run(cache.set(key, status, ttl=CacheTTL.RUN_STATUS))
        run(cache.invalidate_run_status(str(run_id)))

        assert run(cache.get(key)) is None

    @given(
        user_id=st.uuids(),
        orgs=st.lists(st.uuids(), min_size=1, max_size=5),
    )
    @settings(max_examples=30)
    def test_user_orgs_cache_round_trip(self, user_id, orgs):
        """Property: User org memberships stored in cache are returned unchanged."""
        cache, _ = make_cache()
        key = CacheService.user_orgs_key(str(user_id))
        value = [str(o) for o in orgs]

        run(cache.set(key, value, ttl=CacheTTL.USER_ORG_MEMBERSHIPS))
        result = run(cache.get(key))

        assert result == value

    @given(
        key=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-_"),
        value=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=30)
    def test_set_is_idempotent_with_same_value(self, key, value):
        """Property: Setting the same key twice with the same value is idempotent."""
        cache, _ = make_cache()
        unique_key = f"{key}:{uuid4()}"

        run(cache.set(unique_key, value, ttl=300))
        run(cache.set(unique_key, value, ttl=300))

        assert run(cache.get(unique_key)) == value

    @given(
        key=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-_"),
        value_a=st.text(min_size=1, max_size=50),
        value_b=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=30)
    def test_overwrite_returns_latest_value(self, key, value_a, value_b):
        """Property: The most recently set value is always returned."""
        cache, _ = make_cache()
        unique_key = f"{key}:{uuid4()}"

        run(cache.set(unique_key, value_a, ttl=300))
        run(cache.set(unique_key, value_b, ttl=300))

        assert run(cache.get(unique_key)) == value_b
