"""Tests for AnnData.uns provenance (h5ad-serializable)."""

import json
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np


def test_append_step_uses_steps_json_and_write_h5ad_roundtrip():
    from methods.pipeline.provenance import PROVENANCE_KEY, append_step

    adata = ad.AnnData(np.ones((2, 3), dtype=np.float32))
    append_step(adata, "qc_filter", {"metrics": {"n_cells_before": 10, "n_cells_after": 8}})
    block = adata.uns[PROVENANCE_KEY]
    assert "steps" not in block
    assert isinstance(block.get("steps_json"), str)
    steps = json.loads(block["steps_json"])
    assert len(steps) == 1
    assert steps[0]["step"] == "qc_filter"
    assert steps[0]["metrics"]["n_cells_before"] == 10

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "p.h5ad"
        adata.write_h5ad(path)
        restored = ad.read_h5ad(path)
    rb = restored.uns[PROVENANCE_KEY]
    assert isinstance(rb.get("steps_json"), str)
    assert json.loads(rb["steps_json"])[0]["step"] == "qc_filter"


def test_append_step_decodes_steps_json_for_chaining():
    from methods.pipeline.provenance import PROVENANCE_KEY, append_step

    adata = ad.AnnData(np.ones((1, 1), dtype=np.float32))
    append_step(adata, "a", {"metrics": {}})
    append_step(adata, "b", {"metrics": {}})
    steps = json.loads(adata.uns[PROVENANCE_KEY]["steps_json"])
    assert [s["step"] for s in steps] == ["a", "b"]


def test_expand_provenance_for_export():
    from methods.pipeline.provenance import expand_provenance_for_export

    raw = {"steps_json": json.dumps([{"step": "x", "ts": "t"}]), "run": {"id": "1"}}
    out = expand_provenance_for_export(raw)
    assert "steps_json" not in out
    assert out["steps"] == [{"step": "x", "ts": "t"}]
    assert out["run"] == {"id": "1"}
