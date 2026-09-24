"""Subprocess entrypoint for isolated scientific pipeline steps."""

from __future__ import annotations

import os

# Numba defaults to TBB when the image sets NUMBA_THREADING_LAYER=tbb without a working
# llvmlite TBB binding; workqueue is always available for igraph/leiden paths.
_numba_tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
if _numba_tl in ("", "tbb"):
    os.environ["NUMBA_THREADING_LAYER"] = "workqueue"

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from workflows.run_execution.activities import (
    _json_safe,
    _load_adata,
    _prepare_intermediate_snapshot_adata,
    _read_adata_snapshot,
    _run_step,
    _write_adata_snapshot,
)


def _load_config(path: str | Path) -> dict[str, Any]:
    with open(path) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _write_result(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)


def run_step_from_config(config: dict[str, Any]) -> int:
    step_name = str(config["step_name"])
    output_snapshot_path = str(config["output_snapshot_path"])
    result_path = str(config["result_path"])
    parameters = config.get("parameters", {})
    random_seed = int(config.get("random_seed", 42))
    input_snapshot_path = config.get("input_snapshot_path")
    raw_downloads = config.get("raw_downloads")
    raw_work_dir = config.get("raw_work_dir")

    try:
        if isinstance(input_snapshot_path, str) and input_snapshot_path:
            adata = _read_adata_snapshot(input_snapshot_path)
        elif isinstance(raw_work_dir, str) and isinstance(raw_downloads, list):
            downloaded = [
                (str(item["fname"]), str(item["local_path"]))
                for item in raw_downloads
                if isinstance(item, dict)
                and isinstance(item.get("fname"), str)
                and isinstance(item.get("local_path"), str)
            ]
            if not downloaded:
                raise ValueError("No raw dataset downloads were provided to the step runner")
            load_kw: dict = {}
            esl = config.get("expression_sample_labels")
            if isinstance(esl, list) and all(isinstance(x, str) for x in esl):
                load_kw["expression_sample_labels"] = esl
            dc = config.get("dataset_condition")
            if isinstance(dc, str) and dc.strip():
                load_kw["dataset_condition"] = dc.strip()
            esc = config.get("expression_sample_conditions")
            if isinstance(esc, list) and all(isinstance(x, str) for x in esc):
                load_kw["expression_sample_conditions"] = esc
            pf = config.get("per_file_upload_metadata")
            if isinstance(pf, list) and pf and all(isinstance(x, dict) for x in pf):
                load_kw["per_file_upload_metadata"] = list(pf)
            adata = _load_adata(raw_work_dir, downloaded, **load_kw)
        else:
            raise ValueError("Step runner requires either an input snapshot or raw downloads")
        new_adata, metrics = _run_step(step_name, adata, parameters, random_seed)
        _prepare_intermediate_snapshot_adata(new_adata)
        _write_adata_snapshot(new_adata, output_snapshot_path)
        _write_result(
            result_path,
            {
                "success": True,
                "step_name": step_name,
                "metrics": _json_safe(metrics),
                "n_obs": int(new_adata.n_obs),
                "n_vars": int(new_adata.n_vars),
                "output_snapshot_path": output_snapshot_path,
            },
        )
        return 0
    except Exception as exc:  # pragma: no cover - exercised by parent integration path
        _write_result(
            result_path,
            {
                "success": False,
                "step_name": step_name,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Zerna scientific pipeline step in isolation"
    )
    parser.add_argument("config_path", help="Path to the JSON step configuration file")
    args = parser.parse_args(argv)
    return run_step_from_config(_load_config(args.config_path))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
