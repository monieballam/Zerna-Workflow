"""Helpers for resolving cluster-key parameters against AnnData obs columns."""

from __future__ import annotations

from typing import Any

import anndata as ad

from methods.data.obs_keys import CLUSTER_KEY_CANDIDATES, is_valid_groupby_column
from methods.data.obs_keys import resolve_cluster_key as _resolve


def detect_cluster_key(adata: ad.AnnData) -> str | None:
    """Return the first likely cluster column present in ``adata.obs``."""
    for candidate in CLUSTER_KEY_CANDIDATES:
        if candidate in adata.obs.columns:
            return candidate
    return None


def resolve_cluster_key(adata: ad.AnnData, requested: str | None) -> str | None:
    """Resolve a requested cluster key, falling back to detected cluster columns."""
    return _resolve(adata, requested, strict=False)


def detect_clustering_method_executed(adata: ad.AnnData) -> str | None:
    """Infer Leiden vs Louvain from ``zerna_clustering`` written by the clustering step."""
    bc = adata.uns.get("zerna_clustering")
    if not isinstance(bc, dict):
        return None
    me = bc.get("method_executed") or bc.get("method")
    if not isinstance(me, str):
        return None
    m = me.strip().lower()
    if m in ("leiden", "louvain"):
        return m
    return None


def _obs_column_case_insensitive(adata: ad.AnnData, name: str) -> str | None:
    obs_lookup = {str(c).lower(): str(c) for c in adata.obs.columns}
    return obs_lookup.get(str(name).strip().lower())


def resolve_annotation_cluster_key(
    adata: ad.AnnData,
    requested: str | None,
    *,
    pipeline_cluster_key_hint: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """
    Resolve the obs column used for cluster-level annotation.

    - If ``requested`` is non-empty: the column must exist and look like a grouping key.
    - If empty: prefer ``zerna_clustering`` (Leiden vs Louvain), then pipeline hint, then scan.
    """
    meta: dict[str, Any] = {
        "cluster_key_requested": (str(requested).strip() if requested else None) or None,
        "clustering_method_detected": detect_clustering_method_executed(adata),
    }
    req = meta["cluster_key_requested"]
    if req:
        resolved_col = _obs_column_case_insensitive(adata, req)
        if resolved_col is None:
            cols = [str(c) for c in adata.obs.columns]
            preview = ", ".join(cols[:40])
            if len(cols) > 40:
                preview += ", …"
            raise ValueError(
                f"annotation_cluster_key '{req}' is not present in adata.obs. "
                f"Available columns (preview): {preview}"
            )
        if not is_valid_groupby_column(adata, resolved_col):
            raise ValueError(
                f"annotation_cluster_key '{resolved_col}' is present but does not look like a "
                "valid cluster column (too many unique values per cell). Choose a single "
                "label-per-cluster column such as `leiden` or `louvain`."
            )
        meta["cluster_key_resolved"] = resolved_col
        return resolved_col, meta

    method = meta["clustering_method_detected"]
    if method == "louvain" and "louvain" in adata.obs.columns:
        if is_valid_groupby_column(adata, "louvain"):
            meta["cluster_key_resolved"] = "louvain"
            return "louvain", meta
    if method == "leiden" and "leiden" in adata.obs.columns:
        if is_valid_groupby_column(adata, "leiden"):
            meta["cluster_key_resolved"] = "leiden"
            return "leiden", meta

    if method == "louvain":
        for cand in ("louvain", "leiden", "cluster"):
            if cand in adata.obs.columns and is_valid_groupby_column(adata, cand):
                meta["cluster_key_resolved"] = cand
                return cand, meta
    if method == "leiden":
        for cand in ("leiden", "louvain", "cluster"):
            if cand in adata.obs.columns and is_valid_groupby_column(adata, cand):
                meta["cluster_key_resolved"] = cand
                return cand, meta

    hint = str(pipeline_cluster_key_hint).strip() if pipeline_cluster_key_hint else None
    if hint:
        hk = _obs_column_case_insensitive(adata, hint)
        if hk is not None and is_valid_groupby_column(adata, hk):
            meta["cluster_key_resolved"] = hk
            return hk, meta

    auto = _resolve(adata, None, strict=False)
    meta["cluster_key_resolved"] = auto
    return auto, meta
