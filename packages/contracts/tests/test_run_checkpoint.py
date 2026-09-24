"""Tests for RunCheckpoint contract compatibility."""

from datetime import datetime
from uuid import uuid4

from zerna_contracts.enums import RunStatus
from zerna_contracts.run_checkpoint import RunCheckpoint


def test_run_checkpoint_accepts_legacy_object_step_name():
    """Legacy object-shaped step references should coerce to the step name."""
    checkpoint = RunCheckpoint(
        run_id=uuid4(),
        step_name={"name": "batch_correct", "enabled_if": "batch_correction"},
        status=RunStatus.COMPLETED,
        artifact_refs=[],
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        error_message=None,
    )

    assert checkpoint.step_name == "batch_correct"
