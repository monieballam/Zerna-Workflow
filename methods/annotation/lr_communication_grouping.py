"""Resolve LIANA ``groupby`` obs column: Zerna CCI tiers vs cluster keys.

Annotation contract (AnnotationAgentV3 + :func:`build_cci_celltype_columns`)
---------------------------------------------------------------------------
Canonical LR grouping modes map to ``adata.obs`` columns as follows:

- ``cci_major``  → ``cci_celltype_major``  (from ``auto_level1``)
- ``cci_minor``  → ``cci_celltype_minor``  (from ``auto_level1`` + ``auto_level2``)
- ``cci_fine``   → ``cci_celltype_fine``   (from L1/L2 + ``auto_level3`` when informative)

These columns are written when ``auto_level1`` (and related levels) exist after
annotation; they are not implied by clustering alone.

Fallback policy
---------------
- **cluster** and **auto** may use the resolved cluster column (Leiden / Louvain / …).
- **cci_major** / **cci_minor** / **cci_fine** never fall back to cluster: missing or
  invalid annotation columns raise ``ValueError`` with an explicit message.
- **lineage_subcluster** (optional, advanced) — uses ``obs[lineage_subcluster]`` from P2
  lineage reclustering when present and valid; **not** part of **auto** priority; no cluster
  fallback.
"""

from __future__ import annotations

from typing import Any, TypedDict

import anndata as ad

from methods.annotation.hierarchy_columns import LINEAGE_SUBCLUSTER_COL
from methods.annotation.cluster_keys import resolve_cluster_key
from methods.data.obs_keys import is_valid_groupby_column

CCI_CELLTYPE_MAJOR = "cci_celltype_major"
CCI_CELLTYPE_MINOR = "cci_celltype_minor"
CCI_CELLTYPE_FINE = "cci_celltype_fine"

CCI_COLUMN: dict[str, str] = {
    "cci_major": CCI_CELLTYPE_MAJOR,
    "cci_minor": CCI_CELLTYPE_MINOR,
    "cci_fine": CCI_CELLTYPE_FINE,
}

# Auto mode: prefer minor, then other canonical CCI tiers, then cluster (with warning).
AUTO_CANONICAL_ANNOTATION_PRIORITY: tuple[tuple[str, str], ...] = (
    ("cci_minor", CCI_CELLTYPE_MINOR),
    ("cci_fine", CCI_CELLTYPE_FINE),
    ("cci_major", CCI_CELLTYPE_MAJOR),
)


class LRGroupingResolution(TypedDict):
    """Metadata for metrics, checkpoints, and ``zerna_ligand_receptor``."""

    groupby_column: str
    requested_mode: str
    effective_mode: str
    used_cluster_fallback: bool
    fallback_reason: str | None
    grouping_source_type: str
    annotation_dependency_required: bool
    annotation_dependency_satisfied: bool
    requested_cluster_key: str
    resolved_cluster_key: str | None


def _try_valid_cci_column(
    adata: ad.AnnData,
    col: str,
    *,
    max_unique_ratio_cci: float,
) -> bool:
    if col not in adata.obs.columns:
        return False
    return is_valid_groupby_column(adata, col, max_unique_ratio=max_unique_ratio_cci)


