"""Marker expression cache for precomputed score reuse.

# Feature: gap-analysis-and-verification

Caches precomputed marker scores keyed by dataset version.
Reuses cached scores for subsequent annotation runs on the same dataset.

**Validates: Requirements 17.2, 17.3**
"""

from __future__ import annotations

import hashlib
import json
import logging

from zerna_contracts.base import ZernaBaseModel
from pydantic import Field

logger = logging.getLogger(__name__)


class CachedScores(ZernaBaseModel):
    """Cached marker expression scores for a dataset version."""

    dataset_version_id: str = Field(description="Dataset version identifier")
    marker_key: str = Field(description="Hash of marker gene list used for scoring")
    per_cluster_scores: dict[str, float] = Field(description="cluster_id -> confidence score")
    per_cell_scores: dict[str, float] = Field(description="cell_id -> confidence score")


def _marker_cache_key(markers: list[str]) -> str:
    """Compute a deterministic hash key for a list of marker gene names."""
    canonical = json.dumps(sorted(markers), separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class MarkerExpressionCache:
    """In-memory cache for precomputed marker expression scores.

    Keyed by ``(dataset_version_id, marker_key)`` where ``marker_key`` is a
    deterministic hash of the sorted marker gene list.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], CachedScores] = {}

    def get(
        self,
        dataset_version_id: str,
        markers: list[str],
    ) -> CachedScores | None:
        """Retrieve cached scores for a dataset version and marker set.

        Args:
            dataset_version_id: Identifier for the dataset version.
            markers: List of marker gene names used for scoring.

        Returns:
            CachedScores if a cache hit, otherwise None.
        """
        key = (dataset_version_id, _marker_cache_key(markers))
        result = self._store.get(key)
        if result is not None:
            logger.debug("Cache hit for dataset=%s markers=%s", dataset_version_id, key[1][:8])
        else:
            logger.debug("Cache miss for dataset=%s markers=%s", dataset_version_id, key[1][:8])
        return result

    def put(
        self,
        dataset_version_id: str,
        markers: list[str],
        per_cluster_scores: dict[str, float],
        per_cell_scores: dict[str, float],
    ) -> None:
        """Store computed scores in the cache.

        Args:
            dataset_version_id: Identifier for the dataset version.
            markers: List of marker gene names used for scoring.
            per_cluster_scores: cluster_id -> confidence score mapping.
            per_cell_scores: cell_id -> confidence score mapping.
        """
        mk = _marker_cache_key(markers)
        entry = CachedScores(
            dataset_version_id=dataset_version_id,
            marker_key=mk,
            per_cluster_scores=dict(per_cluster_scores),
            per_cell_scores=dict(per_cell_scores),
        )
        self._store[(dataset_version_id, mk)] = entry
        logger.debug(
            "Cached scores for dataset=%s markers=%s (%d clusters, %d cells)",
            dataset_version_id,
            mk[:8],
            len(per_cluster_scores),
            len(per_cell_scores),
        )

    def invalidate(self, dataset_version_id: str) -> int:
        """Remove all cached entries for a dataset version.

        Returns:
            Number of entries removed.
        """
        keys_to_remove = [k for k in self._store if k[0] == dataset_version_id]
        for k in keys_to_remove:
            del self._store[k]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
