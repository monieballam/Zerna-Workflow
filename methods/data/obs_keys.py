"""Helpers for resolving observation-column keys against ``adata.obs``."""

from __future__ import annotations

import anndata as ad
import pandas as pd

BATCH_KEY_CANDIDATES = (
    "orig.ident",
    "orig_ident",
    "batch",
    "Batch",
    "batch_id",
    "sample",
    "Sample",
    "sample_name",
    "sample_id",
    "donor",
    "Donor",
    "patient",
    "Patient",
    "library",
    "library_id",
    "replicate",
    "condition",
    "HashAssignment",
)

CLUSTER_KEY_CANDIDATES = (
    "leiden",
    "louvain",
    "cluster",
    "Cluster",
    "seurat_clusters",
    "annotation_cell_type",
    "annotation_broad",
    "annotation_label",
    "celltype_level3",
    "celltype_display",
    "zr_display",
    "CellType",
    "cell_type",
)


def _n_unique_non_null(series: pd.Series) -> int:
    """Return the number of unique non-empty values in a series."""
    cleaned = series.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    if cleaned.empty:
        return 0
    return int(cleaned.nunique(dropna=True))


def _is_reasonable_grouping_column(
    adata: ad.AnnData,
    column: str,
    *,
    max_unique_ratio: float,
) -> bool:
    """Return whether an obs column looks like a grouping key instead of per-cell IDs."""
    if column not in adata.obs.columns:
        return False

    n_obs = int(adata.n_obs)
    if n_obs <= 1:
        return False

    n_unique = _n_unique_non_null(adata.obs[column])
    if n_unique < 2:
        return False
    if n_unique >= n_obs:
        return False

    return (n_unique / n_obs) <= max_unique_ratio


def _resolve_obs_key(
    adata: ad.AnnData,
    requested: str | None,
    candidates: tuple[str, ...],
    *,
    strict: bool = False,
    max_unique_ratio: float = 1.0,
) -> str | None:
    obs_columns = [str(column) for column in adata.obs.columns]
    if requested:
        requested_clean = str(requested).strip()
        if requested_clean in obs_columns and _is_reasonable_grouping_column(
            adata,
            requested_clean,
            max_unique_ratio=max_unique_ratio,
        ):
            return requested_clean

        requested_lower = requested_clean.lower()
        case_insensitive = {str(column).lower(): str(column) for column in obs_columns}
        resolved_requested = case_insensitive.get(requested_lower)
        if resolved_requested and _is_reasonable_grouping_column(
            adata,
            resolved_requested,
            max_unique_ratio=max_unique_ratio,
        ):
            return resolved_requested

        if strict:
            raise ValueError(f"obs column '{requested_clean}' not found in adata.obs")

    obs_lookup = {str(column).lower(): str(column) for column in obs_columns}
    for candidate in candidates:
        resolved = obs_lookup.get(candidate.lower())
        if resolved and _is_reasonable_grouping_column(
            adata,
            resolved,
            max_unique_ratio=max_unique_ratio,
        ):
            return resolved
    return None


def is_valid_groupby_column(
    adata: ad.AnnData,
    column: str,
    *,
    max_unique_ratio: float = 0.95,
) -> bool:
    """Return whether ``column`` is present and looks like a categorical grouping (not per-cell IDs)."""
    return _is_reasonable_grouping_column(
        adata,
        column,
        max_unique_ratio=max_unique_ratio,
    )


def resolve_batch_key(
    adata: ad.AnnData,
    requested: str | None,
    *,
    strict: bool = False,
) -> str | None:
    """Resolve a batch-like obs column, optionally raising on invalid explicit keys."""
    return _resolve_obs_key(
        adata,
        requested,
        BATCH_KEY_CANDIDATES,
        strict=strict,
        max_unique_ratio=0.8,
    )


def resolve_cluster_key(
    adata: ad.AnnData,
    requested: str | None,
    *,
    strict: bool = False,
) -> str | None:
    """Resolve a cluster-like obs column, optionally raising on invalid explicit keys."""
    return _resolve_obs_key(
        adata,
        requested,
        CLUSTER_KEY_CANDIDATES,
        strict=strict,
        max_unique_ratio=0.5,
    )
