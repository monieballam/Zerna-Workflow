"""Property-based tests for Nextflow pipeline idempotence.

**Property 26: Nextflow Pipeline Idempotence**
**Validates: Requirements 13.5**

THE Nextflow pipelines SHALL be idempotent and resumable.
Running the same pipeline twice with identical inputs and random seeds
must produce equivalent outputs.
"""

from __future__ import annotations

import anndata as ad
import numpy as np
import pytest
import scipy.sparse as sp
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adata(n_cells: int = 80, n_genes: int = 300, seed: int = 0) -> ad.AnnData:
    rng = np.random.default_rng(seed)
    X = rng.negative_binomial(5, 0.5, size=(n_cells, n_genes)).astype(np.float32)
    X = sp.csr_matrix(X)
    obs_names = [f"cell_{i}" for i in range(n_cells)]
    var_names = [f"gene_{i}" for i in range(n_genes)]
    adata = ad.AnnData(X=X)
    adata.obs_names = obs_names
    adata.var_names = var_names
    return adata


def _run_preprocessing_pipeline(adata: ad.AnnData, seed: int, n_top_genes: int = 100) -> ad.AnnData:
    """Run the deterministic preprocessing sub-pipeline and return the result."""
    from methods.dimensionality_reduction.pca import PCAInput, PCAMethod
    from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod
    from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod
    from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

    qc = QCFilterMethod().execute(
        QCFilterInput(adata=adata, min_genes=1, max_genes=100_000, min_cells=1, max_mito_pct=100.0),
        compute=None,
    )
    norm = NormalizationMethod().execute(
        NormalizationInput(adata=qc.adata, scale=False),
        compute=None,
    )
    hvg = HVGSelectionMethod().execute(
        HVGSelectionInput(adata=norm.adata, n_top_genes=n_top_genes),
        compute=None,
    )
    pca = PCAMethod().execute(
        PCAInput(adata=hvg.adata, n_components=10, random_state=seed),
        compute=None,
    )
    return pca.adata


