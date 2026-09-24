"""Annotation audit suite smoke tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

from methods.annotation.audit.runner import run_annotation_audit, write_audit_outputs
from methods.annotation.hierarchy_columns import (
    AUTO_LEVEL1_COL,
    AUTO_LEVEL2_COL,
    AUTO_LEVEL3_COL,
    FINAL_DISPLAY_COL,
)


def _minimal_obs(n: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            AUTO_LEVEL1_COL: ["Immune"] * n,
            AUTO_LEVEL2_COL: ["T cells"] * n,
            AUTO_LEVEL3_COL: ["CD4"] * n,
            FINAL_DISPLAY_COL: ["Immune | T cells | CD4"] * n,
            "leiden": [str(i % 3) for i in range(n)],
        },
        index=[f"c{i}" for i in range(n)],
    )


def test_audit_runs_on_minimal_consistent_adata():
    obs = _minimal_obs()
    adata = ad.AnnData(X=np.zeros((len(obs), 5)), obs=obs)
    doc = run_annotation_audit(adata, cluster_key="leiden")
    assert doc["version"] == 1
    assert "sections" in doc
    assert doc["summary"]["n_obs"] == len(obs)
    # No stale final_display
    hier = doc["sections"]["hierarchy"]
    assert hier["metrics"].get("final_display_mismatch_vs_hierarchy_rules", 0) == 0


def test_audit_flags_stale_final_display():
    obs = _minimal_obs()
    obs[FINAL_DISPLAY_COL] = "Wrong | Labels | Here"
    adata = ad.AnnData(X=np.zeros((len(obs), 5)), obs=obs)
    doc = run_annotation_audit(adata, cluster_key="leiden")
    hier = doc["sections"]["hierarchy"]
    assert hier["metrics"].get("final_display_mismatch_vs_hierarchy_rules", 0) > 0
    codes = [f["code"] for f in hier["findings"]]
    assert "final_display_stale_or_inconsistent" in codes


def test_write_outputs_json_md_csv():
    obs = _minimal_obs()
    adata = ad.AnnData(X=np.zeros((len(obs), 3)), obs=obs)
    doc = run_annotation_audit(adata)
    with tempfile.TemporaryDirectory() as td:
        paths = write_audit_outputs(doc, Path(td), write_csv=True)
        assert Path(paths["json"]).is_file()
        assert Path(paths["markdown"]).is_file()
        assert Path(paths["csv"]).is_file()
        loaded = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert loaded["summary"]["n_obs"] == len(obs)
