"""Per-cluster DE / marker gene lists (shared by annotation + explorer evidence backfill)."""

from __future__ import annotations

import logging
from typing import Any

import anndata as ad
import numpy as np

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(numeric) or np.isinf(numeric):
        return None
    return numeric


def _compute_cluster_markers(
    adata: ad.AnnData,
    cluster_key: str,
    top_n: int,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Compute top marker genes per cluster using scanpy with a deterministic fallback."""
    if cluster_key not in adata.obs.columns:
        return {}, []

    marker_adata = adata.raw.to_adata() if getattr(adata, "raw", None) is not None else adata.copy()
    marker_adata.obs[cluster_key] = adata.obs[cluster_key].astype(str).values

    if marker_adata.obs[cluster_key].nunique() < 2:
        return {}, []

    try:
        import scanpy as sc

        sc.tl.rank_genes_groups(
            marker_adata,
            groupby=cluster_key,
            method="wilcoxon",
            n_genes=top_n,
            use_raw=False,
        )

        cluster_markers: dict[str, list[str]] = {}
        rows: list[dict[str, Any]] = []
        for cluster_id in sorted(marker_adata.obs[cluster_key].astype(str).unique(), key=str):
            group_df = sc.get.rank_genes_groups_df(marker_adata, group=str(cluster_id))
            if "logfoldchanges" in group_df.columns:
                positive_mask = group_df["logfoldchanges"].fillna(0) > 0
                if positive_mask.any():
                    group_df = group_df.loc[positive_mask]
            elif "scores" in group_df.columns:
                positive_mask = group_df["scores"].fillna(0) > 0
                if positive_mask.any():
                    group_df = group_df.loc[positive_mask]
            group_df = group_df.head(top_n)
            genes = [str(gene) for gene in group_df["names"].tolist() if str(gene)]
            cluster_markers[str(cluster_id)] = genes
            for _, row in group_df.iterrows():
                rows.append(
                    {
                        "cluster": str(cluster_id),
                        "gene": str(row["names"]),
                        "score": _safe_float(row.get("scores")),
                        "logfoldchange": _safe_float(row.get("logfoldchanges")),
                        "pval_adj": _safe_float(row.get("pvals_adj")),
                    }
                )
        return cluster_markers, rows
    except Exception as exc:
        logger.warning(
            "rank_genes_groups failed during annotation marker extraction: %s. Falling back to mean-difference markers.",
            exc,
        )
        return _fallback_cluster_markers(marker_adata, cluster_key, top_n)


def _fallback_cluster_markers(
    adata: ad.AnnData,
    cluster_key: str,
    top_n: int,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Fallback cluster marker extraction when scanpy DE is unavailable."""
    X = adata.X.toarray() if hasattr(adata.X, "toarray") else np.asarray(adata.X)
    var_names = np.asarray(adata.var_names.astype(str))
    labels = adata.obs[cluster_key].astype(str).values

    cluster_markers: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    for cluster_id in sorted(np.unique(labels), key=str):
        in_cluster = labels == cluster_id
        out_cluster = ~in_cluster
        if in_cluster.sum() == 0:
            continue

        cluster_mean = X[in_cluster].mean(axis=0)
        rest_mean = (
            X[out_cluster].mean(axis=0) if out_cluster.any() else np.zeros(X.shape[1], dtype=float)
        )
        score = np.asarray(cluster_mean - rest_mean).ravel()
        positive_indices = np.where(score > 0)[0]
        ordered_indices = positive_indices[np.argsort(score[positive_indices])[::-1]]
        top_indices = ordered_indices[:top_n]
        genes = [str(var_names[index]) for index in top_indices]

        cluster_markers[str(cluster_id)] = genes
        for index in top_indices:
            rows.append(
                {
                    "cluster": str(cluster_id),
                    "gene": str(var_names[index]),
                    "score": _safe_float(score[index]),
                    "logfoldchange": _safe_float(score[index]),
                    "pval_adj": None,
                }
            )

    return cluster_markers, rows


__all__ = ["_compute_cluster_markers"]