def resolve_lr_groupby_column(
    adata: ad.AnnData,
    *,
    communication_grouping: str | None,
    cluster_key_requested: str | None,
    max_unique_ratio_cci: float = 0.95,
) -> LRGroupingResolution:
    """
    Choose the obs column passed to LIANA as ``groupby``.

    - **auto** — ``cci_celltype_minor`` if valid, else ``cci_celltype_fine``, else
      ``cci_celltype_major``; only if none are valid, fall back to the resolved
      cluster key (with ``used_cluster_fallback`` and ``fallback_reason``).
    - **cci_major** / **cci_minor** / **cci_fine** — require the matching
      ``cci_celltype_*`` column to exist and pass validity checks; **no** cluster
      fallback.
    - **lineage_subcluster** — require ``lineage_subcluster`` obs column (P2); exploratory;
      **no** cluster fallback and **never** selected by **auto**.
    - **cluster** — ``resolve_cluster_key`` only; annotation columns are not required.
    """
    raw = (communication_grouping or "auto").strip().lower()
    if raw not in (
        "auto",
        "cci_major",
        "cci_minor",
        "cci_fine",
        "cluster",
        "lineage_subcluster",
    ):
        raw = "auto"

    req_ck = str(cluster_key_requested or "leiden").strip()
    cluster_col = resolve_cluster_key(adata, req_ck)

    def _base(
        *,
        groupby_column: str,
        effective_mode: str,
        used_fallback: bool,
        reason: str | None,
        source: str,
        dep_required: bool,
        dep_satisfied: bool,
    ) -> LRGroupingResolution:
        return LRGroupingResolution(
            groupby_column=groupby_column,
            requested_mode=raw,
            effective_mode=effective_mode,
            used_cluster_fallback=used_fallback,
            fallback_reason=reason,
            grouping_source_type=source,
            annotation_dependency_required=dep_required,
            annotation_dependency_satisfied=dep_satisfied,
            requested_cluster_key=req_ck,
            resolved_cluster_key=cluster_col,
        )

    if raw == "cluster":
        if not cluster_col:
            raise ValueError(
                "ligand–receptor communication_grouping=cluster requires a resolvable cluster "
                f"column (requested={req_ck!r}). "
                f"Available obs columns: {list(adata.obs.columns)}"
            )
        return _base(
            groupby_column=cluster_col,
            effective_mode="cluster",
            used_fallback=False,
            reason=None,
            source="cluster",
            dep_required=False,
            dep_satisfied=False,
        )

    if raw == "auto":
        for eff_mode, col in AUTO_CANONICAL_ANNOTATION_PRIORITY:
            if _try_valid_cci_column(adata, col, max_unique_ratio_cci=max_unique_ratio_cci):
                return _base(
                    groupby_column=col,
                    effective_mode=eff_mode,
                    used_fallback=False,
                    reason=None,
                    source="annotation",
                    dep_required=False,
                    dep_satisfied=True,
                )
        reason = (
            "No valid canonical annotation CCI column "
            f"({', '.join(c for _, c in AUTO_CANONICAL_ANNOTATION_PRIORITY)}) "
            f"— using cluster fallback"
        )
        if not cluster_col:
            raise ValueError(
                "ligand–receptor: auto mode requires either valid cci_celltype_* columns "
                "(after annotation) or a resolvable cluster column. "
                f"{reason}. requested_cluster_key={req_ck!r}. "
                f"Available obs columns: {list(adata.obs.columns)}"
            )
        return _base(
            groupby_column=cluster_col,
            effective_mode="cluster",
            used_fallback=True,
            reason=reason,
            source="cluster",
            dep_required=False,
            dep_satisfied=False,
        )

    if raw == "lineage_subcluster":
        col = LINEAGE_SUBCLUSTER_COL
        if col not in adata.obs.columns:
            raise ValueError(
                "ligand–receptor communication_grouping='lineage_subcluster' requires obs column "
                f"{col!r} (P2 lineage reclustering). Column is missing — run annotation with P2 "
                "lineage reclustering first, or choose 'auto', 'cluster', or cci_* grouping. "
                f"Available obs columns: {list(adata.obs.columns)}"
            )
        if not _try_valid_cci_column(adata, col, max_unique_ratio_cci=max_unique_ratio_cci):
            raise ValueError(
                f"{col!r} is present but not usable as an LR groupby "
                "(e.g. too many distinct values per cell, or fewer than two groups after dropping "
                "empty labels). "
                "Choose communication_grouping='auto' or 'cluster', or adjust P2 outputs. "
                "communication_grouping='lineage_subcluster' does not fall back to clusters."
            )
        return _base(
            groupby_column=col,
            effective_mode="lineage_subcluster",
            used_fallback=False,
            reason=None,
            source="lineage_subcluster",
            dep_required=True,
            dep_satisfied=True,
        )

    # Explicit cci_* — annotation-dependent; strict (no cluster fallback)
    col = CCI_COLUMN[raw]
    if col not in adata.obs.columns:
        raise ValueError(
            f"Ligand–receptor communication_grouping={raw!r} requires annotation column "
            f"{col!r} (from AnnotationAgentV3 / build_cci_celltype_columns). "
            f"Column is missing — run annotation first, or use grouping 'auto' or 'cluster'. "
            f"Available obs columns: {list(adata.obs.columns)}"
        )
    if not _try_valid_cci_column(adata, col, max_unique_ratio_cci=max_unique_ratio_cci):
        raise ValueError(
            f"{col!r} is present but not usable as an LR groupby "
            f"(e.g. too many distinct values per cell). "
            f"Choose communication_grouping='cluster' or 'auto', or fix annotation labels. "
            f"communication_grouping={raw!r} does not fall back to clusters."
        )
    return _base(
        groupby_column=col,
        effective_mode=raw,
        used_fallback=False,
        reason=None,
        source="annotation",
        dep_required=True,
        dep_satisfied=True,
    )


def add_lr_display_columns(results_df: Any) -> Any:
    """Copy source/target into display columns when present."""
    import pandas as pd

    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        return results_df
    out = results_df.copy()
    if "source" in out.columns and "source_display" not in out.columns:
        out["source_display"] = out["source"].astype(str)
    if "target" in out.columns and "target_display" not in out.columns:
        out["target_display"] = out["target"].astype(str)
    return out


__all__ = [
    "AUTO_CANONICAL_ANNOTATION_PRIORITY",
    "CCI_CELLTYPE_FINE",
    "CCI_CELLTYPE_MAJOR",
    "CCI_CELLTYPE_MINOR",
    "CCI_COLUMN",
    "LRGroupingResolution",
    "add_lr_display_columns",
    "resolve_lr_groupby_column",
]
