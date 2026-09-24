"""Regression: Scanpy ``rank_genes_groups`` in ``uns`` must survive ``write_h5ad``."""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pytest

from methods.annotation.uns_h5ad_serialization import sanitize_explorer_uns_for_h5ad


@pytest.mark.parametrize(
    "rg",
    [
        {
            "params": {"groupby": "leiden", "method": "wilcoxon"},
            "names": np.array([["CD3D", "CD3E"], ["MS4A1", "CD79A"]], dtype=object),
            "scores": np.array([[10.0, 8.0], [9.0, 7.0]], dtype=np.float64),
        },
    ],
)
def test_sanitize_rank_genes_groups_allows_h5ad_write(tmp_path: Path, rg: dict) -> None:
    adata = ad.AnnData(np.ones((4, 2), dtype=np.float32))
    adata.uns["rank_genes_groups"] = rg
    sanitize_explorer_uns_for_h5ad(adata)
    path = tmp_path / "x.h5ad"
    adata.write_h5ad(path)
    back = ad.read_h5ad(path)
    assert "rank_genes_groups" in back.uns
