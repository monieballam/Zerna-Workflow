"""
H5AD writers for deployment smoke tests: one “modern” artifact (auto_level1/2/3 + P2 lineage)
and one “legacy” artifact (no auto hierarchy, zr_* / level3_final_safe / final_display coalesce).
"""

from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np


def write_modern_deployment_smoke_h5ad(path: Path) -> None:
    """
    Modern contract: ``auto_level*``, ``final_display``, raw ``annotation_label``, P2 lineage UMAP,
    ``global_cluster`` vs partition ``lineage_subcluster``, and one cell with unresolved structural L3.
    """
    n = 7
    adata = ad.AnnData(X=np.ones((n, 2), dtype=np.float32))
    adata.obs_names = [f"c{i}" for i in range(n)]
    adata.obs["leiden"] = [str(i % 2) for i in range(n - 1)] + ["2"]
    adata.obs["global_cluster"] = list(adata.obs["leiden"])
    adata.obs["auto_level1"] = ["Immune"] * 4 + ["Stromal"] * 2 + ["Immune"]
    adata.obs["auto_level2"] = ["T cells"] * 4 + ["Fibroblasts"] * 2 + ["T cells"]
    adata.obs["auto_level3"] = ["CD4", "CD4", "CD8", "CD8", "iCAF", "iCAF", ""]
    adata.obs["level3_final_safe"] = ["", "", "", "", "", "", ""]
    adata.obs["final_display"] = (
        ["Immune | T cells | CD4"] * 4 + ["Stromal | Fibroblasts | iCAF"] * 2 + ["Immune | T cells"]
    )
    adata.obs["lineage_subcluster"] = [
        "Immune:0",
        "Immune:0",
        "Immune:1",
        "Immune:1",
        "",
        "",
        "Immune:2",
    ]
    adata.obs["annotation_label"] = ["CD4 T", "CD4 T", "CD8 T", "CD8 T", "FB", "FB", "NKT-like"]
    adata.obs["annotation_lineage"] = ["Immune"] * 4 + ["Stromal"] * 2 + ["Immune"]
    adata.obs["annotation_confidence"] = ["high"] * n
    adata.obs["sample"] = ["S1", "S1", "S2", "S2", "S3", "S3", "S1"]
    adata.obs["condition"] = ["A", "A", "B", "B", "A", "A", "A"]
    adata.obsm["X_umap"] = np.array(
        [[float(i), float(i) * 0.1] for i in range(n)], dtype=np.float32
    )
    lu = np.full((n, 2), np.nan, dtype=np.float32)
    lu[:4, :] = np.array([[0.1 * i, 0.2 * i] for i in range(4)], dtype=np.float32)
    lu[6, :] = np.array([0.55, 0.55], dtype=np.float32)
    adata.obsm["X_umap_lineage_immune"] = lu
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "normalized_label": "CD4 T",
                "summary": "CD4 helper",
                "confidence": "high",
                "supporting_markers": {"CD4 T": ["CD4", "IL7R"]},
                "top_cell_types": [
                    {"cell_type": "CD4 T", "score": 0.9, "n_markers": 3},
                ],
            },
            "1": {
                "normalized_label": "CD8 T",
                "summary": "CD8 cytotoxic",
                "confidence": "high",
                "supporting_markers": {"CD8 T": ["CD8A", "GZMB"]},
                "top_cell_types": [
                    {"cell_type": "CD8 T", "score": 0.85, "n_markers": 2},
                ],
            },
            "2": {
                "normalized_label": "NKT-like",
                "summary": "unresolved fine",
                "confidence": "medium",
                "supporting_markers": {"NKT-like": ["ZBTB16"]},
                "top_cell_types": [],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {"evidence": [{"level3_label": "CD4 T", "score": 0.8}]},
            "1": {"evidence": [{"level3_label": "CD8 T", "score": 0.7}]},
            "2": {"evidence": [{"level3_label": "NKT-like", "score": 0.5}]},
        }
    )
    adata.uns["cluster_markers"] = {"0": ["G0A", "G0B"], "1": ["G1A", "G1B"], "2": ["G2A"]}
    adata.uns["explorer_partition_inspector_v1"] = json.dumps(
        {
            "version": 1,
            "lineage_subcluster": {
                "Immune:0": {
                    "normalized_label": "CD4 T",
                    "summary": "CD4 helper",
                    "confidence": "high",
                    "cluster_markers": ["LINEAGE_CD4_A", "LINEAGE_CD4_B"],
                    "supporting_markers": {"CD4 T": ["CD4", "IL7R"]},
                    "top_cell_types": [
                        {"cell_type": "CD4 T", "score": 0.9, "n_markers": 3},
                    ],
                    "_retrieval_source_cluster": "0",
                    "partition_annotation_support_markers": ["LINEAGE_CD4_A", "CD4"],
                },
                "Immune:1": {
                    "normalized_label": "CD8 T",
                    "summary": "CD8 cytotoxic",
                    "confidence": "high",
                    "cluster_markers": ["LINEAGE_CD8_A", "LINEAGE_CD8_B"],
                    "supporting_markers": {"CD8 T": ["CD8A", "GZMB"]},
                    "top_cell_types": [
                        {"cell_type": "CD8 T", "score": 0.85, "n_markers": 2},
                    ],
                    "_retrieval_source_cluster": "1",
                },
                "Immune:2": {
                    "normalized_label": "NKT-like",
                    "summary": "fine unresolved",
                    "confidence": "medium",
                    "cluster_markers": ["G2A"],
                    "supporting_markers": {"NKT-like": ["ZBTB16"]},
                    "top_cell_types": [],
                    "_retrieval_source_cluster": "2",
                },
            },
            "fine_subcluster": {},
        }
    )
    adata.write_h5ad(path)


