"""Partition-aware Cluster Inspector evidence for lineage_subcluster and fine_subcluster."""

from __future__ import annotations

import copy
import logging
from typing import Any

import anndata as ad
import numpy as np

from methods.annotation.hierarchy_columns import (
    EXPLORER_PARTITION_INSPECTOR_UNS_KEY,
    FINE_SUBCLUSTER_COL,
    GLOBAL_CLUSTER_COL,
    LINEAGE_SUBCLUSTER_COL,
    P2_RECLUSTER_LINEAGES,
    P3_FINE_SUBCLUSTER_RE,
)
from methods.annotation.cluster_marker_de import _compute_cluster_markers
from methods.annotation.explorer_annotation_evidence import (
    pick_support_markers_for_display_headline,
)
from methods.annotation.uns_h5ad_serialization import serialize_uns_for_h5ad

logger = logging.getLogger(__name__)


def _nonempty_marker_value(raw: object) -> bool:
    """Avoid ``if ndarray:`` / ambiguous truth tests on marker list values."""
    if raw is None:
        return False
    if isinstance(raw, np.ndarray):
        return raw.size > 0
    if isinstance(raw, (list, tuple, set)):
        return len(raw) > 0
    if isinstance(raw, str):
        return bool(raw.strip())
    try:
        return bool(raw)
    except ValueError:
        return True


def _valid_lineage_subcluster_token(token: str) -> bool:
    """True when the token prefix is a P2 lineage (Immune/Stromal/Epithelial/Endothelial)."""
    t = str(token).strip()
    if not t or t.lower() in {"nan", "none"}:
        return False
    if ":" not in t:
        return False
    prefix = t.split(":", 1)[0]
    return prefix in P2_RECLUSTER_LINEAGES


def _annotation_support_genes(annotation: dict[str, Any], assigned_label: str) -> list[str]:
    """Pack genes for overlap with partition DE — same headline / hierarchy key order as explorer API."""
    m, _, _ = pick_support_markers_for_display_headline(annotation, assigned_label, max_markers=30)
    return m


def _mode_global_cluster(adata: ad.AnnData, row_mask: np.ndarray) -> str | None:
    if GLOBAL_CLUSTER_COL not in adata.obs.columns:
        return None
    s = adata.obs.loc[row_mask, GLOBAL_CLUSTER_COL].astype(str).str.strip()
    s = s.replace("", np.nan).dropna()
    if s.empty:
        return None
    return str(s.mode().iloc[0])


def _global_cluster_markers(adata: ad.AnnData, global_id: str | None, top_n: int) -> list[str]:
    if not global_id:
        return []
    cm = adata.uns.get("cluster_markers")
    if not isinstance(cm, dict):
        return []
    gid = str(global_id)
    genes = cm.get(gid)
    if genes is None and gid.isdigit():
        genes = cm.get(str(int(gid)))
    if not isinstance(genes, (list, tuple)):
        return []
    return [str(g) for g in genes[:top_n]]


def _merge_partition_annotation(
    adata: ad.AnnData,
    *,
    row_mask: np.ndarray,
    deg_genes: list[str],
    zerna_by_global: dict[str, Any],
    top_n: int,
) -> dict[str, Any]:
    dom = _mode_global_cluster(adata, row_mask)
    base_raw = zerna_by_global.get(str(dom), {}) if dom is not None else {}
    base: dict[str, Any] = copy.deepcopy(base_raw) if isinstance(base_raw, dict) else {}
    genes = list(deg_genes[:top_n]) if deg_genes else _global_cluster_markers(adata, dom, top_n)
    base["cluster_markers"] = genes
    if dom is not None:
        base["_retrieval_source_cluster"] = str(dom)
    label_hint = str(base.get("normalized_label") or "")
    sup = _annotation_support_genes(base, label_hint)
    if sup and genes:
        head = set(genes[: min(50, len(genes))])
        overlap = [g for g in sup if g in head]
        if len(overlap) >= 2:
            base["partition_annotation_support_markers"] = overlap[:15]
    return base


