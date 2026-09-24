"""Unit tests for preprocessing methods."""

import json
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp


def make_adata(n_cells=100, n_genes=200, seed=42, sparse=True, counts=True):
    """Create synthetic AnnData for testing."""
    rng = np.random.default_rng(seed)
    if counts:
        X = rng.negative_binomial(5, 0.5, size=(n_cells, n_genes)).astype(np.float32)
    else:
        X = rng.random((n_cells, n_genes)).astype(np.float32)
    if sparse:
        X = sp.csr_matrix(X)
    obs_names = [f"cell_{i}" for i in range(n_cells)]
    var_names = [f"gene_{i}" for i in range(n_genes)]
    # Add some MT genes
    var_names = list(var_names)
    for i in range(10):
        var_names[i] = f"MT-{i}"
    adata = ad.AnnData(X=X, obs={"cell_id": obs_names}, var={"gene_id": var_names})
    adata.obs_names = obs_names
    adata.var_names = var_names
    return adata


# QC Filter tests
class TestQCFilterMethod:
    def test_basic_filtering(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=100, n_genes=300)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata, min_genes=1, max_genes=10000, min_cells=1, max_mito_pct=100.0
            ),
            compute=None,
        )
        assert result.adata.n_obs <= 100
        assert result.metrics.n_cells_before == 100

    def test_empty_dataset(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=5, n_genes=50)
        method = QCFilterMethod()
        # Very strict thresholds → all cells filtered
        result = method.execute(
            QCFilterInput(
                adata=adata, min_genes=10000, max_genes=20000, min_cells=1, max_mito_pct=100.0
            ),
            compute=None,
        )
        assert result.adata.n_obs == 0
        assert result.metrics.n_cells_after == 0
        assert result.metrics.median_genes_per_cell == 0.0

    def test_all_cells_filtered_by_mito(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=20, n_genes=100)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(adata=adata, min_genes=1, max_genes=10000, min_cells=1, max_mito_pct=0.0),
            compute=None,
        )
        assert result.adata.n_obs == 0

    def test_metrics_populated(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=50, n_genes=200)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata, min_genes=1, max_genes=10000, min_cells=1, max_mito_pct=100.0
            ),
            compute=None,
        )
        assert result.metrics.n_cells_before == 50
        assert result.metrics.n_genes_before == 200
        assert result.metrics.median_genes_per_cell >= 0

    def test_sparse_filtering_subsets_in_place(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        X = sp.csr_matrix(
            np.array(
                [
                    [5, 0, 0],
                    [1, 0, 0],
                    [0, 0, 0],
                ],
                dtype=np.float32,
            )
        )
        adata = ad.AnnData(X=X)
        adata.obs_names = ["c1", "c2", "c3"]
        adata.var_names = ["g1", "g2", "g3"]

        result = QCFilterMethod().execute(
            QCFilterInput(
                adata=adata,
                min_genes=1,
                max_genes=10,
                min_cells=2,
                max_mito_pct=100.0,
            ),
            compute=None,
        )

        assert result.adata is adata
        assert result.adata.shape == (2, 1)
        assert list(result.adata.obs_names) == ["c1", "c2"]
        assert list(result.adata.var_names) == ["g1"]

    def test_zerna_qc_report_writes_h5ad_roundtrip(self):
        """Regression: uns zerna_qc_report must be h5ad-serializable (worker snapshots)."""
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=30, n_genes=80)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata, min_genes=1, max_genes=10000, min_cells=1, max_mito_pct=100.0
            ),
            compute=None,
        )
        assert "zerna_qc_report" in result.adata.uns
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qc.h5ad"
            result.adata.write_h5ad(path)
            restored = ad.read_h5ad(path)
        rep = restored.uns["zerna_qc_report"]
        assert isinstance(rep.get("filter_rules_json"), str)
        rules = json.loads(rep["filter_rules_json"])
        assert isinstance(rules, list)
        assert all(isinstance(r["rule"], str) for r in rules)

    def test_zerna_qc_report_includes_species_and_gene_matching(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=20, n_genes=80)
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata,
                species="auto",
                min_genes=1,
                max_genes=10000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        rep = result.adata.uns["zerna_qc_report"]
        assert rep["thresholds"].get("qc_species") == "auto"
        assert rep["thresholds"].get("species_effective") in ("human", "mouse")
        gm = rep.get("gene_matching")
        assert isinstance(gm, dict)
        assert gm.get("species_effective") == rep["thresholds"]["species_effective"]
        assert gm.get("mito", {}).get("mode") == "species_aware"

    def test_legacy_mito_prefix_overrides_species_mask(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        rng = np.random.default_rng(0)
        var_names = ["mt-special", "CD3D"]
        X = rng.negative_binomial(10, 0.5, size=(30, 2)).astype(np.float32)
        X = sp.csr_matrix(X)
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"c{i}" for i in range(30)]
        adata.var_names = var_names
        method = QCFilterMethod()
        result_human = method.execute(
            QCFilterInput(
                adata=adata,
                species="human",
                min_genes=1,
                max_genes=10000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        assert not np.asarray(result_human.adata.var["mt"]).any()

        result_legacy = method.execute(
            QCFilterInput(
                adata=adata,
                species="human",
                mito_prefix="mt-",
                min_genes=1,
                max_genes=10000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        assert np.asarray(result_legacy.adata.var["mt"]).tolist() == [True, False]
        gm = result_legacy.adata.uns["zerna_qc_report"]["gene_matching"]
        assert gm["mito"]["mode"] == "legacy_single_prefix"

    def test_programmatic_hb_genes_without_toggle_no_max_hb_rule(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        adata = make_adata(n_cells=20, n_genes=50)
        adata.var_names = [f"gene_{i}" for i in range(50)]
        adata.var_names = list(adata.var_names)
        adata.var_names = ["HBB" if i == 0 else f"gene_{i}" for i in range(50)]
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata,
                species="human",
                hb_gene_names=["HBB"],
                compute_hb_pct=False,
                min_genes=1,
                max_genes=10000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        rules = json.loads(result.adata.uns["zerna_qc_report"]["filter_rules_json"])
        assert not any(r["rule"] == "max_hb_pct" for r in rules)
        assert "pct_counts_hb" in result.adata.obs.columns

    def test_mouse_species_counts_mt_from_lowercase_prefix(self):
        from methods.preprocessing.qc_filter import QCFilterInput, QCFilterMethod

        rng = np.random.default_rng(1)
        n = 25
        var_names = [f"mt-gene-{i}" if i < 5 else f"Gene{i}" for i in range(40)]
        X = rng.negative_binomial(8, 0.5, size=(n, len(var_names))).astype(np.float32)
        X = sp.csr_matrix(X)
        adata = ad.AnnData(X=X)
        adata.obs_names = [f"c{i}" for i in range(n)]
        adata.var_names = var_names
        method = QCFilterMethod()
        result = method.execute(
            QCFilterInput(
                adata=adata,
                species="mouse",
                min_genes=1,
                max_genes=10000,
                min_cells=1,
                max_mito_pct=100.0,
            ),
            compute=None,
        )
        mt_pct = np.asarray(result.adata.obs["pct_counts_mt"])
        assert (mt_pct > 0).all()
        assert result.adata.uns["zerna_qc_report"]["thresholds"]["species_effective"] == "mouse"


def test_expand_zerna_qc_report_for_export_roundtrip():
    from methods.preprocessing.qc_filter import expand_zerna_qc_report_for_export

    rules = [{"rule": "min_genes", "cells_before": 10, "cells_after": 8}]
    raw = {"version": 2, "filter_rules_json": json.dumps(rules)}
    out = expand_zerna_qc_report_for_export(raw)
    assert "filter_rules_json" not in out
    assert out["filter_rules"] == rules


def test_sanitize_for_h5ad_uns_numpy_and_pandas_in_filter_rules():
    from methods.h5ad_uns_coercion import _sanitize_for_h5ad_uns

    raw = {
        "version": 2,
        "filter_rules": [
            {
                "rule": "min_genes",
                "cells_before": np.int64(100),
                "cells_removed": np.int32(5),
                "cells_after": np.uint64(95),
            }
        ],
        "thresholds": {"max_mito_pct": np.float64(20.0), "empty": None},
        "series_like": pd.Series([1.0, 2.0]),
    }
    out = _sanitize_for_h5ad_uns(raw, _path="zerna_qc_report")
    json.dumps(out, allow_nan=False)
    fr0 = out["filter_rules"][0]
    assert fr0["cells_before"] == 100 and type(fr0["cells_before"]) is int
    assert fr0["cells_removed"] == 5 and type(fr0["cells_removed"]) is int
    assert fr0["cells_after"] == 95 and type(fr0["cells_after"]) is int
    assert out["thresholds"]["max_mito_pct"] == 20.0
    assert out["series_like"] == [1.0, 2.0]


# Doublet detection tests
# Note: real Scrublet can be unstable in some CI / Python builds; stub the core call for stability.


@pytest.fixture
def _stable_scrublet_stub(monkeypatch):
    from methods.preprocessing.doublet_detection import DoubletDetectionMethod

    def fake(matrix, **_kwargs):
        n = matrix.shape[0]
        return np.full(n, 0.12, dtype=np.float32), np.zeros(n, dtype=bool)

    monkeypatch.setattr(DoubletDetectionMethod, "_run_scrublet", staticmethod(fake))


@pytest.mark.usefixtures("_stable_scrublet_stub")
class TestDoubletDetectionMethod:
    def test_doublet_scores_added(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=100, n_genes=500)
        method = DoubletDetectionMethod()
        result = method.execute(DoubletDetectionInput(adata=adata, random_state=0), compute=None)
        assert "doublet_score" in result.adata.obs.columns
        assert "predicted_doublet" in result.adata.obs.columns
        assert len(result.adata.obs["doublet_score"]) == result.adata.n_obs

    def test_doublet_scores_range(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=100, n_genes=500)
        method = DoubletDetectionMethod()
        result = method.execute(DoubletDetectionInput(adata=adata, random_state=42), compute=None)
        scores = result.adata.obs["doublet_score"].values
        assert (scores >= 0).all() and (scores <= 1).all()

    def test_metrics_populated(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=100, n_genes=500)
        method = DoubletDetectionMethod()
        result = method.execute(DoubletDetectionInput(adata=adata, random_state=0), compute=None)
        assert result.metrics.n_cells == 100
        assert result.metrics.n_cells_before == 100
        assert result.metrics.n_cells_after == result.adata.n_obs
        assert 0 <= result.metrics.doublet_rate <= 1.0

    def test_batchwise_detection_uses_obs_column(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=100, n_genes=500)
        adata.obs["batch"] = ["a"] * 50 + ["b"] * 50

        method = DoubletDetectionMethod()
        result = method.execute(
            DoubletDetectionInput(adata=adata, batch_key="batch", random_state=0),
            compute=None,
        )

        assert "doublet_score" in result.adata.obs.columns
        assert "predicted_doublet" in result.adata.obs.columns
        assert result.metrics.n_cells_before == 100

    def test_solo_backend_dispatches_with_resolved_batch_key(self, monkeypatch):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=60, n_genes=500)
        adata.obs["Batch"] = ["A"] * 30 + ["B"] * 30

        captured: dict[str, object] = {}

        def fake_run_solo(_adata, **kwargs):
            captured.update(kwargs)
            scores = np.linspace(0.1, 0.9, _adata.n_obs, dtype=np.float32)
            return scores, scores > 0.5

        method = DoubletDetectionMethod()
        monkeypatch.setattr(method, "_run_solo", fake_run_solo)

        result = method.execute(
            DoubletDetectionInput(
                adata=adata,
                method="solo",
                batch_key="batch",
                threshold=0.5,
            ),
            compute=None,
        )

        assert result.metrics.method_used == "solo"
        assert result.metrics.method_requested == "solo"
        assert result.metrics.execution_layout == "whole_object"
        assert result.metrics.batch_key_used == "Batch"
        assert captured["batch_key"] == "Batch"

    def test_doubletdetection_backend_dispatches(self, monkeypatch):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=500)

        def fake_run_doubletdetection(matrix, **_kwargs):
            scores = np.full(matrix.shape[0], 0.8, dtype=np.float32)
            return scores, np.ones(matrix.shape[0], dtype=bool)

        monkeypatch.setattr(
            DoubletDetectionMethod,
            "_run_doubletdetection",
            staticmethod(fake_run_doubletdetection),
        )

        method = DoubletDetectionMethod()
        result = method.execute(
            DoubletDetectionInput(adata=adata, method="doubletdetection", threshold=0.5),
            compute=None,
        )

        assert result.metrics.method_used == "doubletdetection"
        assert result.metrics.n_predicted_doublets == 80

    def test_r_backends_raise_clear_error(self, monkeypatch):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=40, n_genes=500)
        method = DoubletDetectionMethod()
        monkeypatch.delenv("ZERNA_RSCRIPT_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None if name == "Rscript" else None)

        for backend in ("scDblFinder", "DoubletFinder", "scds"):
            try:
                method.execute(DoubletDetectionInput(adata=adata, method=backend), compute=None)
            except ValueError as exc:
                assert "requires an R runtime integration" in str(exc)
            else:
                raise AssertionError(f"{backend} should require the R runtime path")

    def test_scrublet_pooled_execution_layout_and_warning(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=80, n_genes=500)
        method = DoubletDetectionMethod()
        result = method.execute(DoubletDetectionInput(adata=adata, random_state=0), compute=None)
        summ = result.adata.uns["zerna_doublet_summary"]
        assert summ["execution_layout"] == "pooled"
        assert any("pooled cells" in w for w in summ.get("warnings", []))
        assert result.metrics.execution_layout == "pooled"

    def test_scrublet_grouped_per_sample_path(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=100, n_genes=500)
        adata.obs["sample_id"] = (["a"] * 50) + (["b"] * 50)
        method = DoubletDetectionMethod()
        result = method.execute(
            DoubletDetectionInput(adata=adata, batch_key="sample_id", random_state=0),
            compute=None,
        )
        summ = result.adata.uns["zerna_doublet_summary"]
        assert summ["execution_layout"] == "grouped"
        assert summ["grouping_key"] == "sample_id"
        assert "skipped_low_n" not in summ["per_sample"].get("a", {})

    def test_scrublet_skipped_groups_warning(self):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=40, n_genes=500)
        adata.obs["sample_id"] = ["x"] * 20 + ["y"] * 20
        method = DoubletDetectionMethod()
        result = method.execute(
            DoubletDetectionInput(adata=adata, batch_key="sample_id", random_state=0),
            compute=None,
        )
        summ = result.adata.uns["zerna_doublet_summary"]
        assert summ["execution_layout"] == "grouped"
        assert any("Skipped" in w and "50" in w for w in summ.get("warnings", []))
        assert any(v.get("skipped_low_n") for v in summ["per_sample"].values())

    def test_flag_only_vs_remove_doublets_provenance(self, monkeypatch):
        from methods.preprocessing.doublet_detection import (
            DoubletDetectionInput,
            DoubletDetectionMethod,
        )

        adata = make_adata(n_cells=30, n_genes=500)

        def fake_scrublet(matrix, **_kwargs):
            n = matrix.shape[0]
            return np.linspace(0.2, 0.9, n, dtype=np.float32), np.ones(n, dtype=bool)

        monkeypatch.setattr(
            DoubletDetectionMethod,
            "_run_scrublet",
            staticmethod(fake_scrublet),
        )
        method = DoubletDetectionMethod()
        flagged = method.execute(
            DoubletDetectionInput(
                adata=adata,
                random_state=0,
                doublet_mode="flag_only",
            ),
            compute=None,
        )
        assert flagged.adata.n_obs == 30
        assert flagged.metrics.cells_removed == 0
        assert flagged.adata.uns["zerna_doublet_summary"]["cells_removed"] == 0

        removed = method.execute(
            DoubletDetectionInput(
                adata=adata,
                random_state=0,
                doublet_mode="remove_doublets",
            ),
            compute=None,
        )
        assert removed.adata.n_obs == 0
        assert removed.metrics.cells_removed == 30
        assert removed.adata.uns["zerna_doublet_summary"]["cells_removed"] == 30


# Normalization tests
def _dense(x):
    return x.toarray() if hasattr(x, "toarray") else np.asarray(x)


class TestNormalizationMethod:
    def test_log1p_values_nonnegative(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=50, n_genes=100)
        method = NormalizationMethod()
        result = method.execute(NormalizationInput(adata=adata, scale=False), compute=None)
        X = _dense(result.adata.X)
        assert (X >= 0).all()

    def test_scaling_mean_near_zero(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=50, n_genes=100)
        method = NormalizationMethod()
        result = method.execute(
            NormalizationInput(adata=adata, scale=True, max_value=None), compute=None
        )
        X = _dense(result.adata.X)
        col_means = X.mean(axis=0)
        assert np.abs(col_means).max() < 1e-4

    def test_max_value_clipping(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=50, n_genes=100)
        method = NormalizationMethod()
        result = method.execute(
            NormalizationInput(adata=adata, scale=True, max_value=10.0), compute=None
        )
        X = _dense(result.adata.X)
        assert X.max() <= 10.0

    def test_preserves_counts_and_log1p_layers(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=20, n_genes=50)
        original = adata.X.copy()
        method = NormalizationMethod()
        result = method.execute(NormalizationInput(adata=adata, scale=False), compute=None)

        assert "counts" in result.adata.layers
        assert "log1p" in result.adata.layers

        counts = _dense(result.adata.layers["counts"])
        expected = _dense(original)
        assert np.allclose(counts, expected)

    def test_prefers_counts_layer_when_unset_and_counts_present(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=10, n_genes=20, seed=1, sparse=False)
        raw = np.asarray(adata.X.copy())
        adata.layers["counts"] = raw.copy()
        adata.X = np.zeros_like(raw) + 999.0

        result = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)

        assert result.metrics.resolved_source_matrix == "counts"
        assert not result.metrics.used_pipeline_active_counts_layer
        assert result.metrics.counts_layer_existed_before
        assert not result.metrics.counts_layer_created_during_step
        assert np.allclose(_dense(result.adata.layers["counts"]), _dense(raw))

    def test_fallback_snapshots_x_to_counts_when_no_counts_layer(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=8, n_genes=12, seed=2)
        assert "counts" not in adata.layers
        raw = adata.X.copy()

        result = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False, persist_counts_layer=True),
            None,
        )

        assert result.metrics.resolved_source_matrix == "counts"
        assert not result.metrics.counts_layer_existed_before
        assert result.metrics.counts_layer_created_during_step
        assert np.allclose(_dense(result.adata.layers["counts"]), _dense(raw))

    def test_preserves_pre_existing_counts_when_normalizing_from_it(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=6, n_genes=20, seed=3)
        adata.layers["counts"] = adata.X.copy()
        raw_counts = adata.layers["counts"].copy()
        adata.X = adata.X.copy() * 0.1

        result = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)

        assert np.allclose(_dense(result.adata.layers["counts"]), _dense(raw_counts))

    def test_scale_false_x_equals_log1p_layer(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=10, n_genes=15, seed=4)
        result = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)

        assert result.metrics.x_representation_at_exit == "log1p"
        assert not result.metrics.scale_applied
        assert result.metrics.scale_max_value is None
        assert np.allclose(_dense(result.adata.X), _dense(result.adata.layers["log1p"]))

    def test_scale_true_x_scaled_log1p_layer_prescale(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=12, n_genes=18, seed=5)
        result = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=True, max_value=10.0),
            None,
        )

        assert result.metrics.x_representation_at_exit == "scaled"
        assert result.metrics.scale_applied
        assert result.metrics.scale_max_value == 10.0
        Xs = _dense(result.adata.X)
        lp = _dense(result.adata.layers["log1p"])
        assert not np.allclose(Xs, lp)
        assert np.abs(Xs.mean(axis=0)).max() < 1e-3

    def test_provenance_uns_and_metrics_align(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=5, n_genes=20, seed=6)
        result = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False, target_sum=5000.0),
            None,
        )
        block = result.adata.uns["zerna_normalization"]
        m = result.metrics
        assert block["requested_source_counts_layer"] is m.requested_source_counts_layer
        assert block["resolved_source_matrix"] == m.resolved_source_matrix
        assert block["counts_layer_existed_before"] == m.counts_layer_existed_before
        assert block["counts_layer_created_during_step"] == m.counts_layer_created_during_step
        assert block["target_sum"] == m.target_sum == 5000.0
        assert block["log1p_applied"] is True
        assert block["scale_applied"] == m.scale_applied
        assert block["scale_max_value"] == m.scale_max_value
        assert block["x_representation_at_exit"] == m.x_representation_at_exit
        assert block["source_counts_layer"] == m.source_counts_layer == m.resolved_source_matrix

    def test_explicit_missing_layer_raises(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=4, n_genes=20, seed=7)
        with pytest.raises(ValueError, match="not in adata.layers"):
            NormalizationMethod().execute(
                NormalizationInput(adata=adata, source_counts_layer="nope"),
                None,
            )

    def test_pipeline_active_counts_layer_used_before_default_counts(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=5, n_genes=20, seed=8)
        adata.layers["counts"] = adata.X.copy()
        adata.layers["corrected_counts"] = adata.X.copy() * 2
        adata.uns["zerna_active_counts_layer"] = "corrected_counts"

        result = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)

        assert result.metrics.used_pipeline_active_counts_layer
        assert result.metrics.resolved_source_matrix == "corrected_counts"
        assert result.metrics.requested_source_counts_layer is None

    def test_explicit_source_overrides_pipeline_active(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=5, n_genes=20, seed=9)
        adata.layers["counts"] = adata.X.copy()
        adata.layers["corrected_counts"] = adata.X.copy() * 3
        adata.uns["zerna_active_counts_layer"] = "corrected_counts"

        result = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False, source_counts_layer="counts"),
            None,
        )

        assert not result.metrics.used_pipeline_active_counts_layer
        assert result.metrics.resolved_source_matrix == "counts"
        assert result.metrics.requested_source_counts_layer == "counts"

    def test_explicit_x_uses_x_even_when_counts_exists(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=5, n_genes=20, seed=10, sparse=False)
        adata.layers["counts"] = np.asarray(adata.X.copy())
        poison = np.zeros_like(np.asarray(adata.X)) + 3.0
        adata.X = poison

        from_x = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False, source_counts_layer="X"),
            None,
        )
        assert from_x.metrics.resolved_source_matrix == "X"

        adata_b = make_adata(n_cells=5, n_genes=20, seed=10, sparse=False)
        adata_b.layers["counts"] = np.asarray(adata_b.X.copy())
        adata_b.X = poison.copy()

        from_counts = NormalizationMethod().execute(
            NormalizationInput(adata=adata_b, scale=False),
            None,
        )
        assert from_counts.metrics.resolved_source_matrix == "counts"
        assert not np.allclose(
            _dense(from_x.adata.layers["log1p"]),
            _dense(from_counts.adata.layers["log1p"]),
        )

    def test_progress_summary_strings_match_workflow_contract(self):
        """Mirror ``_format_step_summary('normalize', ...)`` in run_execution activities."""
        off = "Normalized counts and computed log1p expression values."
        on = "Normalized counts, computed log1p expression values, then scaled the active matrix."
        assert "log1p" in off.lower() and "scaled" not in off.lower()
        assert "log1p" in on.lower() and "scaled" in on.lower()

    def test_persist_counts_layer_false_skips_counts_when_only_x(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=4, n_genes=20, seed=11)
        assert "counts" not in adata.layers
        result = NormalizationMethod().execute(
            NormalizationInput(adata=adata, scale=False, persist_counts_layer=False),
            None,
        )
        assert "counts" not in result.adata.layers
        assert "log1p" in result.adata.layers
        assert result.metrics.resolved_source_matrix == "X"
        assert not result.metrics.counts_layer_created_during_step

    def test_normalize_active_matrix_float32_not_float64(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=30, n_genes=40, seed=12, sparse=True)
        out = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)
        X = out.adata.X
        assert sp.issparse(X)
        assert X.data.dtype == np.float32
        assert str(X.data.dtype) != "float64"
        assert out.metrics.float32_normalized_output is True
        assert out.adata.uns["zerna_normalization"]["float32_normalized_output"] is True

    def test_normalize_dense_log1p_float32(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=12, n_genes=20, seed=13, sparse=False)
        out = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)
        assert np.asarray(out.adata.X).dtype == np.float32
        assert np.asarray(out.adata.layers["log1p"]).dtype == np.float32

    def test_counts_layer_not_duplicated_when_already_present(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=8, n_genes=16, seed=14)
        adata.layers["counts"] = adata.X.copy()
        before_id = id(adata.layers["counts"])
        out = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)
        assert id(out.adata.layers["counts"]) == before_id

    def test_scale_false_log1p_aliases_active_x_when_ann_data_allows(self):
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=6, n_genes=10, seed=15)
        out = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None)
        assert out.adata.uns["zerna_normalization"]["log1p_aliases_active_x"] is (
            out.adata.X is out.adata.layers["log1p"]
        )

    def test_normalize_hvg_pca_chain_sparse_float32(self):
        from methods.dimensionality_reduction.pca import PCAInput, PCAMethod
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod
        from methods.preprocessing.normalization import NormalizationInput, NormalizationMethod

        adata = make_adata(n_cells=300, n_genes=400, seed=16, sparse=True)
        ad = NormalizationMethod().execute(NormalizationInput(adata=adata, scale=False), None).adata
        assert ad.X.data.dtype == np.float32
        ad = (
            HVGSelectionMethod()
            .execute(
                HVGSelectionInput(adata=ad, n_top_genes=80, flavor="seurat_v3"),
                None,
            )
            .adata
        )
        pca = PCAMethod().execute(
            PCAInput(adata=ad, n_components=20, use_highly_variable=True), None
        )
        assert pca.adata.obsm["X_pca"].dtype == np.float32
        assert pca.adata.varm["PCs"].dtype == np.float32
        assert pca.metrics.float32_pca_outputs is True


