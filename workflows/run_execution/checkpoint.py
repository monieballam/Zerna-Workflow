"""Checkpoint persistence for pipeline step failure and resume.

Persists RunCheckpoint records to a JSON file per run so that failed
runs can be resumed from the last successful step.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from zerna_contracts.enums import RunStatus
from zerna_contracts.run_checkpoint import RunCheckpoint

# Default directory for checkpoint storage (overridable via env var)
_CHECKPOINT_DIR = os.getenv("ZERNA_CHECKPOINT_DIR", "/tmp/zerna_checkpoints")


def _normalize_checkpoint_step_name(value: object) -> str | None:
    """Convert legacy object-shaped step names into canonical strings."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _checkpoint_path(run_id: str | UUID) -> Path:
    """Return the filesystem path for a run's checkpoint file."""
    base = Path(_CHECKPOINT_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{run_id}.json"


def persist_checkpoint(checkpoint: RunCheckpoint) -> None:
    """Append or update a checkpoint for a pipeline step.

    Checkpoints are stored as a JSON array in a per-run file.
    If a checkpoint for the same step already exists it is replaced.
    """
    path = _checkpoint_path(checkpoint.run_id)
    existing: list[dict] = []
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    normalized_existing = []
    for checkpoint_data in existing:
        normalized_step_name = _normalize_checkpoint_step_name(checkpoint_data.get("step_name"))
        if normalized_step_name is None:
            continue
        normalized_existing.append({**checkpoint_data, "step_name": normalized_step_name})

    # Replace existing checkpoint for same step, or append
    updated = [c for c in normalized_existing if c.get("step_name") != checkpoint.step_name]
    updated.append(json.loads(checkpoint.model_dump_json()))

    with open(path, "w") as f:
        json.dump(updated, f, indent=2, default=str)


def load_checkpoints(run_id: str | UUID) -> list[RunCheckpoint]:
    """Load all checkpoints for a run."""
    path = _checkpoint_path(run_id)
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    checkpoints: list[RunCheckpoint] = []
    for checkpoint_data in data:
        normalized_step_name = _normalize_checkpoint_step_name(checkpoint_data.get("step_name"))
        if normalized_step_name is None:
            continue
        checkpoints.append(RunCheckpoint(**{**checkpoint_data, "step_name": normalized_step_name}))
    return checkpoints


def get_resume_point(run_id: str | UUID, step_order: list[str]) -> str | None:
    """Determine which step to resume from after a failure.

    Returns the name of the first step that should be (re-)executed,
    or None if no checkpoints exist (start from scratch).
    """
    checkpoints = load_checkpoints(run_id)
    if not checkpoints:
        return None

    completed = {c.step_name for c in checkpoints if c.status == RunStatus.COMPLETED}

    for step in step_order:
        if step not in completed:
            return step
    return None  # all steps completed


def clear_checkpoints(run_id: str | UUID) -> None:
    """Remove all checkpoints for a run (e.g. after successful completion)."""
    path = _checkpoint_path(run_id)
    if path.exists():
        path.unlink()