def write_legacy_deployment_smoke_h5ad(path: Path) -> None:
    """
    Legacy: no ``auto_level*``; lineage from ``annotation_lineage``; level3/display from
    ``level3_final_safe`` / ``zr_*`` / ``final_display`` coalescing; ``cellType`` prefers
    ``final_display`` when present so ``rawAnnotationLabel`` stays a separate coloring column.
    """
    adata = ad.AnnData(X=np.ones((4, 3), dtype=np.float32))
    adata.obs_names = [f"cell_{i}" for i in range(4)]
    adata.obs["leiden"] = ["0", "0", "1", "1"]
    adata.obs["annotation_label"] = ["T cell", "T cell", "B cell", "B cell"]
    adata.obs["annotation_lineage"] = ["Immune", "Immune", "Immune", "Immune"]
    adata.obs["zr_level2"] = ["T cells", "T cells", "B cells", "B cells"]
    adata.obs["zr_level3"] = ["cd8_zr", "cd8_zr", "b_zr", "b_zr"]
    adata.obs["level3_final_safe"] = ["CD8", "CD8", "Memory B", "Memory B"]
    adata.obs["final_display"] = [
        "Immune | T cells | CD8",
        "Immune | T cells | CD8",
        "Immune | B cells | Memory B",
        "Immune | B cells | Memory B",
    ]
    adata.obs["zr_display"] = [
        "ZR|legacy|T",
        "ZR|legacy|T",
        "ZR|legacy|B",
        "ZR|legacy|B",
    ]
    adata.obs["annotation_confidence"] = ["high", "high", "medium", "medium"]
    adata.obs["sample"] = ["S1", "S1", "S2", "S2"]
    adata.obs["condition"] = ["Tumor", "Tumor", "Normal", "Normal"]
    adata.obsm["X_umap"] = np.array(
        [[0.0, 0.1], [0.2, 0.3], [1.0, 1.1], [1.2, 1.3]],
        dtype=np.float32,
    )
    adata.uns["cluster_markers"] = {
        "0": ["CD3D", "TRBC1"],
        "1": ["MS4A1", "CD79A"],
    }
    adata.uns["zerna_cluster_annotations"] = json.dumps(
        {
            "0": {
                "summary": "T cell cluster",
                "normalized_label": "T cell",
                "confidence": "high",
                "mode": "celltypist_consensus",
                "supporting_markers": {"T cell": ["CD3D", "TRBC1"]},
                "top_cell_types": [
                    {"cell_type": "T cell", "score": 0.91, "n_markers": 6},
                ],
                "cluster_markers": ["CD3D", "TRBC1"],
            },
            "1": {
                "summary": "B cell cluster",
                "normalized_label": "B cell",
                "confidence": "medium",
                "top_cell_types": [
                    {"cell_type": "B cell", "score": 0.73, "n_markers": 4},
                ],
                "cluster_markers": ["MS4A1", "CD79A"],
            },
        }
    )
    adata.uns["cluster_retrieval_evidence"] = json.dumps(
        {
            "0": {
                "evidence": [
                    {"cluster_id": "prior_0", "level3_label": "T cell", "score": 0.88},
                ]
            },
            "1": {
                "evidence": [
                    {"cluster_id": "prior_1", "level3_label": "B cell", "score": 0.61},
                ]
            },
        }
    )
    adata.write_h5ad(path)