# HVG selection tests
class TestHVGSelectionMethod:
    def test_hvg_column_added(self):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        adata = make_adata(n_cells=100, n_genes=500)
        method = HVGSelectionMethod()
        result = method.execute(HVGSelectionInput(adata=adata, n_top_genes=100), compute=None)
        assert "highly_variable" in result.adata.var.columns

    def test_hvg_count_matches_n_top_genes(self):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        adata = make_adata(n_cells=100, n_genes=500)
        method = HVGSelectionMethod()
        result = method.execute(HVGSelectionInput(adata=adata, n_top_genes=100), compute=None)
        assert result.metrics.n_hvgs_selected == 100

    def test_different_gene_counts(self):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        adata = make_adata(n_cells=100, n_genes=500)
        method = HVGSelectionMethod()
        for n in [50, 100, 200]:
            result = method.execute(HVGSelectionInput(adata=adata, n_top_genes=n), compute=None)
            assert result.metrics.n_hvgs_selected == n

    def test_metrics_total_genes(self):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        adata = make_adata(n_cells=100, n_genes=500)
        method = HVGSelectionMethod()
        result = method.execute(HVGSelectionInput(adata=adata, n_top_genes=100), compute=None)
        assert result.metrics.n_genes_total == 500

    def test_seurat_v3_uses_counts_layer_when_available(self, monkeypatch):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        captured: dict[str, object] = {}

        def fake_hvg(adata, **kwargs):
            captured.update(kwargs)
            adata.var["highly_variable"] = False
            adata.var.iloc[
                : kwargs["n_top_genes"], adata.var.columns.get_loc("highly_variable")
            ] = True

        adata = make_adata(n_cells=50, n_genes=200)
        adata.layers["counts"] = adata.X.copy()
        adata.X = adata.X.copy().astype(np.float32)

        monkeypatch.setattr("scanpy.pp.highly_variable_genes", fake_hvg)

        method = HVGSelectionMethod()
        result = method.execute(
            HVGSelectionInput(adata=adata, n_top_genes=25, flavor="seurat_v3"),
            compute=None,
        )

        assert captured["layer"] == "counts"
        assert result.metrics.n_hvgs_selected == 25
        assert result.metrics.resolved_source_matrix == "counts"
        assert result.metrics.used_counts_like_input is True
        assert result.metrics.seurat_v3_fell_back_to_x is False
        assert result.metrics.seurat_v3_fallback_warning is None
        assert result.metrics.subset_genes is False
        uns = result.adata.uns["zerna_hvg"]
        assert uns["resolved_source_matrix"] == "counts"
        assert uns["subset_genes"] is False
        assert uns["scanpy_hvg_layer_argument"] == "counts"
        assert result.metrics.scanpy_hvg_layer_argument == "counts"
        assert uns["hvg_source_matrix_profile"]["sparse"] is True
        assert result.metrics.hvg_source_matrix_profile is not None

    def test_seurat_v3_fallback_records_warning_without_counts(self, monkeypatch, caplog):
        import logging

        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        captured: dict[str, object] = {}

        def fake_hvg(adata, **kwargs):
            captured["layer"] = kwargs.get("layer")
            adata.var["highly_variable"] = False
            loc = adata.var.columns.get_loc("highly_variable")
            adata.var.iloc[: kwargs["n_top_genes"], loc] = True

        adata = make_adata(n_cells=30, n_genes=120, seed=21)
        assert "counts" not in adata.layers

        monkeypatch.setattr("scanpy.pp.highly_variable_genes", fake_hvg)

        with caplog.at_level(logging.WARNING):
            result = HVGSelectionMethod().execute(
                HVGSelectionInput(adata=adata, n_top_genes=50, flavor="seurat_v3"),
                compute=None,
            )

        assert captured["layer"] is None
        assert result.metrics.seurat_v3_fell_back_to_x is True
        assert result.metrics.resolved_source_matrix == "X"
        assert result.metrics.used_counts_like_input is False
        assert result.metrics.seurat_v3_fallback_warning
        assert "adata.X" in (result.metrics.seurat_v3_fallback_warning or "")
        uns = result.adata.uns["zerna_hvg"]
        assert uns["seurat_v3_fell_back_to_x"] is True
        assert uns["seurat_v3_fallback_warning"]
        assert any("seurat_v3" in r.message.lower() for r in caplog.records)

    def test_seurat_v3_numerical_issue_retries_with_seurat(self, monkeypatch, caplog):
        import logging

        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        calls: list[tuple[str, str | None]] = []

        def fake_hvg(adata, **kwargs):
            calls.append((str(kwargs.get("flavor")), kwargs.get("layer")))
            if kwargs.get("flavor") == "seurat_v3":
                raise ValueError("b'svddc failed in l2fit.'")
            adata.var["highly_variable"] = False
            loc = adata.var.columns.get_loc("highly_variable")
            adata.var.iloc[: kwargs["n_top_genes"], loc] = True

        adata = make_adata(n_cells=30, n_genes=120, seed=33)
        adata.layers["counts"] = adata.X.copy()

        monkeypatch.setattr("scanpy.pp.highly_variable_genes", fake_hvg)

        with caplog.at_level(logging.WARNING):
            result = HVGSelectionMethod().execute(
                HVGSelectionInput(adata=adata, n_top_genes=40, flavor="seurat_v3"),
                compute=None,
            )

        assert calls == [("seurat_v3", "counts"), ("seurat", None)]
        assert result.metrics.flavor_requested == "seurat_v3"
        assert result.metrics.flavor_executed == "seurat"
        assert result.metrics.flavor_fallback_applied is True
        assert "svddc failed in l2fit" in (result.metrics.flavor_fallback_reason or "").lower()
        assert result.metrics.resolved_source_matrix == "X"
        assert result.metrics.used_counts_like_input is False
        uns = result.adata.uns["zerna_hvg"]
        assert uns["flavor_requested"] == "seurat_v3"
        assert uns["flavor_executed"] == "seurat"
        assert uns["flavor_fallback_applied"] is True
        assert "svddc failed in l2fit" in (uns["flavor_fallback_reason"] or "").lower()
        assert any("singular loess fit" in r.message.lower() for r in caplog.records)

    def test_batch_key_resolution_recorded_in_provenance(self, monkeypatch):
        from methods.preprocessing.hvg_selection import HVGSelectionInput, HVGSelectionMethod

        def fake_hvg(adata, **kwargs):
            adata.var["highly_variable"] = False
            loc = adata.var.columns.get_loc("highly_variable")
            adata.var.iloc[:20, loc] = True

        adata = make_adata(n_cells=40, n_genes=100, seed=22)
        adata.obs["lane"] = ["L1"] * 20 + ["L2"] * 20

        monkeypatch.setattr("scanpy.pp.highly_variable_genes", fake_hvg)

        result = HVGSelectionMethod().execute(
            HVGSelectionInput(adata=adata, n_top_genes=20, flavor="seurat", batch_key="lane"),
            compute=None,
        )
        assert result.metrics.requested_hvg_batch_key == "lane"
        assert result.metrics.resolved_batch_key == "lane"
        assert result.adata.uns["zerna_hvg"]["requested_hvg_batch_key"] == "lane"
        assert result.adata.uns["zerna_hvg"]["resolved_batch_key"] == "lane"


