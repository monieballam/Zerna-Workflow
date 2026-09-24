"""Lightweight run provenance accumulation on AnnData.uns."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

PROVENANCE_KEY = "zerna_provenance"


def _uns_dict_only(val: Any) -> dict[str, Any]:
    """Treat ``uns`` values as dicts only; do not truth-test with ``or`` (ndarrays are ambiguous)."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return dict(val)
    return {}


def _decode_steps(block: dict[str, Any]) -> list[Any]:
    """Load step history from ``steps_json`` or legacy ``steps`` list."""
    sj = block.get("steps_json")
    if isinstance(sj, str):
        try:
            parsed = json.loads(sj)
        except json.JSONDecodeError:
            return []
        return list(parsed) if isinstance(parsed, list) else []
    legacy = block.get("steps")
    return list(legacy) if isinstance(legacy, list) else []


def _encode_steps(block: dict[str, Any], steps: list[Any]) -> None:
    """Persist steps as one JSON string (h5ad cannot store list-of-dicts in nested uns)."""
    block["steps_json"] = json.dumps(steps, allow_nan=False, default=str)
    block.pop("steps", None)


def expand_provenance_for_export(block: Any) -> Any:
    """Turn ``steps_json`` back into ``steps`` for JSON sidecars / summaries."""
    if not isinstance(block, dict):
        return block
    out = dict(block)
    sj = out.get("steps_json")
    if isinstance(sj, str):
        try:
            out["steps"] = json.loads(sj)
        except json.JSONDecodeError:
            out["steps"] = []
        out.pop("steps_json", None)
    return out


def append_step(adata, step_name: str, payload: dict[str, Any]) -> None:
    """Append one pipeline step record under ``adata.uns[PROVENANCE_KEY]``."""
    block = _uns_dict_only(adata.uns.get(PROVENANCE_KEY))
    steps = _decode_steps(block)
    entry = {
        "step": step_name,
        "ts": datetime.now(UTC).isoformat(),
        **payload,
    }
    steps.append(entry)
    _encode_steps(block, steps)
    adata.uns[PROVENANCE_KEY] = block


def set_run_header(adata, header: dict[str, Any]) -> None:
    """Merge top-level run metadata (sample IDs, template id, etc.)."""
    block = _uns_dict_only(adata.uns.get(PROVENANCE_KEY))
    meta = _uns_dict_only(block.get("run"))
    meta.update(header)
    block["run"] = meta
    adata.uns[PROVENANCE_KEY] = block


def build_summary_dict(adata) -> dict[str, Any]:
    """Return a JSON-serializable provenance + QC/doublet pointers for the final artifact."""
    qc_raw = adata.uns.get("zerna_qc_report")
    qc_report = None
    if isinstance(qc_raw, dict):
        from methods.preprocessing.qc_filter import expand_zerna_qc_report_for_export

        qc_report = expand_zerna_qc_report_for_export(dict(qc_raw))
    elif qc_raw is not None:
        qc_report = qc_raw

    prov_raw = adata.uns.get(PROVENANCE_KEY)
    provenance_export = (
        expand_provenance_for_export(dict(prov_raw)) if isinstance(prov_raw, dict) else prov_raw
    )

    out: dict[str, Any] = {
        "provenance": provenance_export,
        "qc_report": qc_report,
        "doublet_summary": adata.uns.get("zerna_doublet_summary"),
        "ambient_correction": adata.uns.get("zerna_ambient_correction"),
        "normalization": adata.uns.get("zerna_normalization"),
        "hvg": adata.uns.get("zerna_hvg"),
        "pca": adata.uns.get("zerna_pca"),
        "integration": adata.uns.get("zerna_integration"),
        "active_representation": adata.uns.get("zerna_active_representation"),
        "active_counts_layer": adata.uns.get("zerna_active_counts_layer"),
        "clustering": adata.uns.get("zerna_clustering"),
        "neighbors_graph": adata.uns.get("zerna_neighbors"),
        "embedding": adata.uns.get("zerna_embedding"),
        "annotation": adata.uns.get("zerna_annotation"),
        "differential_expression": adata.uns.get("zerna_de"),
        "zerna_pathway": adata.uns.get("zerna_pathway"),
        "zerna_ligand_receptor": adata.uns.get("zerna_ligand_receptor"),
    }
    return {k: v for k, v in out.items() if v is not None}
