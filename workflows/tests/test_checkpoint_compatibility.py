"""Tests for checkpoint compatibility helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import anndata as ad
import numpy as np
import pandas as pd
from zerna_contracts.enums import RunStatus
from zerna_contracts.run_checkpoint import RunCheckpoint


def test_load_checkpoints_normalizes_legacy_object_step_names(monkeypatch, tmp_path):
    """Legacy object step names should load as canonical strings."""
    from workflows.run_execution import checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module, "_CHECKPOINT_DIR", str(tmp_path))
    run_id = uuid4()
    checkpoint_path = Path(tmp_path) / f"{run_id}.json"
    checkpoint_path.write_text(
        json.dumps(
            [
                {
                    "run_id": str(run_id),
                    "step_name": {"name": "batch_correct", "enabled_if": "batch_correction"},
                    "status": "completed",
                    "artifact_refs": [],
                    "started_at": "2026-03-17T09:32:45.128427",
                    "completed_at": "2026-03-17T09:32:46.128427",
                    "error_message": None,
                }
            ]
        )
    )

    checkpoints = checkpoint_module.load_checkpoints(run_id)

    assert len(checkpoints) == 1
    assert checkpoints[0].step_name == "batch_correct"


def test_persist_checkpoint_replaces_legacy_object_step_entries(monkeypatch, tmp_path):
    """Persisting a normalized checkpoint should replace legacy dict-backed duplicates."""
    from workflows.run_execution import checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module, "_CHECKPOINT_DIR", str(tmp_path))
    run_id = uuid4()
    checkpoint_path = Path(tmp_path) / f"{run_id}.json"
    checkpoint_path.write_text(
        json.dumps(
            [
                {
                    "run_id": str(run_id),
                    "step_name": {"name": "batch_correct", "enabled_if": "batch_correction"},
                    "status": "completed",
                    "artifact_refs": [],
                    "started_at": "2026-03-17T09:32:45.128427",
                    "completed_at": "2026-03-17T09:32:46.128427",
                    "error_message": None,
                }
            ]
        )
    )

    checkpoint_module.persist_checkpoint(
        RunCheckpoint(
            run_id=run_id,
            step_name="batch_correct",
            status=RunStatus.FAILED,
            artifact_refs=[],
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            error_message="failed",
        )
    )

    data = json.loads(checkpoint_path.read_text())
    assert len(data) == 1
    assert data[0]["step_name"] == "batch_correct"
    assert data[0]["status"] == "failed"


def test_load_counts_aligned_adata_reorders_and_subsets_to_current_snapshot(tmp_path):
    """Counts snapshots should align to the current step's filtered/reordered AnnData."""
    from workflows.run_execution.activities import _load_counts_aligned_adata

    counts = ad.AnnData(
        X=np.array(
            [
                [1, 2, 3, 4],
                [5, 6, 7, 8],
                [9, 10, 11, 12],
                [13, 14, 15, 16],
            ]
        ),
        obs=pd.DataFrame(index=["c1", "c2", "c3", "c4"]),
        var=pd.DataFrame(index=["g1", "g2", "g3", "g4"]),
    )
    current = ad.AnnData(
        X=np.array(
            [
                [0.1, 0.2, 0.3],
                [0.4, 0.5, 0.6],
            ]
        ),
        obs=pd.DataFrame({"state": ["a", "b"]}, index=["c3", "c1"]),
        var=pd.DataFrame({"highly_variable": [True, False, True]}, index=["g4", "g2", "g1"]),
    )

    counts_path = tmp_path / "counts.h5ad"
    counts.write_h5ad(counts_path)

    aligned = _load_counts_aligned_adata(current, str(counts_path))

    assert list(aligned.obs_names) == ["c3", "c1"]
    assert list(aligned.var_names) == ["g4", "g2", "g1"]
    assert aligned.obs.equals(current.obs)
    assert aligned.var.equals(current.var)
    assert aligned.X.tolist() == [[12, 10, 9], [4, 2, 1]]


def test_resolve_counts_snapshot_prefers_latest_filtered_snapshot():
    """Resumed runs should use the most filtered raw-count snapshot available."""
    from workflows.run_execution.activities import _resolve_counts_snapshot_s3_key

    initial = "runs/example/_state/snapshots/000_initial.h5ad"

    assert (
        _resolve_counts_snapshot_s3_key(
            initial,
            {
                "qc_filter": "runs/example/_state/snapshots/qc_filter.h5ad",
                "doublet_detection": "runs/example/_state/snapshots/doublet_detection.h5ad",
            },
        )
        == "runs/example/_state/snapshots/doublet_detection.h5ad"
    )
    assert (
        _resolve_counts_snapshot_s3_key(
            initial,
            {"qc_filter": "runs/example/_state/snapshots/qc_filter.h5ad"},
        )
        == "runs/example/_state/snapshots/qc_filter.h5ad"
    )
    assert _resolve_counts_snapshot_s3_key(initial, {}) == initial


def test_repair_counts_snapshot_overrides_stale_initial_reference():
    """Execution-state repair should replace stale initial-count references on resume."""
    from workflows.run_execution.activities import _repair_counts_snapshot_s3_key

    initial = "runs/example/_state/snapshots/000_initial.h5ad"
    repaired = _repair_counts_snapshot_s3_key(
        initial,
        {
            "qc_filter": "runs/example/_state/snapshots/qc_filter.h5ad",
            "doublet_detection": "runs/example/_state/snapshots/doublet_detection.h5ad",
            "normalize": "runs/example/_state/snapshots/normalize.h5ad",
        },
        initial,
    )

    assert repaired == "runs/example/_state/snapshots/doublet_detection.h5ad"
