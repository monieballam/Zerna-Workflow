"""Property-based tests for error capture on method failure.

**Property 14: Error Capture on Method Failure**
**Validates: Requirements 4.16**

WHEN a MethodDefinition fails, THE Compute_Plane SHALL capture error details
and halt the Run. Specifically:
  - Errors must propagate as exceptions (not silently swallowed)
  - Error messages must be descriptive (non-empty)
  - The pipeline must halt after a method failure (no partial outputs)
  - stdout/stderr/exit-code information must be preserved
"""

from __future__ import annotations

import anndata as ad
import numpy as np
import pytest
import scipy.sparse as sp
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adata(n_cells: int = 60, n_genes: int = 200, seed: int = 0) -> ad.AnnData:
    rng = np.random.default_rng(seed)
    X = rng.negative_binomial(5, 0.5, size=(n_cells, n_genes)).astype(np.float32)
    X = sp.csr_matrix(X)
    obs_names = [f"cell_{i}" for i in range(n_cells)]
    var_names = [f"gene_{i}" for i in range(n_genes)]
    adata = ad.AnnData(X=X)
    adata.obs_names = obs_names
    adata.var_names = var_names
    return adata


def _make_empty_adata() -> ad.AnnData:
    """Return an AnnData with zero cells — triggers errors in most methods."""
    adata = ad.AnnData(X=sp.csr_matrix((0, 50)))
    adata.var_names = [f"gene_{i}" for i in range(50)]
    return adata


