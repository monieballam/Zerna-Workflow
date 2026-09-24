"""Redis caching service with TTL management and cache invalidation.

Provides a unified interface for caching frequently accessed data with
configurable TTLs per data type and automatic invalidation on mutations.
"""

import json
import logging
from enum import IntEnum
from typing import Any, cast

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class CacheTTL(IntEnum):
    """TTL values (in seconds) for different data types."""

    DATASET_SUMMARY = 300  # 5 minutes
    RUN_STATUS = 30  # 30 seconds
    USER_ORG_MEMBERSHIPS = 600  # 10 minutes
    PIPELINE_TEMPLATE = 600  # 10 minutes
    KNOWLEDGE_PACK = 3600  # 1 hour
    DEFAULT = 300  # 5 minutes


class CacheService:
    """Redis-backed cache service with typed TTLs and invalidation support."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Core get / set / delete
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Retrieve a cached value by key.

        Returns:
            Deserialized value, or None if key is absent / expired.
        """
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.warning("Cache GET failed for key=%s", key, exc_info=True)
            return None

    async def set(self, key: str, value: Any, ttl: int = CacheTTL.DEFAULT) -> bool:
        """Store a value in the cache with a TTL.

        Args:
            key:   Cache key.
            value: JSON-serialisable value.
            ttl:   Time-to-live in seconds.

        Returns:
            True on success, False on error.
        """
        try:
            serialized = json.dumps(value, default=str)
            await self._redis.setex(key, ttl, serialized)
            return True
        except Exception:
            logger.warning("Cache SET failed for key=%s", key, exc_info=True)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a single cache key.

        Returns:
            True if the key existed and was deleted, False otherwise.
        """
        try:
            deleted = int(await self._redis.delete(key))
            return deleted > 0
        except Exception:
            logger.warning("Cache DELETE failed for key=%s", key, exc_info=True)
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern.

        Returns:
            Number of keys deleted.
        """
        try:
            keys = await self._redis.keys(pattern)
            if not keys:
                return 0
            return cast(int, await self._redis.delete(*keys))
        except Exception:
            logger.warning("Cache DELETE_PATTERN failed for pattern=%s", pattern, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Typed key builders
    # ------------------------------------------------------------------

    @staticmethod
    def dataset_key(org_id: str, dataset_id: str) -> str:
        return f"dataset:{org_id}:{dataset_id}"

    @staticmethod
    def dataset_list_key(org_id: str, page: int, page_size: int) -> str:
        return f"dataset_list:{org_id}:{page}:{page_size}"

    @staticmethod
    def run_status_key(run_id: str) -> str:
        return f"run_status:{run_id}"

    @staticmethod
    def run_detail_key(org_id: str, run_id: str) -> str:
        return f"run_detail:{org_id}:{run_id}"

    @staticmethod
    def run_list_key(
        org_id: str, status: str, dataset_version_id: str, limit: int, offset: int
    ) -> str:
        return f"run_list:{org_id}:{status}:{dataset_version_id}:{limit}:{offset}"

    @staticmethod
    def knowledge_pack_list_key(pack_type: str, limit: int, offset: int) -> str:
        return f"kp_list:{pack_type}:{limit}:{offset}"

    @staticmethod
    def user_orgs_key(user_id: str) -> str:
        return f"user_orgs:{user_id}"

    # ------------------------------------------------------------------
    # Invalidation helpers
    # ------------------------------------------------------------------

    async def invalidate_dataset(self, org_id: str, dataset_id: str) -> None:
        """Invalidate all cache entries related to a dataset."""
        await self.delete(self.dataset_key(org_id, dataset_id))
        # Invalidate all list pages for this org
        await self.delete_pattern(f"dataset_list:{org_id}:*")

    async def invalidate_run_status(self, run_id: str) -> None:
        """Invalidate cached run status and detail."""
        await self.delete(self.run_status_key(run_id))
        # Invalidate run detail cache for all orgs
        await self.delete_pattern(f"run_detail:*:{run_id}")
        # Invalidate run list caches (broad invalidation)
        await self.delete_pattern("run_list:*")

    async def invalidate_knowledge_packs(self) -> None:
        """Invalidate all knowledge pack list caches."""
        await self.delete_pattern("kp_list:*")

    async def invalidate_user_orgs(self, user_id: str) -> None:
        """Invalidate cached user organisation memberships."""
        await self.delete(self.user_orgs_key(user_id))
