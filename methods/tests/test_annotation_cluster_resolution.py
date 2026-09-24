"""Cluster key and expression provenance for annotation vs upstream clustering."""

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from anndata import AnnData

from methods.annotation.write_guard import (
    ANNOTATION_WRITE_GUARD_UNS_KEY,
    backup_column_name,
    preserve_annotation_columns_before_rewrite,
)
from methods.annotation.cell_type_annotation import ANNOTATION_DASHBOARD_CANONICAL_OBS
from methods.annotation.cluster_keys import resolve_annotation_cluster_key


def _adata_with_clusters(*, leiden: bool = True, louvain: bool = False) -> AnnData:
    rng = np.random.default_rng(0)
    n = 40
    g = 30
    X = sp.csr_matrix(rng.poisson(2, size=(n, g)).astype(np.float32))
    ad = AnnData(X=X)
    ad.obs_names = [f"c{i}" for i in range(n)]
    ad.var_names = [f"g{i}" for i in range(g)]
    if leiden:
        ad.obs["leiden"] = pd.Series([str(i % 3) for i in range(n)], index=ad.obs_names)
    if louvain:
        ad.obs["louvain"] = pd.Series([str(i % 4) for i in range(n)], index=ad.obs_names)
    return ad


def test_resolve_prefers_leiden_when_zerna_clustering_says_leiden():
    ad = _adata_with_clusters(leiden=True, louvain=True)
    ad.uns["zerna_clustering"] = {"method_executed": "leiden", "cluster_key_written": "leiden"}
    key, meta = resolve_annotation_cluster_key(ad, None, pipeline_cluster_key_hint=None)
    assert key == "leiden"
    assert meta["clustering_method_detected"] == "leiden"
    assert meta["cluster_key_resolved"] == "leiden"


def test_resolve_prefers_louvain_when_zerna_clustering_says_louvain():
    ad = _adata_with_clusters(leiden=True, louvain=True)
    ad.uns["zerna_clustering"] = {"method_executed": "louvain", "cluster_key_written": "louvain"}
    key, meta = resolve_annotation_cluster_key(ad, None, pipeline_cluster_key_hint=None)
    assert key == "louvain"
    assert meta["clustering_method_detected"] == "louvain"


def test_resolve_uses_pipeline_hint_when_no_zerna_clustering():
    ad = _adata_with_clusters(leiden=True, louvain=False)
    key, meta = resolve_annotation_cluster_key(ad, None, pipeline_cluster_key_hint="leiden")
    assert key == "leiden"
    assert meta["cluster_key_requested"] is None


def test_resolve_explicit_key_missing_raises():
    ad = _adata_with_clusters(leiden=True, louvain=False)
    with pytest.raises(ValueError, match="not present in adata.obs"):
        resolve_annotation_cluster_key(ad, "nonexistent_col", pipeline_cluster_key_hint=None)


def test_canonical_dashboard_obs_tuple_documents_product_fields():
    assert "annotation_label" in ANNOTATION_DASHBOARD_CANONICAL_OBS
    assert "final_display" in ANNOTATION_DASHBOARD_CANONICAL_OBS
    assert "annotation_confidence" in ANNOTATION_DASHBOARD_CANONICAL_OBS


def test_preserve_annotation_columns_before_rewrite_is_one_time_and_non_destructive():
    ad = _adata_with_clusters(leiden=True, louvain=False)
    ad.obs["annotation_label"] = pd.Series(["Legacy"] * ad.n_obs, index=ad.obs_names)
    ad.obs["auto_level3"] = pd.Series(["CD4"] * ad.n_obs, index=ad.obs_names)
    ad.obs["final_display"] = pd.Series(
        ["Immune|T cells|CD4"] * ad.n_obs,
        index=ad.obs_names,
    )

    first = preserve_annotation_columns_before_rewrite(ad)
    ad.obs["annotation_label"] = pd.Series(["New"] * ad.n_obs, index=ad.obs_names)
    second = preserve_annotation_columns_before_rewrite(ad)

    assert "annotation_label" in first["preserved_columns"]
    assert "annotation_label" in second["existing_backup_columns"]
    assert list(ad.obs[backup_column_name("annotation_label")]) == ["Legacy"] * ad.n_obs
    assert list(ad.obs[backup_column_name("auto_level3")]) == ["CD4"] * ad.n_obs
    assert list(ad.obs[backup_column_name("final_display")]) == ["Immune|T cells|CD4"] * ad.n_obs