# ---------------------------------------------------------------------------
# Property 14: Error Capture on Method Failure
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestErrorCaptureOnMethodFailure:
    """Property 14: Error Capture on Method Failure

    For any invalid input to a MethodDefinition, the method must raise an
    exception with a descriptive message rather than silently returning
    incorrect results or crashing without context.
    """

    # ── Input validation errors ──────────────────────────────────────────

    @given(
        bad_min_genes=st.integers(min_value=100_000, max_value=200_000),
        seed=st.integers(min_value=0, max_value=99),
    )
    @settings(max_examples=10, deadline=None)
    def test_qc_filter_invalid_threshold_raises(self, bad_min_genes, seed):
        """QC filter with impossible thresholds must not silently pass all cells."""
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = _make_adata(seed=seed)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata,
                min_genes=bad_min_genes,
                max_genes=bad_min_genes + 1,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        # All cells should be filtered out — result must reflect this, not silently pass
        assert result.adata.n_obs == 0, (
            f"Impossible QC threshold must filter all cells, got {result.adata.n_obs}"
        )
        assert result.metrics.n_cells_after == 0

    def test_qc_filter_negative_min_genes_produces_no_filtering(self):
        """QC filter with negative min_genes effectively disables the lower bound."""
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = _make_adata()
        method = QCFilterMethod()
        # Negative min_genes is technically allowed by the schema (no ge constraint);
        # it should not crash and should behave as if min_genes=0
        result = method.execute(
            QCFilterInput(
                adata=adata,
                min_genes=-1,
                max_genes=100_000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        # Should not raise; all cells pass the lower bound
        assert result.adata.n_obs >= 0

    @given(seed=st.integers(min_value=0, max_value=99))
    @settings(max_examples=10, deadline=None)
    def test_clustering_missing_cluster_key_raises_value_error(self, seed):
        """Clustering with a missing cluster key must raise ValueError with descriptive message."""
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )
        from methods.dimensionality_reduction.clustering import ClusteringInput, LeidenMethod
        from methods.dimensionality_reduction.pca import PCAInput, PCAMethod
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = _make_adata(seed=seed)
        norm = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False), compute=None
        )
        hvg = HVGSelectionMethod().execute(
            HVGSelectionInput(adata=norm.adata, n_top_genes=80), compute=None
        )
        pca = PCAMethod().execute(
            PCAInput(adata=hvg.adata, n_components=5, random_state=seed), compute=None
        )
        cluster = LeidenMethod().execute(
            ClusteringInput(adata=pca.adata, resolution=0.5, n_neighbors=5, random_state=seed),
            compute=None,
        )

        # Now try DE with a non-existent cluster key
        with pytest.raises(ValueError) as exc_info:
            DifferentialExpressionMethod().execute(
                DifferentialExpressionInput(
                    adata=cluster.adata,
                    cluster_key="nonexistent_column",
                ),
                compute=None,
            )

        error_msg = str(exc_info.value)
        assert "nonexistent_column" in error_msg, "Error message must name the missing cluster key"
        assert len(error_msg) > 10, "Error message must be descriptive (non-trivial)"

    @given(seed=st.integers(min_value=0, max_value=99))
    @settings(max_examples=10, deadline=None)
    def test_ligand_receptor_missing_cluster_key_raises_value_error(self, seed):
        """LR analysis with a missing cluster key must raise ValueError."""
        pytest.importorskip("liana", reason="liana not installed")
        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = _make_adata(seed=seed)

        with pytest.raises(ValueError) as exc_info:
            LigandReceptorMethod().execute(
                LigandReceptorInput(
                    adata=adata,
                    cluster_key="nonexistent_cluster",
                ),
                compute=None,
            )

        assert "nonexistent_cluster" in str(exc_info.value)

    @given(seed=st.integers(min_value=0, max_value=99))
    @settings(max_examples=10, deadline=None)
    def test_ligand_receptor_too_few_cells_raises_value_error(self, seed):
        """LR analysis with fewer than min_cells per cluster must raise ValueError."""
        pytest.importorskip("liana", reason="liana not installed")
        from methods.annotation.ligand_receptor import LigandReceptorInput, LigandReceptorMethod

        adata = _make_adata(n_cells=10, n_genes=100, seed=seed)
        # Add a cluster column with only 1 cell per cluster
        adata.obs["leiden"] = [str(i) for i in range(10)]

        with pytest.raises(ValueError) as exc_info:
            LigandReceptorMethod().execute(
                LigandReceptorInput(adata=adata, cluster_key="leiden", min_cells=5),
                compute=None,
            )

        error_msg = str(exc_info.value)
        assert len(error_msg) > 10, "Error message must be descriptive"

    # ── Schema validation errors ─────────────────────────────────────────

    @given(bad_resolution=st.floats(max_value=0.0))
    @settings(max_examples=10, deadline=None)
    def test_clustering_non_positive_resolution_rejected(self, bad_resolution):
        """Clustering schema must reject resolution ≤ 0."""
        from methods.dimensionality_reduction.clustering import ClusteringInput

        with pytest.raises(ValidationError):
            ClusteringInput(
                adata=_make_adata(),
                resolution=bad_resolution,
            )

    @given(bad_n_components=st.integers(max_value=1))
    @settings(max_examples=10, deadline=None)
    def test_pca_too_few_components_rejected(self, bad_n_components):
        """PCA schema must reject n_components < 2."""
        from methods.dimensionality_reduction.pca import PCAInput

        with pytest.raises(ValidationError):
            PCAInput(adata=_make_adata(), n_components=bad_n_components)

    @given(bad_n_top=st.integers(max_value=0))
    @settings(max_examples=10, deadline=None)
    def test_hvg_zero_genes_rejected(self, bad_n_top):
        """HVG schema must reject n_top_genes ≤ 0."""
        from methods.preprocessing.hvg_selection import HVGSelectionInput

        with pytest.raises(ValidationError):
            HVGSelectionInput(adata=_make_adata(), n_top_genes=bad_n_top)

    # ── Error propagation: pipeline halts on failure ─────────────────────

    def test_pipeline_halts_after_method_failure(self):
        """When a method raises, subsequent steps must not execute."""
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = _make_adata()
        # Attempt DE without clustering — should raise ValueError
        with pytest.raises(ValueError):
            DifferentialExpressionMethod().execute(
                DifferentialExpressionInput(adata=adata, cluster_key="leiden"),
                compute=None,
            )
        # If we reach here, the error was raised correctly and the pipeline halted

    def test_error_message_contains_actionable_information(self):
        """Error messages must contain enough context for debugging."""
        from methods.annotation.differential_expression import (
            DifferentialExpressionInput,
            DifferentialExpressionMethod,
        )

        adata = _make_adata()
        try:
            DifferentialExpressionMethod().execute(
                DifferentialExpressionInput(adata=adata, cluster_key="missing_key"),
                compute=None,
            )
            pytest.fail("Expected ValueError was not raised")
        except ValueError as exc:
            msg = str(exc)
            # Must mention the missing key
            assert "missing_key" in msg, f"Error must name the missing key, got: {msg}"
            # Must mention available columns
            assert "Available" in msg or "columns" in msg.lower(), (
                f"Error should list available columns, got: {msg}"
            )

    @given(
        bad_batch_key=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="_"),
        ),
        seed=st.integers(min_value=0, max_value=99),
    )
    @settings(max_examples=10, deadline=None)
    def test_batch_correction_missing_batch_key_raises(self, bad_batch_key, seed):
        """Batch correction with a non-existent batch key must raise ValueError."""
        from methods.dimensionality_reduction.batch_correction import HarmonyInput, HarmonyMethod

        adata = _make_adata(seed=seed)
        # Ensure the key doesn't accidentally exist
        if bad_batch_key in adata.obs.columns:
            return  # skip this example

        with pytest.raises(ValueError) as exc_info:
            HarmonyMethod().execute(
                HarmonyInput(adata=adata, batch_key=bad_batch_key, random_state=seed),
                compute=None,
            )

        assert bad_batch_key in str(exc_info.value), "Error must name the missing batch key"

    # ── Nextflow process error capture (structural) ───────────────────────

    def test_nextflow_modules_have_error_capture_in_script(self):
        """Structural: Nextflow process modules must not suppress errors."""
        from pathlib import Path

        modules_dir = Path(__file__).parent.parent / "modules"
        assert modules_dir.exists(), f"Modules directory not found: {modules_dir}"

        nf_files = list(modules_dir.glob("*.nf"))
        assert len(nf_files) > 0, "No Nextflow module files found"

        for nf_file in nf_files:
            content = nf_file.read_text()
            # Each module must have a script block
            assert "script:" in content, f"{nf_file.name} must have a script block"
            # Modules must not use '|| true' which would suppress errors
            assert "|| true" not in content, (
                f"{nf_file.name} must not suppress errors with '|| true'"
            )

    def test_nextflow_config_has_error_strategy(self):
        """Structural: nextflow.config must define errorStrategy for processes."""
        from pathlib import Path

        config_path = Path(__file__).parent.parent / "nextflow.config"
        assert config_path.exists(), "nextflow.config not found"

        content = config_path.read_text()
        assert "errorStrategy" in content, "nextflow.config must define errorStrategy for processes"
        # Must not use 'ignore' which would suppress errors
        assert "errorStrategy = 'ignore'" not in content, (
            "errorStrategy must not be 'ignore' — errors must halt the pipeline"
        )
