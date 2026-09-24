from __future__ import annotations

import pytest

from workflows.run_execution.activities import _raise_if_step_output_empty


def test_qc_filter_zero_cell_guard_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="QC filtering removed all cells"):
        _raise_if_step_output_empty("qc_filter", output_meta={"n_obs": 0})


def test_doublet_detection_zero_cell_guard_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Doublet detection left zero cells"):
        _raise_if_step_output_empty("doublet_detection", output_meta={"n_obs": 0})


def test_zero_cell_guard_ignores_nonempty_outputs() -> None:
    _raise_if_step_output_empty("qc_filter", output_meta={"n_obs": 12})
