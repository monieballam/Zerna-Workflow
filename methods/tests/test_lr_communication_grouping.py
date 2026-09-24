"""LIANA communication grouping: CCI columns vs cluster fallback (strict explicit cci_*)."""

from __future__ import annotations

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from methods.annotation.zerna_architecture.celltype_cci_columns import build_cci_celltype_columns
from methods.annotation.hierarchy_columns import (
    AUTO_LEVEL1_COL,
    AUTO_LEVEL2_COL,
    AUTO_LEVEL3_COL,
    LINEAGE_SUBCLUSTER_COL,
)
from methods.annotation.lr_communication_grouping import (
    add_lr_display_columns,
    resolve_lr_groupby_column,
)


def test_auto_selects_cci_celltype_minor_when_present():
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": ["Immune:Myeloid"] * 2 + ["Stromal:Fibroblasts"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 3)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "cci_celltype_minor"
    assert r["effective_mode"] == "cci_minor"
    assert not r["used_cluster_fallback"]
    assert r["grouping_source_type"] == "annotation"
    assert r["annotation_dependency_satisfied"]


def test_auto_prefers_cci_minor_when_lineage_subcluster_also_present():
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": ["Immune:Myeloid"] * 2 + ["Stromal:Fibroblasts"] * 2,
            LINEAGE_SUBCLUSTER_COL: ["Immune:0"] * 2 + ["Stromal:1"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "cci_celltype_minor"
    assert r["effective_mode"] == "cci_minor"


def test_auto_prefers_minor_over_coarser_when_both_present():
    obs = pd.DataFrame(
        {
            "cci_celltype_major": ["Immune"] * 4,
            "cci_celltype_minor": ["Immune:Myeloid"] * 2 + ["Stromal:Fibroblasts"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "cci_celltype_minor"


def test_auto_selects_cci_major_when_minor_and_fine_missing():
    obs = pd.DataFrame(
        {
            "cci_celltype_major": ["Immune"] * 2 + ["Stromal"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "cci_celltype_major"
    assert r["effective_mode"] == "cci_major"
    assert not r["used_cluster_fallback"]


def test_auto_falls_back_to_cluster_when_no_cci_columns():
    obs = pd.DataFrame({"leiden": ["0", "0", "1", "1"]})
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "leiden"
    assert r["effective_mode"] == "cluster"
    assert r["used_cluster_fallback"]
    assert r["fallback_reason"]
    assert r["grouping_source_type"] == "cluster"
    assert not r["annotation_dependency_satisfied"]


def test_auto_resolves_annotation_after_agent_v3_cci_build():
    n = 4
    obs = pd.DataFrame(
        {
            AUTO_LEVEL1_COL: ["Immune"] * 2 + ["Stromal"] * 2,
            AUTO_LEVEL2_COL: ["Myeloid"] * 2 + ["Fibroblasts"] * 2,
            AUTO_LEVEL3_COL: ["Mono", "Macro", "iCAF", "iCAF"],
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((n, 3)), obs=obs)
    build_cci_celltype_columns(adata)
    assert "cci_celltype_minor" in adata.obs.columns
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "cci_celltype_minor"
    assert r["grouping_source_type"] == "annotation"


def test_lineage_subcluster_explicit():
    obs = pd.DataFrame(
        {
            LINEAGE_SUBCLUSTER_COL: ["Immune:0"] * 2 + ["Stromal:1"] * 2,
            "cci_celltype_minor": ["Immune:Myeloid"] * 2 + ["Stromal:Fibroblasts"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="lineage_subcluster",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == LINEAGE_SUBCLUSTER_COL
    assert r["effective_mode"] == "lineage_subcluster"
    assert r["grouping_source_type"] == "lineage_subcluster"
    assert r["annotation_dependency_required"]


def test_lineage_subcluster_raises_when_column_missing():
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": ["A"] * 2 + ["B"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    with pytest.raises(ValueError, match="lineage_subcluster"):
        resolve_lr_groupby_column(
            adata,
            communication_grouping="lineage_subcluster",
            cluster_key_requested="leiden",
        )


def test_cluster_mode_ignores_cci_columns():
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": ["A"] * 4,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="cluster",
        cluster_key_requested="leiden",
    )
    assert r["groupby_column"] == "leiden"
    assert r["effective_mode"] == "cluster"
    assert not r["used_cluster_fallback"]


def test_cci_major_and_cci_fine_explicit():
    obs = pd.DataFrame(
        {
            "cci_celltype_major": ["Immune"] * 2 + ["Stromal"] * 2,
            "cci_celltype_fine": ["Immune:Myeloid:Mono"] * 2 + ["Stromal:Fibroblasts:iCAF"] * 2,
            "leiden": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r_maj = resolve_lr_groupby_column(
        adata, communication_grouping="cci_major", cluster_key_requested="leiden"
    )
    assert r_maj["groupby_column"] == "cci_celltype_major"
    assert r_maj["effective_mode"] == "cci_major"
    assert r_maj["annotation_dependency_required"]

    r_fine = resolve_lr_groupby_column(
        adata, communication_grouping="cci_fine", cluster_key_requested="leiden"
    )
    assert r_fine["groupby_column"] == "cci_celltype_fine"
    assert r_fine["effective_mode"] == "cci_fine"


def test_cci_explicit_raises_when_column_missing():
    obs = pd.DataFrame({"leiden": ["0", "0", "1", "1"]})
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    for mode in ("cci_minor", "cci_major", "cci_fine"):
        with pytest.raises(ValueError, match="requires annotation column|annotation column"):
            resolve_lr_groupby_column(
                adata,
                communication_grouping=mode,
                cluster_key_requested="leiden",
            )


def test_cci_explicit_raises_when_column_invalid_not_fallback():
    """Per-cell unique pseudo-CCI column must not silently fall back to cluster."""
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": [f"g{i}" for i in range(20)],
            "leiden": ["0"] * 10 + ["1"] * 10,
        }
    )
    adata = ad.AnnData(X=np.zeros((20, 2)), obs=obs)
    with pytest.raises(ValueError, match="not usable as an LR groupby"):
        resolve_lr_groupby_column(
            adata,
            communication_grouping="cci_minor",
            cluster_key_requested="leiden",
        )


def test_requested_and_resolved_cluster_key_in_provenance_shape():
    obs = pd.DataFrame(
        {
            "cci_celltype_minor": ["A", "A", "B", "B"],
            "louvain": ["0", "0", "1", "1"],
        }
    )
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    r = resolve_lr_groupby_column(
        adata,
        communication_grouping="auto",
        cluster_key_requested="leiden",
    )
    assert r["requested_cluster_key"] == "leiden"
    assert r["resolved_cluster_key"] == "louvain"


def test_add_lr_display_columns_keeps_raw_source_target():
    df = pd.DataFrame(
        {
            "source": ["Immune:Myeloid"],
            "target": ["Stromal:Fibroblasts"],
            "liana_rank": [1.0],
        }
    )
    out = add_lr_display_columns(df)
    assert out["source"].tolist() == ["Immune:Myeloid"]
    assert out["target"].tolist() == ["Stromal:Fibroblasts"]
    assert out["source_display"].iloc[0] == "Myeloid"
    assert out["target_display"].iloc[0] == "Fibroblasts"


def test_cluster_mode_raises_without_cluster_column():
    obs = pd.DataFrame({"only_bio_metadata": ["A", "B", "A", "B"]})
    adata = ad.AnnData(X=np.zeros((4, 2)), obs=obs)
    with pytest.raises(ValueError, match="cluster"):
        resolve_lr_groupby_column(
            adata,
            communication_grouping="cluster",
            cluster_key_requested="leiden",
        )
