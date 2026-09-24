"""Tests for explorer annotation evidence normalization and uns backfill."""

from __future__ import annotations

import anndata as ad
import numpy as np

from methods.annotation.explorer_annotation_evidence import (
    ensure_explorer_annotation_evidence,
    normalize_top_cell_types_entry,
)


class TestNormalizeTopCellTypesEntry:
    def test_tuple_three_fields(self):
        d = normalize_top_cell_types_entry(("CT_1", 0.85, 4))
        assert d == {"cell_type": "CT_1", "score": 0.85, "n_markers": 4}

    def test_dict_adjusted_score(self):
        d = normalize_top_cell_types_entry(
            {"cell_type": "X", "adjusted_score": 0.5, "n_markers": 2}
        )
        assert d == {"cell_type": "X", "score": 0.5, "n_markers": 2}

    def test_empty_dict_returns_none(self):
        assert normalize_top_cell_types_entry({}) is None


class TestEnsureExplorerAnnotationEvidence:
    def test_coerces_top_cell_types_and_fills_cluster_markers(self):
        rng = np.random.default_rng(0)
        n, g = 40, 30
        X = rng.random((n, g)).astype(np.float32)
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"c{i}" for i in range(n)]
        adata.var_names = [f"gene_{i}" for i in range(g)]
        adata.obs["leiden"] = np.where(np.arange(n) < 20, "0", "1").astype(object)

        adata.uns["zerna_cluster_annotations"] = {
            "0": {
                "summary": "a",
                "top_cell_types": [("t1", 0.9, 3), ("t2", 0.2, 1)],
                "supporting_markers": {},
            },
        }
        adata.uns["cluster_markers"] = {
            "0": ["gene_0", "gene_1"],
            "1": ["gene_2"],
        }

        ensure_explorer_annotation_evidence(adata, "leiden", top_n=10, coerce_top_cell_types=True)

        ann0 = adata.uns["zerna_cluster_annotations"]["0"]
        assert ann0["top_cell_types"][0]["cell_type"] == "t1"
        assert ann0["top_cell_types"][1]["cell_type"] == "t2"
        assert ann0["cluster_markers"] == ["gene_0", "gene_1"]

    def test_recomputes_when_cluster_markers_empty(self):
        rng = np.random.default_rng(1)
        n, g = 30, 25
        X = rng.random((n, g)).astype(np.float32)
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"c{i}" for i in range(n)]
        adata.var_names = [f"gene_{i}" for i in range(g)]
        adata.obs["leiden"] = np.where(np.arange(n) < 15, "0", "1").astype(object)

        adata.uns["zerna_cluster_annotations"] = {
            "0": {"summary": "a", "top_cell_types": [("x", 1.0, 0)]},
        }
        adata.uns["cluster_markers"] = {"0": [], "1": []}

        ensure_explorer_annotation_evidence(adata, "leiden", top_n=5, coerce_top_cell_types=True)

        cm = adata.uns.get("cluster_markers")
        assert isinstance(cm, dict)
        assert any(len(v) > 0 for v in cm.values())