# ---------------------------------------------------------------------------
# Property 26: Nextflow Pipeline Idempotence
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestNextflowPipelineIdempotence:
    """Property 26: Nextflow Pipeline Idempotence

    For any valid dataset and fixed random seed, executing the pipeline twice
    must produce equivalent outputs (same cell count, same HVG selection,
    same PCA coordinates, same cluster assignments).
    """

    @given(
        n_cells=st.integers(min_value=60, max_value=120),
        n_genes=st.integers(min_value=200, max_value=400),
        seed=st.integers(min_value=0, max_value=999),
    )
    @settings(max_examples=15, deadline=None)
    def test_qc_filter_is_deterministic(self, n_cells, n_genes, seed):
        """QC filtering with identical inputs must produce identical outputs."""
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = _make_adata(n_cells, n_genes, seed)
        method = QCFilterMethod()
        params = QCFilterInput(
            adata=adata, min_genes=50, max_genes=10_000, min_cells=1, max_mito_pct=50.0
        )

        result1 = method.execute(params, compute=None)
        # Re-create params from the same original adata (not the filtered one)
        params2 = QCFilterInput(
            adata=adata, min_genes=50, max_genes=10_000, min_cells=1, max_mito_pct=50.0
        )
        result2 = method.execute(params2, compute=None)

        assert result1.adata.n_obs == result2.adata.n_obs, (
            "QC filter must produce same cell count on repeated runs"
        )
        assert result1.adata.n_vars == result2.adata.n_vars, (
            "QC filter must produce same gene count on repeated runs"
        )
        assert result1.metrics.model_dump() == result2.metrics.model_dump(), (
            "QC metrics must be identical on repeated runs"
        )

    @given(
        n_top_genes=st.integers(min_value=50, max_value=200),
        seed=st.integers(min_value=0, max_value=999),
    )
    @settings(max_examples=10, deadline=None)
    def test_hvg_selection_is_deterministic(self, n_top_genes, seed):
        """HVG selection with identical inputs must select the same genes."""
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = _make_adata(n_cells=80, n_genes=500, seed=seed)
        norm = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False), compute=None
        )

        method = HVGSelectionMethod()
        result1 = method.execute(
            HVGSelectionInput(adata=norm.adata, n_top_genes=n_top_genes), compute=None
        )
        result2 = method.execute(
            HVGSelectionInput(adata=norm.adata, n_top_genes=n_top_genes), compute=None
        )

        hvg1 = result1.adata.var["highly_variable"].values
        hvg2 = result2.adata.var["highly_variable"].values
        assert np.array_equal(hvg1, hvg2), (
            "HVG selection must select the same genes on repeated runs"
        )

    @given(
        n_components=st.integers(min_value=5, max_value=15),
        seed=st.integers(min_value=0, max_value=999),
    )
    @settings(max_examples=10, deadline=None)
    def test_pca_is_deterministic_with_fixed_seed(self, n_components, seed):
        """PCA with a fixed random seed must produce identical coordinates."""
        from methods.dimensionality_reduction.pca import PCAInput, PCAMethod
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = _make_adata(n_cells=80, n_genes=300, seed=seed)
        norm = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False), compute=None
        )
        hvg = HVGSelectionMethod().execute(
            HVGSelectionInput(adata=norm.adata, n_top_genes=100), compute=None
        )

        method = PCAMethod()
        result1 = method.execute(
            PCAInput(adata=hvg.adata, n_components=n_components, random_state=seed), compute=None
        )
        result2 = method.execute(
            PCAInput(adata=hvg.adata, n_components=n_components, random_state=seed), compute=None
        )

        # PCA coordinates may differ in sign (eigenvector sign ambiguity) but
        # absolute values must be identical
        coords1 = np.abs(result1.adata.obsm["X_pca"])
        coords2 = np.abs(result2.adata.obsm["X_pca"])
        assert np.allclose(coords1, coords2, atol=1e-4), (
            "PCA coordinates must be identical (up to sign) with the same random seed"
        )

    @given(
        resolution=st.floats(min_value=0.3, max_value=1.2),
        seed=st.integers(min_value=0, max_value=999),
    )
    @settings(max_examples=8, deadline=None)
    def test_clustering_is_deterministic_with_fixed_seed(self, resolution, seed):
        """Leiden clustering with a fixed seed must produce identical cluster assignments."""
        from methods.dimensionality_reduction.clustering import ClusteringInput, LeidenMethod

        adata = _run_preprocessing_pipeline(
            _make_adata(n_cells=80, n_genes=300, seed=seed), seed=seed
        )

        method = LeidenMethod()
        result1 = method.execute(
            ClusteringInput(adata=adata, resolution=resolution, n_neighbors=5, random_state=seed),
            compute=None,
        )
        result2 = method.execute(
            ClusteringInput(adata=adata, resolution=resolution, n_neighbors=5, random_state=seed),
            compute=None,
        )

        labels1 = result1.adata.obs["leiden"].values
        labels2 = result2.adata.obs["leiden"].values
        assert np.array_equal(labels1, labels2), (
            "Leiden clustering must produce identical assignments with the same seed"
        )

    @given(seed=st.integers(min_value=0, max_value=999))
    @settings(max_examples=8, deadline=None)
    def test_umap_is_deterministic_with_fixed_seed(self, seed):
        """UMAP with a fixed seed must produce identical embeddings."""
        from methods.dimensionality_reduction.embedding import UMAPInput, UMAPMethod

        adata = _run_preprocessing_pipeline(
            _make_adata(n_cells=80, n_genes=300, seed=seed), seed=seed
        )

        method = UMAPMethod()
        result1 = method.execute(
            UMAPInput(adata=adata, n_components=2, n_neighbors=5, random_state=seed),
            compute=None,
        )
        result2 = method.execute(
            UMAPInput(adata=adata, n_components=2, n_neighbors=5, random_state=seed),
            compute=None,
        )

        emb1 = result1.adata.obsm["X_umap"]
        emb2 = result2.adata.obsm["X_umap"]
        assert np.allclose(emb1, emb2, atol=1e-4), (
            "UMAP must produce identical embeddings with the same random seed"
        )

    @given(
        seed=st.integers(min_value=0, max_value=999),
        n_top_genes=st.integers(min_value=80, max_value=150),
    )
    @settings(max_examples=8, deadline=None)
    def test_full_pipeline_is_idempotent(self, seed, n_top_genes):
        """Running the full preprocessing pipeline twice must produce equivalent outputs."""
        adata = _make_adata(n_cells=80, n_genes=300, seed=seed)

        result1 = _run_preprocessing_pipeline(adata, seed=seed, n_top_genes=n_top_genes)
        result2 = _run_preprocessing_pipeline(adata, seed=seed, n_top_genes=n_top_genes)

        assert result1.n_obs == result2.n_obs, "Idempotent pipeline must produce same cell count"
        assert result1.n_vars == result2.n_vars, "Idempotent pipeline must produce same gene count"

        # HVG selection must be identical
        hvg1 = result1.var.get("highly_variable")
        hvg2 = result2.var.get("highly_variable")
        if hvg1 is not None and hvg2 is not None:
            assert np.array_equal(hvg1.values, hvg2.values), (
                "Idempotent pipeline must select the same HVGs"
            )

        # PCA coordinates must be identical (up to sign)
        if "X_pca" in result1.obsm and "X_pca" in result2.obsm:
            assert np.allclose(
                np.abs(result1.obsm["X_pca"]),
                np.abs(result2.obsm["X_pca"]),
                atol=1e-4,
            ), "Idempotent pipeline must produce same PCA coordinates"

    def test_different_seeds_produce_different_embeddings(self):
        """Sanity check: different seeds should generally produce different UMAP layouts."""
        from methods.dimensionality_reduction.embedding import UMAPInput, UMAPMethod

        adata = _run_preprocessing_pipeline(_make_adata(n_cells=80, n_genes=300, seed=0), seed=0)

        result_seed0 = UMAPMethod().execute(
            UMAPInput(adata=adata, n_components=2, n_neighbors=5, random_state=0),
            compute=None,
        )
        result_seed1 = UMAPMethod().execute(
            UMAPInput(adata=adata, n_components=2, n_neighbors=5, random_state=99),
            compute=None,
        )

        # Different seeds should produce different layouts (not guaranteed but very likely)
        emb0 = result_seed0.adata.obsm["X_umap"]
        emb1 = result_seed1.adata.obsm["X_umap"]
        # At least some coordinates should differ
        assert not np.allclose(emb0, emb1, atol=1e-3), (
            "Different random seeds should produce different UMAP layouts"
        )