def test_hybrid_annotation_writes_zerna_annotation_provenance(monkeypatch):
    """Cross-step: clustering metadata + expression source recorded after marker/celltypist path."""
    import unittest.mock as mock

    from methods.annotation import cell_type_annotation as m

    ad = _adata_with_clusters(leiden=True, louvain=False)
    ad.layers["log1p"] = ad.X.copy()
    ad.uns["zerna_clustering"] = {"method_executed": "leiden"}
    ad.uns["zerna_active_representation"] = "X_pca"
    ad.obsm["X_pca"] = np.zeros((ad.n_obs, 5), dtype=np.float32)

    def mock_predict(*_a, **_k):
        n = ad.n_obs
        labs = np.array(["T"] * n, dtype=object)
        uq = ["T"]
        pm = pd.DataFrame(np.ones((n, 1)), index=ad.obs_names, columns=uq)
        pl = pd.DataFrame({"predicted_labels": labs}, index=ad.obs_names)
        pred = mock.MagicMock()
        pred.predicted_labels = pl
        pred.probability_matrix = pm
        pred.majority_voting = None
        return pred

    monkeypatch.setattr(m, "_resolve_celltypist_model", lambda _mn: object())
    monkeypatch.setattr(m, "_predict_celltypist_in_chunks", mock_predict)

    from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

    out = CellTypistMethod().execute(
        CellTypistInput(
            adata=ad,
            annotation_method="hybrid",
            majority_voting=False,
            cluster_key=None,
            pipeline_cluster_key_hint="leiden",
            annotation_input_is_main_adata=True,
        ),
        compute=None,
    )
    ba = out.adata.uns.get("zerna_annotation") or {}
    assert ba.get("cluster_key_resolved") == "leiden"
    assert ba.get("clustering_method_detected") == "leiden"
    assert ba.get("expression_source_used") == "layers_log1p"
    assert ba.get("active_representation_at_annotation") == "X_pca"
    assert ba.get("annotation_input_mode") == "main_adata"
    assert out.metrics.cluster_key_resolved == "leiden"
    assert out.metrics.expression_source_used == "layers_log1p"


def test_hybrid_annotation_rerun_preserves_previous_annotation_columns(monkeypatch):
    """A rerun may refresh canonical labels, but the prior annotation state must remain archived."""
    import unittest.mock as mock

    from methods.annotation import cell_type_annotation as m

    ad = _adata_with_clusters(leiden=True, louvain=False)
    ad.layers["log1p"] = ad.X.copy()
    ad.obs["annotation_label"] = pd.Series(["LegacyFib"] * ad.n_obs, index=ad.obs_names)
    ad.obs["celltype_level3"] = pd.Series(["LegacySubtype"] * ad.n_obs, index=ad.obs_names)
    ad.obs["zr_level3"] = pd.Series(["LegacySubtype"] * ad.n_obs, index=ad.obs_names)
    ad.obs["auto_level3"] = pd.Series(["LegacySubtype"] * ad.n_obs, index=ad.obs_names)
    ad.obs["final_display"] = pd.Series(
        ["Stromal|Fibroblasts|LegacySubtype"] * ad.n_obs,
        index=ad.obs_names,
    )

    def mock_predict(*_a, **_k):
        labs = np.array(["T"] * ad.n_obs, dtype=object)
        uq = ["T"]
        pm = pd.DataFrame(np.ones((ad.n_obs, 1)), index=ad.obs_names, columns=uq)
        pl = pd.DataFrame({"predicted_labels": labs}, index=ad.obs_names)
        pred = mock.MagicMock()
        pred.predicted_labels = pl
        pred.probability_matrix = pm
        pred.majority_voting = None
        return pred

    monkeypatch.setattr(m, "_resolve_celltypist_model", lambda _mn: object())
    monkeypatch.setattr(m, "_predict_celltypist_in_chunks", mock_predict)

    from methods.annotation.cell_type_annotation import CellTypistInput, CellTypistMethod

    out = CellTypistMethod().execute(
        CellTypistInput(
            adata=ad,
            annotation_method="hybrid",
            majority_voting=False,
            cluster_key=None,
            pipeline_cluster_key_hint="leiden",
            annotation_input_is_main_adata=True,
        ),
        compute=None,
    )

    obs = out.adata.obs
    assert list(obs[backup_column_name("annotation_label")]) == ["LegacyFib"] * ad.n_obs
    assert list(obs[backup_column_name("celltype_level3")]) == ["LegacySubtype"] * ad.n_obs
    assert list(obs[backup_column_name("zr_level3")]) == ["LegacySubtype"] * ad.n_obs
    assert list(obs[backup_column_name("auto_level3")]) == ["LegacySubtype"] * ad.n_obs
    assert (
        list(obs[backup_column_name("final_display")])
        == ["Stromal|Fibroblasts|LegacySubtype"] * ad.n_obs
    )
    assert (obs["annotation_label"] != "LegacyFib").all()

    guard = out.adata.uns.get(ANNOTATION_WRITE_GUARD_UNS_KEY) or {}
    assert "annotation_label" in guard.get("preserved_columns", [])
    assert "final_display" in guard.get("preserved_columns", [])
