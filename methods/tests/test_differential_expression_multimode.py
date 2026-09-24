"""Multi-mode differential expression: marker vs pseudobulk contracts."""

from __future__ import annotations

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from methods.annotation.differential_expression import (
    DE_MODE_CONDITION,
    DE_MODE_MARKER,
    DE_MODE_PSEUDOBULK,
    MultiModeDEInput,
    MultiModeDifferentialExpressionMethod,
    normalize_de_mode,
)


def _tiny_adata(*, n_cells: int = 12, n_genes: int = 20) -> ad.AnnData:
    rng = np.random.default_rng(0)
    X = rng.poisson(2.0, size=(n_cells, n_genes)).astype(np.float32)
    obs = pd.DataFrame(
        {
            "leiden": np.repeat(["0", "1"], n_cells // 2),
            "sample": [f"s{i // 3}" for i in range(n_cells)],
            "condition": np.repeat(["A", "B"], n_cells // 2),
        },
        index=[f"c{i}" for i in range(n_cells)],
    )
    adata = ad.AnnData(X=X, obs=obs)
    adata.layers["counts"] = X.copy()
    adata.layers["log1p"] = np.log1p(X)
    return adata


def test_normalize_de_mode_defaults_and_validates() -> None:
    assert normalize_de_mode(None) == DE_MODE_MARKER
    assert normalize_de_mode("") == DE_MODE_MARKER
    assert normalize_de_mode("  MARKER_RANKING ") == DE_MODE_MARKER
    with pytest.raises(ValueError, match="Unsupported de_mode"):
        normalize_de_mode("not_a_mode")


def test_marker_ranking_sets_zerna_de_and_rank_genes_groups() -> None:
    adata = _tiny_adata()
    m = MultiModeDifferentialExpressionMethod()
    out = m.execute(
        MultiModeDEInput(adata=adata, de_mode=DE_MODE_MARKER, cluster_key="leiden"),
        compute=None,
    )
    assert "rank_genes_groups" in out.adata.uns
    assert not out.results_df.empty
    prov = out.adata.uns.get("zerna_de")
    assert isinstance(prov, dict)
    assert prov["de_mode"] == DE_MODE_MARKER
    assert prov["cell_level_analysis"] is True
    assert prov["pseudobulk"] is False
    assert prov["replicate_aware"] is False
    assert prov["condition_aware"] is False
    assert prov.get("statistical_warning")
    assert out.metrics.de_mode == DE_MODE_MARKER


def test_marker_ranking_logreg_handles_missing_logfc_and_pvals() -> None:
    adata = _tiny_adata()
    m = MultiModeDifferentialExpressionMethod()
    out = m.execute(
        MultiModeDEInput(
            adata=adata,
            de_mode=DE_MODE_MARKER,
            cluster_key="leiden",
            de_method="logreg",
            de_n_genes=5,
        ),
        compute=None,
    )
    assert not out.results_df.empty
    assert out.results_df["logfoldchange"].isna().all()
    assert out.results_df["pval"].isna().all()
    assert out.results_df["pval_adj"].isna().all()
    for cluster in out.results_df["cluster"].unique():
        sub = out.results_df[out.results_df["cluster"] == cluster]
        scores = sub["score"].to_numpy()
        assert np.all(scores[:-1] >= scores[1:])


def test_pseudobulk_requires_sample_and_condition_keys() -> None:
    adata = _tiny_adata()
    m = MultiModeDifferentialExpressionMethod()
    with pytest.raises(ValueError, match="de_sample_key"):
        m.execute(
            MultiModeDEInput(
                adata=adata,
                de_mode=DE_MODE_PSEUDOBULK,
                de_condition_key="condition",
            ),
            compute=None,
        )


def test_pseudobulk_fails_on_insufficient_replicates() -> None:
    """One sample per arm after filtering should not silently downgrade."""
    rng = np.random.default_rng(1)
    n_cells, n_genes = 8, 15
    X = rng.poisson(3.0, size=(n_cells, n_genes)).astype(np.float32)
    obs = pd.DataFrame(
        {
            "leiden": ["0"] * n_cells,
            "sample": ["sA0", "sA0", "sB0", "sB0", "sA0", "sA0", "sB0", "sB0"],
            "condition": ["A", "A", "B", "B", "A", "A", "B", "B"],
        },
        index=[f"c{i}" for i in range(n_cells)],
    )
    adata = ad.AnnData(X=X, obs=obs)
    adata.layers["counts"] = X.copy()
    m = MultiModeDifferentialExpressionMethod()
    with pytest.raises(ValueError, match="de_min_samples_per_group"):
        m.execute(
            MultiModeDEInput(
                adata=adata,
                de_mode=DE_MODE_PSEUDOBULK,
                de_sample_key="sample",
                de_condition_key="condition",
                de_min_samples_per_group=2,
                de_min_cells_per_sample=1,
            ),
            compute=None,
        )


def test_condition_within_celltype_requires_focus() -> None:
    adata = _tiny_adata()
    m = MultiModeDifferentialExpressionMethod()
    with pytest.raises(ValueError, match="de_focus_level"):
        m.execute(
            MultiModeDEInput(
                adata=adata,
                de_mode=DE_MODE_CONDITION,
                de_groupby_key="leiden",
                de_sample_key="sample",
                de_condition_key="condition",
            ),
            compute=None,
        )


def _adata_for_pseudobulk_pydeseq2(*, n_genes: int = 35) -> ad.AnnData:
    rng = np.random.default_rng(7)
    n_cells = 24
    X = rng.poisson(18, size=(n_cells, n_genes)).astype(np.float32)
    obs = pd.DataFrame(
        {
            "leiden": ["0"] * n_cells,
            "sample": ["sa1"] * 6 + ["sa2"] * 6 + ["sb1"] * 6 + ["sb2"] * 6,
            "condition": ["A"] * 12 + ["B"] * 12,
        },
        index=[f"c{i}" for i in range(n_cells)],
    )
    adata = ad.AnnData(X=X, obs=obs)
    adata.layers["counts"] = X.copy()
    return adata


def test_pseudobulk_uses_pydeseq2_and_provenance() -> None:
    adata = _adata_for_pseudobulk_pydeseq2()
    m = MultiModeDifferentialExpressionMethod()
    out = m.execute(
        MultiModeDEInput(
            adata=adata,
            de_mode=DE_MODE_PSEUDOBULK,
            de_sample_key="sample",
            de_condition_key="condition",
            de_min_samples_per_group=2,
            de_min_cells_per_sample=1,
        ),
        compute=None,
    )
    assert "rank_genes_groups" not in out.adata.uns
    assert out.pseudobulk_results_df is not None
    assert not out.pseudobulk_results_df.empty
    assert "stat" in out.pseudobulk_results_df.columns
    prov = out.adata.uns["zerna_de"]
    assert prov["inferential_backend_executed"] == "pydeseq2"
    assert prov["count_model_based"] is True
    assert prov["sample_level_metadata_used"] is True
    assert prov["fallback_applied"] is False
    assert prov["counts_source_used"] == "layers_counts"
    agg = prov.get("aggregation_summary") or {}
    assert agg.get("inferential_backend") == "pydeseq2"
    assert "pydeseq2" in str(agg.get("statistical_model", "")).lower()


def test_pseudobulk_tidy_records_compatible_with_csv_export() -> None:
    """Same rename contract as workflows secondary artifact export."""
    adata = _adata_for_pseudobulk_pydeseq2()
    m = MultiModeDifferentialExpressionMethod()
    out = m.execute(
        MultiModeDEInput(
            adata=adata,
            de_mode=DE_MODE_PSEUDOBULK,
            de_sample_key="sample",
            de_condition_key="condition",
            de_min_samples_per_group=2,
            de_min_cells_per_sample=1,
        ),
        compute=None,
    )
    raw = out.adata.uns.get("de_pseudobulk_tidy_records")
    assert isinstance(raw, list) and raw
    pb_df = pd.DataFrame(raw)
    export_pb = pb_df.rename(
        columns={
            "logfoldchange": "log_fold_change",
            "pval": "p_value",
            "pval_adj": "adjusted_p_value",
        }
    )
    assert "log_fold_change" in export_pb.columns
    assert "p_value" in export_pb.columns
    assert "adjusted_p_value" in export_pb.columns


def test_pseudobulk_clear_failure_when_pydeseq2_unavailable(monkeypatch) -> None:
    import methods.annotation.pseudobulk_differential_expression as pb_mod

    def _fail_import() -> tuple:
        # Mirrors production: ImportError is wrapped by _import_pydeseq2 into ValueError.
        raise ValueError(
            "Pseudobulk inferential DE requires the `pydeseq2` package (negative binomial / Wald). "
            "Install it in the compute environment."
        )

    monkeypatch.setattr(pb_mod, "_import_pydeseq2", _fail_import)
    adata = _adata_for_pseudobulk_pydeseq2()
    m = MultiModeDifferentialExpressionMethod()
    with pytest.raises(ValueError, match="pydeseq2|PyDESeq2"):
        m.execute(
            MultiModeDEInput(
                adata=adata,
                de_mode=DE_MODE_PSEUDOBULK,
                de_sample_key="sample",
                de_condition_key="condition",
                de_min_samples_per_group=2,
                de_min_cells_per_sample=1,
            ),
            compute=None,
        )