def ensure_partition_explorer_inspector_evidence(
    adata: ad.AnnData,
    *,
    top_n: int = 50,
) -> None:
    """Populate ``uns`` with partition-level inspector evidence (H5AD-safe dicts).

    - ``explorer_partition_inspector_v1``: per lineage_subcluster / fine_subcluster id,
      annotation-shaped dicts derived from the dominant global cluster's
      ``zerna_cluster_annotations`` entry, with ``cluster_markers`` set from
      partition-level DE when available (else global cluster markers).

    Canonical marker-evidence ``uns`` keys
    (``cluster_marker_evidence_v1``, ``lineage_subcluster_marker_evidence_v1``,
    ``fine_subcluster_marker_evidence_v1``) are owned by vendored Zerna ``attach_*``;
    this function does **not** write or overwrite them.
    """
    raw_ann = adata.uns.get("zerna_cluster_annotations")
    zerna_by_global: dict[str, Any] = {}
    if isinstance(raw_ann, dict) and raw_ann:
        zerna_by_global = {str(k): v for k, v in raw_ann.items() if isinstance(v, dict)}
    elif raw_ann is not None:
        logger.debug(
            "partition explorer evidence: zerna_cluster_annotations not a dict; skipping merge"
        )

    out_lineage: dict[str, dict[str, Any]] = {}
    out_fine: dict[str, dict[str, Any]] = {}
    lineage_deg: dict[str, list[str]] = {}
    fine_deg: dict[str, list[str]] = {}

    if LINEAGE_SUBCLUSTER_COL in adata.obs.columns:
        ls = adata.obs[LINEAGE_SUBCLUSTER_COL].astype(str).str.strip()
        valid_mask = ls.map(_valid_lineage_subcluster_token).to_numpy()
        if bool(valid_mask.sum() >= 2):
            n_u = int(
                adata.obs.loc[valid_mask, LINEAGE_SUBCLUSTER_COL].astype(str).str.strip().nunique()
            )
            if n_u >= 2:
                sub = adata[valid_mask].copy()
                raw_deg, _ = _compute_cluster_markers(
                    sub, cluster_key=LINEAGE_SUBCLUSTER_COL, top_n=top_n
                )
                lineage_deg = {
                    str(k): [str(g) for g in v[:top_n]]
                    for k, v in raw_deg.items()
                    if str(k).strip()
                }
        _vm_lineage = np.asarray(valid_mask, dtype=bool)
        pids = (
            sorted({str(x) for x in ls.iloc[np.flatnonzero(_vm_lineage)].unique()}, key=str)
            if bool(_vm_lineage.any())
            else []
        )
        for pid in pids:
            row_mask = (ls == pid).to_numpy()
            if not row_mask.any():
                continue
            genes = lineage_deg.get(pid, [])
            out_lineage[pid] = _merge_partition_annotation(
                adata,
                row_mask=row_mask,
                deg_genes=genes,
                zerna_by_global=zerna_by_global,
                top_n=top_n,
            )

    if FINE_SUBCLUSTER_COL in adata.obs.columns:
        fs = adata.obs[FINE_SUBCLUSTER_COL].astype(str).str.strip()
        valid_mask = np.array([bool(P3_FINE_SUBCLUSTER_RE.match(str(x))) for x in fs], dtype=bool)
        if bool(valid_mask.sum() >= 2):
            n_u = int(
                adata.obs.loc[valid_mask, FINE_SUBCLUSTER_COL].astype(str).str.strip().nunique()
            )
            if n_u >= 2:
                sub = adata[valid_mask].copy()
                raw_deg, _ = _compute_cluster_markers(
                    sub, cluster_key=FINE_SUBCLUSTER_COL, top_n=top_n
                )
                fine_deg = {
                    str(k): [str(g) for g in v[:top_n]]
                    for k, v in raw_deg.items()
                    if str(k).strip()
                }
        _vm = np.asarray(valid_mask, dtype=bool)
        pids = (
            sorted({str(x) for x in fs.iloc[np.flatnonzero(_vm)].unique()}, key=str)
            if bool(_vm.any())
            else []
        )
        for pid in pids:
            row_mask = (fs == pid).to_numpy()
            if not row_mask.any():
                continue
            genes = fine_deg.get(pid, [])
            out_fine[pid] = _merge_partition_annotation(
                adata,
                row_mask=row_mask,
                deg_genes=genes,
                zerna_by_global=zerna_by_global,
                top_n=top_n,
            )

    adata.uns[EXPLORER_PARTITION_INSPECTOR_UNS_KEY] = serialize_uns_for_h5ad(
        {
            "version": 1,
            "lineage_subcluster": out_lineage,
            "fine_subcluster": out_fine,
        }
    )


__all__ = ["ensure_partition_explorer_inspector_evidence"]
