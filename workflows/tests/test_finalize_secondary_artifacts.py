"""Late-stage finalization must not truth-test numpy arrays (ambiguous bool)."""

from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest


def test_coerce_str_list_from_ndarray():
    from workflows.run_execution.activities import _coerce_str_list

    assert _coerce_str_list(np.array(["n_genes_by_counts", "total_counts"])) == [
        "n_genes_by_counts",
        "total_counts",
    ]


def test_coerce_to_python_list_logs_field(monkeypatch, caplog):
    import logging

    from workflows.run_execution.activities import FINALIZE_LOG, _coerce_to_python_list

    caplog.set_level(logging.INFO)
    out = _coerce_to_python_list(np.array([1, 2, 3]), field="test_field")
    assert out == [1, 2, 3]
    assert FINALIZE_LOG in caplog.text
    assert "test_field" in caplog.text


def test_scalar_str_for_display_ndarray_vector():
    from workflows.run_execution.activities import _scalar_str_for_display

    assert _scalar_str_for_display(np.array(["first", "second"])) == "first"
    assert _scalar_str_for_display(np.array([])) is None


def test_first_scalar_annotation_label_avoids_or_on_ndarray():
    from workflows.run_execution.activities import _first_scalar_annotation_label

    assert (
        _first_scalar_annotation_label(
            {"normalized_label": np.array(["T_cell", "B_cell"]), "cell_type": "B_cell"}
        )
        == "T_cell"
    )
    assert _first_scalar_annotation_label({"cell_type": np.array(["Mono"])}) == "Mono"


def test_parameter_str_list_ndarray_replaces_unsafe_or():
    from workflows.run_execution.activities import _parameter_str_list

    default = ["RPS", "RPL"]
    got = _parameter_str_list(np.array(["RPS", "RPS6"]), default)
    assert got == ["RPS", "RPS6"]
    assert _parameter_str_list(None, default) == default


def test_numpy_or_list_raises_value_error():
    """Document why ``x or []`` on ndarray is forbidden in finalization."""
    v = np.array([1, 2])
    with pytest.raises(ValueError, match="truth value of an array"):
        _ = v or []


def test_prepare_secondary_artifacts_with_ndarray_uns_fields(tmp_path: Path):
    """QC obs columns, pathway names, and summaries survive ndarray fields in ``uns``."""
    from workflows.run_execution.activities import _prepare_secondary_artifacts

    n = 5
    obs = pd.Index([f"cell_{i}" for i in range(n)])
    X = np.random.randn(n, 10)
    adata = ad.AnnData(X=X, obs=pd.DataFrame(index=obs))
    adata.obs["n_genes_by_counts"] = np.arange(n)
    adata.obs["total_counts"] = np.linspace(100, 500, n)
    adata.uns["zerna_qc_report"] = {
        "version": 2,
        "n_cells_input": n,
        "n_cells_after_cell_filters": n,
        "n_genes_before_gene_filter": 10,
        "n_genes_removed_low_detection": 0,
        "n_genes_after_gene_filter": 10,
        "filter_rules_json": "[]",
        "thresholds": {},
        "obs_qc_columns": np.array(["n_genes_by_counts", "total_counts"]),
    }
    adata.uns["zerna_provenance"] = {
        "steps_json": "[]",
        "run": {"run_id": "test-run"},
    }
    adata.obsm["pathway_scores"] = np.random.randn(n, 2)
    adata.uns["pathway_scoring_meta"] = {
        "obsm_key": "pathway_scores",
        "pathway_names": np.array(["HALLMARK_A", "HALLMARK_B"]),
    }

    artifacts = _prepare_secondary_artifacts(adata, str(tmp_path))
    kinds = {a["extra_metadata"].get("kind") for a in artifacts}
    assert "qc_summary" in kinds
    assert "qc_metrics" in kinds
    assert "run_summary" in kinds

    qc_json = json.loads((tmp_path / "qc_report" / "qc_summary.json").read_text())
    assert qc_json["obs_qc_columns"] == ["n_genes_by_counts", "total_counts"]

    summary = json.loads((tmp_path / "qc_report" / "run_summary.json").read_text())
    assert "qc_report" in summary
    assert summary["qc_report"]["obs_qc_columns"] == ["n_genes_by_counts", "total_counts"]

    pathway_files = [a for a in artifacts if a["relative_key"].startswith("pathway_scores")]
    assert len(pathway_files) == 1
    assert (tmp_path / "pathway_scores.csv").is_file()
