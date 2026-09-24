"""Cross-step tests: clustering and UMAP share neighbor graph state and provenance."""

import anndata as ad
import numpy as np
import pytest
import scanpy as sc
import scipy.sparse as sp

from methods.dimensionality_reduction.clustering import ClusteringInput, LeidenMethod
from methods.dimensionality_reduction.embedding import UMAPInput, UMAPMethod
from methods.dimensionality_reduction.neighbors_graph import (
    NEIGHBOR_GRAPH_PROVENANCE_SCHEMA_VERSION,
    NEIGHBOR_GRAPH_VALIDATION_CONTRACT_ID,
)


def _make_normalized_adata(n_cells=100, n_genes=500, seed=42, n_batches=1):
    """Synthetic log-normalized AnnData with HVGs and PCA (matches dimensionality test helper)."""
    rng = np.random.default_rng(seed)
    X = rng.negative_binomial(5, 0.5, size=(n_cells, n_genes)).astype(np.float32)
    X = sp.csr_matrix(X)
    adata = ad.AnnData(X=X)
    adata.obs_names = [f"cell_{i}" for i in range(n_cells)]
    adata.var_names = [f"gene_{i}" for i in range(n_genes)]
    if n_batches > 1:
        adata.obs["batch"] = [f"batch_{i % n_batches}" for i in range(n_cells)]
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=200, flavor="seurat_v3")
    sc.tl.pca(adata, n_comps=30, use_highly_variable=True, random_state=0)
    return adata


def _assert_aligned_neighbors_provenance(nb: dict) -> None:
    assert (
        nb.get("neighbor_graph_provenance_schema_version")
        == NEIGHBOR_GRAPH_PROVENANCE_SCHEMA_VERSION
    )
    assert nb.get("neighbor_graph_validation_contract_id") == NEIGHBOR_GRAPH_VALIDATION_CONTRACT_ID
    assert nb.get("connectivity_method") == "gauss"
    assert nb.get("transformer") == "sklearn"


@pytest.mark.parametrize("rep_key", ["X_pca_harmony", "X_scVI"])
def test_batch_corrected_rep_cluster_then_umap_coordinated_neighbors(rep_key: str):
    """Simulate batch correction output: active rep + same use_rep for cluster and embed."""
    adata = _make_normalized_adata(n_cells=85, seed=11)
    rng = np.random.default_rng(7)
    adata.obsm[rep_key] = rng.standard_normal((adata.n_obs, 11), dtype=np.float32)
    adata.uns["zerna_active_representation"] = rep_key

    nn, rs = 14, 3
    cluster = LeidenMethod().execute(
        ClusteringInput(
            adata=adata,
            use_rep=rep_key,
            n_neighbors=nn,
            random_state=rs,
            resolution=0.7,
        ),
        compute=None,
    )
    assert cluster.metrics.neighbors_recomputed is True
    assert cluster.metrics.neighbors_reused is False
    nb_after_cluster = adata.uns.get("zerna_neighbors") or {}
    _assert_aligned_neighbors_provenance(nb_after_cluster)
    assert nb_after_cluster.get("last_modified_by_pipeline_step") == "clustering"
    assert nb_after_cluster.get("representation_used_for_neighbors") == rep_key
    assert adata.uns["zerna_active_representation"] == rep_key

    embed = UMAPMethod().execute(
        UMAPInput(adata=adata, use_rep=rep_key, n_neighbors=nn, random_state=rs),
        compute=None,
    )
    assert embed.metrics.neighbors_reused is True
    assert embed.metrics.neighbors_recomputed is False
    nb_after_embed = adata.uns.get("zerna_neighbors") or {}
    _assert_aligned_neighbors_provenance(nb_after_embed)
    assert nb_after_embed.get("last_modified_by_pipeline_step") == "embedding_umap"
    assert nb_after_embed.get("graph_reused") is True
    assert nb_after_embed.get("graph_recomputed") is False
    assert int(adata.uns["neighbors"]["params"]["n_neighbors"]) == nn
    assert adata.uns["neighbors"]["params"]["method"] == "gauss"
    assert adata.uns["zerna_active_representation"] == rep_key


def test_second_clustering_recomputes_neighbors_when_representation_changes():
    """Changing use_rep between clustering runs must invalidate and rebuild the graph."""
    adata = _make_normalized_adata(n_cells=72, seed=2)
    rng = np.random.default_rng(0)
    adata.obsm["X_alt"] = rng.standard_normal((adata.n_obs, 9), dtype=np.float32)
    nn, rs = 12, 1

    LeidenMethod().execute(
        ClusteringInput(adata=adata, use_rep="X_pca", n_neighbors=nn, random_state=rs),
        compute=None,
    )
    nb1 = adata.uns.get("zerna_neighbors") or {}
    assert nb1.get("graph_recomputed") is True
    assert nb1.get("representation_used_for_neighbors") == "X_pca"

    LeidenMethod().execute(
        ClusteringInput(adata=adata, use_rep="X_alt", n_neighbors=nn, random_state=rs),
        compute=None,
    )
    nb2 = adata.uns.get("zerna_neighbors") or {}
    _assert_aligned_neighbors_provenance(nb2)
    assert nb2.get("graph_recomputed") is True
    assert nb2.get("graph_reused") is False
    assert nb2.get("last_modified_by_pipeline_step") == "clustering"
    assert nb2.get("representation_used_for_neighbors") == "X_alt"
    assert adata.uns["neighbors"]["params"].get("use_rep") == "X_alt"


def test_umap_reuses_only_compatible_neighbor_graph_after_clustering():
    """Embed step must not reuse a graph built with different k/rep/method than requested."""
    adata = _make_normalized_adata(n_cells=88, seed=5)
    nn, rs = 15, 0
    LeidenMethod().execute(
        ClusteringInput(adata=adata, n_neighbors=nn, random_state=rs, resolution=0.6),
        compute=None,
    )
    assert (adata.uns.get("zerna_neighbors") or {}).get(
        "last_modified_by_pipeline_step"
    ) == "clustering"

    UMAPMethod().execute(UMAPInput(adata=adata, n_neighbors=nn, random_state=rs), compute=None)
    nb = adata.uns.get("zerna_neighbors") or {}
    _assert_aligned_neighbors_provenance(nb)
    assert nb.get("graph_reused") is True
    assert nb.get("last_modified_by_pipeline_step") == "embedding_umap"


def test_umap_recomputes_when_neighbors_graph_is_stale_after_clustering():
    """If connectivities become incompatible (e.g. umap method), embed refreshes graph and metadata."""
    adata = _make_normalized_adata(n_cells=76, seed=9)
    nn, rs = 15, 0
    LeidenMethod().execute(
        ClusteringInput(adata=adata, n_neighbors=nn, random_state=rs, resolution=0.5),
        compute=None,
    )
    assert adata.uns["neighbors"]["params"]["method"] == "gauss"

    sc.pp.neighbors(adata, n_neighbors=nn, use_rep="X_pca", random_state=rs)
    assert adata.uns["neighbors"]["params"]["method"] == "umap"

    UMAPMethod().execute(UMAPInput(adata=adata, n_neighbors=nn, random_state=rs), compute=None)
    assert adata.uns["neighbors"]["params"]["method"] == "gauss"
    nb = adata.uns.get("zerna_neighbors") or {}
    _assert_aligned_neighbors_provenance(nb)
    assert nb.get("graph_recomputed") is True
    assert nb.get("graph_reused") is False
    assert nb.get("last_modified_by_pipeline_step") == "embedding_umap"
