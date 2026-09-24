"""Provenance helpers for batch integration (Harmony / scVI)."""

from __future__ import annotations

from typing import Any, Literal

import anndata as ad


def resolve_integration_engine(parameters: dict[str, Any]) -> Literal["harmony", "scvi"]:
    """User-facing engine from integration_mode, else legacy batch_method / method."""
    im = str(parameters.get("integration_mode") or "").strip().lower()
    if im in ("harmony", "scvi"):
        return im  # type: ignore[return-value]
    legacy = (
        str(parameters.get("batch_method") or parameters.get("method") or "harmony").strip().lower()
    )
    if legacy in ("harmony", "scvi"):
        return legacy  # type: ignore[return-value]
    return "harmony"


def finalize_zerna_integration_provenance(
    adata: ad.AnnData,
    *,
    executed_engine: Literal["harmony", "scvi"],
    parameters: dict[str, Any],
    metrics: dict[str, Any],
    step_name: str,
    harmony_max_iter_default: int = 10,
) -> None:
    """Merge explicit requested vs executed integration metadata into uns['zerna_integration']."""
    requested = resolve_integration_engine(parameters)
    batch_key_requested = parameters.get("batch_key")
    batch_key_raw = metrics.get("batch_key")
    batch_key_resolved: str | None
    if batch_key_raw in (None, "", "none"):
        batch_key_resolved = None
    else:
        batch_key_resolved = str(batch_key_raw)

    fallback_applied = False
    fallback_reason: str | None = None
    if metrics.get("fallback_method") == "harmony":
        fallback_applied = True
        fallback_reason = str(metrics.get("fallback_reason") or "scvi_import_or_runtime_failure")
    elif requested == "scvi" and executed_engine == "harmony":
        fallback_applied = True
        fallback_reason = "scvi_optional_dependency_unavailable_in_worker"

    rep_out = "X_pca_harmony" if executed_engine == "harmony" else "X_scVI"
    rep_in = "X_pca" if executed_engine == "harmony" else "integer_counts_matrix"
    active = adata.uns.get("zerna_active_representation")

    n_batches = metrics.get("n_batches")
    n_comp = None
    if rep_out in adata.obsm:
        n_comp = int(adata.obsm[rep_out].shape[1])

    block: dict[str, Any] = {
        "method": executed_engine,
        "method_requested": requested,
        "method_executed": executed_engine,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "batch_key_requested": batch_key_requested,
        "batch_key_resolved": batch_key_resolved,
        "representation_input": rep_in,
        "representation_output": rep_out,
        "representation_obsm": rep_out,
        "x_preserved": True,
        "n_batches": n_batches,
        "compute_backend": metrics.get("compute_backend"),
        "requested_compute_backend": metrics.get("requested_compute_backend"),
        "harmony_output_obsm": "X_pca_harmony",
        "scvi_output_obsm": "X_scVI",
        "downstream_use_obsm": active,
        "clustering_and_embedding_should_use_obsm": active,
        "pipeline_step_name": step_name,
    }

    if executed_engine == "harmony":
        block["n_components"] = (
            n_comp
            if n_comp is not None
            else int(parameters.get("n_pcs", parameters.get("pca_n_components", 50)))
        )
        block["max_iter_harmony"] = int(
            parameters.get("max_iter_harmony", harmony_max_iter_default)
        )
    else:
        block["n_latent"] = n_comp if n_comp is not None else int(parameters.get("n_latent", 30))
        block["n_layers"] = int(parameters.get("n_layers", 2))
        meff = metrics.get("scvi_max_epochs_effective")
        if isinstance(meff, int):
            block["max_epochs_effective"] = meff

    prev = adata.uns.get("zerna_integration")
    if isinstance(prev, dict):
        merged = {**prev, **block}
    else:
        merged = block
    adata.uns["zerna_integration"] = merged
