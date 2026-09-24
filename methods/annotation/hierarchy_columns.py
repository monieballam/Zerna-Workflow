"""Display-column constants for Zerna explorer payloads.

These names are retained so existing H5AD explorer views keep working.
They are not a Zerna hierarchy engine.
"""

from __future__ import annotations

import re
from typing import Any

AUTO_LEVEL1_COL = "auto_level1"
AUTO_LEVEL2_COL = "auto_level2"
AUTO_LEVEL3_COL = "auto_level3"
GLOBAL_CLUSTER_COL = "global_cluster"
LINEAGE_SUBCLUSTER_COL = "lineage_subcluster"
FINE_SUBCLUSTER_COL = "fine_subcluster"
FINAL_DISPLAY_COL = "final_display"

EXPLORER_PARTITION_INSPECTOR_UNS_KEY = "explorer_partition_inspector_v1"
LINEAGE_P2_CONFIG_UNS_KEY = "lineage_reclustering_p2_config"
LINEAGE_P2_REPORT_UNS_KEY = "lineage_reclustering_p2"
FINE_P3_CONFIG_UNS_KEY = "fine_reclustering_p3_config"
FINE_P3_REPORT_UNS_KEY = "fine_reclustering_p3"
ZERNA_P2_STATUS_UNS_KEY = "zerna_p2_status"
ZERNA_P3_STATUS_UNS_KEY = "zerna_p3_status"
ZERNA_LEVEL3_EVIDENCE_UNS_KEY = "zerna_level3_evidence_v1"
ZERNA_POST_AGENT_CANON_V1_UNS_KEY = "zerna_post_agent_canonicalization_v1"
ZERNA_HIERARCHY_PROVENANCE_V1_UNS_KEY = "zerna_hierarchy_provenance_v1"

OBSM_UMAP_LINEAGE_IMMUNE = "X_umap_lineage_immune"
OBSM_UMAP_LINEAGE_STROMAL = "X_umap_lineage_stromal"
OBSM_UMAP_LINEAGE_EPITHELIAL = "X_umap_lineage_epithelial"
OBSM_UMAP_LINEAGE_ENDOTHELIAL = "X_umap_lineage_endothelial"
OBSM_UMAP_FINE_T_CELLS = "X_umap_fine_t_cells"
OBSM_UMAP_FINE_FIBROBLASTS = "X_umap_fine_fibroblasts"
OBSM_UMAP_FINE_MYELOID = "X_umap_fine_myeloid"
OBSM_UMAP_FINE_B_CELLS = "X_umap_fine_b_cells"
OBSM_UMAP_FINE_SMOOTH_MUSCLE = "X_umap_fine_smooth_muscle"

LINEAGE_P2_OBSM_KEYS: tuple[str, ...] = ()
FINE_P3_OBSM_KEYS: tuple[str, ...] = ()
P2_RECLUSTER_LINEAGES: tuple[str, ...] = ()
P3_RECLUSTER_LEVEL2: tuple[str, ...] = ()
P3_FINE_SUBCLUSTER_RE = re.compile(r"^fine_")

_NONINFORMATIVE = frozenset({"", "nan", "none", "null", "unknown", "not_in_parent"})


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_level1(value: Any) -> str:
    return _as_text(value)


def normalize_level2(value: Any, level1: Any = None) -> str:
    return _as_text(value)


def normalize_level3(value: Any, level1: Any = None, level2: Any = None) -> str:
    return _as_text(value)


def level3_non_informative(value: Any) -> bool:
    return _as_text(value).lower() in _NONINFORMATIVE
