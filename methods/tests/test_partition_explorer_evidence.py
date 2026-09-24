"""Tests for partition-level explorer inspector evidence."""

from __future__ import annotations

import anndata as ad
import numpy as np

from methods.annotation.hierarchy_columns import (
    EXPLORER_PARTITION_INSPECTOR_UNS_KEY,
    FINE_SUBCLUSTER_MARKER_EVIDENCE_UNS_KEY,
    LINEAGE_SUBCLUSTER_MARKER_EVIDENCE_UNS_KEY,
)
from methods.annotation.partition_explorer_evidence import (
    ensure_partition_explorer_inspector_evidence,
)


def test_ensure_partition_inspector_writes_uns_and_deg_maps() -> None:
    n = 8
    rng = np.random.default_rng(0)
    X = rng.random((n, 4)).astype(np.float32) * 10.0
    adata = ad.AnnData(X=X)
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.var_names = [f"g{j}" for j in range(4)]
    adata.obs["leiden"] = ["0", "0", "0", "0", "1", "1", "1", "1"]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["lineage_subcluster"] = [
        "Immune:0",
        "Immune:0",
        "Immune:1",
        "Immune:1",
        "Immune:0",
        "Immune:0",
        "Immune:1",
        "Immune:1",
    ]
    adata.obs["fine_subcluster"] = ["", "", "", "", "", "", "", ""]
    adata.uns["zerna_cluster_annotations"] = {
        "0": {
            "normalized_label": "A",
            "supporting_markers": {"A": ["g0", "g1"]},
            "top_cell_types": [{"cell_type": "A", "score": 0.9, "n_markers": 2}],
        },
        "1": {
            "normalized_label": "B",
            "supporting_markers": {"B": ["g2", "g3"]},
            "top_cell_types": [{"cell_type": "B", "score": 0.85, "n_markers": 2}],
        },
    }

    ensure_partition_explorer_inspector_evidence(adata, top_n=10)

    root = adata.uns.get(EXPLORER_PARTITION_INSPECTOR_UNS_KEY)
    assert isinstance(root, dict)
    lineage = root.get("lineage_subcluster")
    assert isinstance(lineage, dict)
    assert "Immune:0" in lineage and "Immune:1" in lineage
    assert lineage["Immune:0"].get("_retrieval_source_cluster") in {"0", "1"}
    # Canonical marker-evidence ``uns`` keys are populated by attach_* helpers, not the partition
    # explorer inspector builder (which only writes ``explorer_partition_inspector_v1``).
    assert LINEAGE_SUBCLUSTER_MARKER_EVIDENCE_UNS_KEY not in adata.uns
    assert FINE_SUBCLUSTER_MARKER_EVIDENCE_UNS_KEY not in adata.uns