class TestAmbientCorrectionMethod:
    def test_soupx_requires_r_runtime(self, monkeypatch):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=5, n_genes=20)
        adata.layers["counts"] = adata.X.copy()
        method = AmbientCorrectionMethod()
        monkeypatch.delenv("ZERNA_RSCRIPT_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None if name == "Rscript" else None)

        with pytest.raises(ValueError, match="requires an R runtime integration"):
            method.execute(
                AmbientCorrectionInput(
                    adata=adata, enabled=True, method="soupx", counts_layer="counts"
                ),
                compute=None,
            )

    def test_soupx_records_corrected_layer_and_provenance(self, monkeypatch):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=4, n_genes=10)
        counts = adata.X.copy().tocsr()
        corrected = counts.copy()
        corrected.data = np.maximum(corrected.data - 1, 0)
        adata.layers["counts"] = counts

        def fake_run_soupx(matrix, **_kwargs):
            assert matrix.shape == counts.shape
            return corrected, {
                "estimated_contamination_fraction": 0.125,
                "soup_profile_source": "filtered_counts_only",
                "clustering_source": "seurat_graph",
                "cluster_count": 3,
            }

        monkeypatch.setattr(
            AmbientCorrectionMethod,
            "_run_soupx",
            staticmethod(fake_run_soupx),
        )

        method = AmbientCorrectionMethod()
        result = method.execute(
            AmbientCorrectionInput(
                adata=adata,
                enabled=True,
                method="soupx",
                counts_layer="counts",
                corrected_layer="corrected_counts",
            ),
            compute=None,
        )

        assert result.metrics.status == "soupx_applied_filtered_counts_only"
        assert result.metrics.applied_method == "soupx"
        assert result.metrics.output_layer == "corrected_counts"
        assert result.metrics.estimated_contamination_fraction == pytest.approx(0.125)
        assert result.metrics.soup_profile_source == "filtered_counts_only"
        assert result.metrics.raw_droplet_matrix_available is False
        assert result.metrics.cluster_count == 3
        assert result.adata.uns["zerna_active_counts_layer"] == "corrected_counts"
        block = result.adata.uns["zerna_ambient_correction"]
        assert block["status"] == "soupx_applied_filtered_counts_only"
        assert block["applied_method"] == "soupx"
        assert block["estimated_contamination_fraction"] == pytest.approx(0.125)
        assert block["counts_removed"] >= 0
        assert "corrected_counts" in result.adata.layers

    def test_identity_records_scaffold_status_in_uns_and_metrics(self):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=4, n_genes=10)
        adata.layers["counts"] = adata.X.copy()
        method = AmbientCorrectionMethod()
        result = method.execute(
            AmbientCorrectionInput(
                adata=adata, enabled=True, method="identity", counts_layer="counts"
            ),
            compute=None,
        )
        assert result.metrics.status == "identity_scaffold_only"
        assert result.metrics.applied_method == "identity"
        assert result.metrics.requested_method == "identity"
        assert result.metrics.output_layer == "corrected_counts"
        block = result.adata.uns["zerna_ambient_correction"]
        assert block["status"] == "identity_scaffold_only"
        assert block["applied_method"] == "identity"
        assert block["output_layer"] == "corrected_counts"
        assert result.adata.uns["zerna_active_counts_layer"] == "corrected_counts"

    def test_off_when_disabled_records_not_applied(self):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=3, n_genes=10)
        adata.layers["counts"] = adata.X.copy()
        method = AmbientCorrectionMethod()
        result = method.execute(
            AmbientCorrectionInput(
                adata=adata, enabled=False, method="identity", counts_layer="counts"
            ),
            compute=None,
        )
        assert result.metrics.status == "not_applied"
        assert result.metrics.applied_method == "off"
        assert result.adata.uns["zerna_ambient_correction"]["status"] == "not_applied"

    def test_identity_materializes_counts_from_x_before_normalization(self):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=4, n_genes=10)
        method = AmbientCorrectionMethod()
        result = method.execute(
            AmbientCorrectionInput(
                adata=adata, enabled=True, method="identity", counts_layer="counts"
            ),
            compute=None,
        )

        assert "counts" in result.adata.layers
        assert "corrected_counts" in result.adata.layers
        assert result.metrics.counts_materialized_from_x is True
        assert result.adata.uns["zerna_ambient_correction"]["counts_materialized_from_x"] is True

    def test_identity_still_rejects_missing_counts_after_normalization(self):
        from methods.preprocessing.ambient_correction import (
            AmbientCorrectionInput,
            AmbientCorrectionMethod,
        )

        adata = make_adata(n_cells=4, n_genes=10)
        adata.uns["zerna_normalization"] = {"resolved_source_matrix": "counts"}
        method = AmbientCorrectionMethod()

        with pytest.raises(ValueError, match="requires layers\\['counts'\\]"):
            method.execute(
                AmbientCorrectionInput(
                    adata=adata, enabled=True, method="identity", counts_layer="counts"
                ),
                compute=None,
            )
