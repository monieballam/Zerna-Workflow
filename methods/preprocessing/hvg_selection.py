"""Highly variable gene (HVG) selection method for single-cell RNA-seq data."""

from __future__ import annotations

import logging
from typing import Any, Literal

import anndata as ad
import numpy as np
import scanpy as sc
import scipy.sparse as sp
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition
from methods.data.obs_keys import resolve_batch_key

logger = logging.getLogger(__name__)


def _memory_audit_matrix(matrix: Any) -> dict[str, Any]:
    if sp.issparse(matrix):
        return {
            "sparse": True,
            "format": type(matrix).__name__,
            "data_dtype": str(matrix.data.dtype),
        }
    arr = np.asarray(matrix)
    return {"sparse": False, "format": "ndarray", "data_dtype": str(arr.dtype)}


_SEURAT_V3_FALLBACK_WARNING = (
    "seurat_v3 expects raw or integer-like counts in adata.layers['counts']; none found — "
    "fell back to adata.X for backward compatibility. Results may not match standard "
    "Seurat v3 HVG behavior on count data."
)

_SEURAT_V3_NUMERICAL_FALLBACK_WARNING = (
    "seurat_v3 HVG selection failed with a singular loess fit; retried with flavor='seurat' "
    "on adata.X so the pipeline can proceed. Provenance records the original error."
)

_SEURAT_V3_NUMERICAL_ERROR_MARKERS = (
    "reciprocal condition number",
    "svddc failed in l2fit",
)


def _matrix_appears_integer_like(matrix: Any) -> bool:
    """Heuristic audit: whether sampled values look count-like (non-negative, near-integers)."""
    if sp.issparse(matrix):
        data = matrix.data
        if data.size == 0:
            return True
        take = min(5000, data.size)
        sample = np.asarray(data[:take], dtype=np.float32)
    else:
        arr = np.asarray(matrix)
        if arr.size == 0:
            return True
        flat = arr.ravel()
        step = max(1, flat.size // 2000)
        sample = np.asarray(flat[::step][:2000], dtype=np.float32)
    if sample.size == 0:
        return True
    finite = np.isfinite(sample)
    if not finite.any():
        return False
    sample = sample[finite]
    if (sample < 0).any():
        return False
    rounded = np.rint(sample)
    return bool(np.mean(np.isclose(sample, rounded, rtol=1e-5, atol=1e-7)) >= 0.99)


class HVGSelectionInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    n_top_genes: int = Field(default=2000, ge=1)
    flavor: str = "seurat_v3"
    batch_key: str | None = None


class HVGSelectionMetrics(BaseModel):
    n_genes_total: int
    n_hvgs_selected: int
    flavor_requested: str
    flavor_executed: str
    flavor_fallback_applied: bool = False
    flavor_fallback_reason: str | None = None
    requested_hvg_batch_key: str | None
    resolved_batch_key: str | None
    resolved_source_matrix: Literal["counts", "X"]
    hvg_layer: str | None
    used_counts_like_input: bool
    seurat_v3_fell_back_to_x: bool
    seurat_v3_fallback_warning: str | None = None
    source_matrix_appears_integer_like: bool
    subset_genes: bool = False
    hvg_source_matrix_profile: dict[str, Any] | None = None
    scanpy_hvg_layer_argument: str | None = None
    float32_friendly_source_audit: bool | None = None


class HVGSelectionOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: HVGSelectionMetrics


class HVGSelectionMethod(MethodDefinition):
    name = "hvg_selection"
    version = "1.2.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return HVGSelectionInput

    def output_schema(self):
        return HVGSelectionOutput

    def execute(self, input: HVGSelectionInput, compute) -> HVGSelectionOutput:
        del compute
        adata = input.adata

        flavor_executed = str(input.flavor or "").strip() or "seurat_v3"
        flavor_requested = flavor_executed
        flavor_fallback_applied = False
        flavor_fallback_reason: str | None = None

        raw_batch = input.batch_key
        if isinstance(raw_batch, str) and not raw_batch.strip():
            raw_batch = None
        requested_hvg_batch_key = raw_batch
        resolved_batch_key = resolve_batch_key(adata, input.batch_key, strict=False)

        layer: str | None = None
        if flavor_executed == "seurat_v3" and "counts" in adata.layers:
            layer = "counts"

        seurat_v3_fell_back_to_x = flavor_executed == "seurat_v3" and layer is None
        fallback_warning: str | None = None
        if seurat_v3_fell_back_to_x:
            fallback_warning = _SEURAT_V3_FALLBACK_WARNING
            logger.warning("HVG Selection (seurat_v3): %s", fallback_warning)

        source_matrix = adata.layers[layer] if layer is not None else adata.X
        source_profile = _memory_audit_matrix(source_matrix)
        f32_audit = source_profile.get("data_dtype") == str(np.dtype(np.float32))
        source_matrix_appears_integer_like = _matrix_appears_integer_like(source_matrix)
        resolved_source_matrix: Literal["counts", "X"] = "counts" if layer is not None else "X"
        used_counts_like_input = layer == "counts"

        try:
            sc.pp.highly_variable_genes(
                adata,
                n_top_genes=input.n_top_genes,
                flavor=flavor_executed,
                batch_key=resolved_batch_key,
                layer=layer,
                inplace=True,
            )
        except ValueError as exc:
            error_text = str(exc).lower()
            numerical_issue = any(
                marker in error_text for marker in _SEURAT_V3_NUMERICAL_ERROR_MARKERS
            )
            if flavor_executed != "seurat_v3" or not numerical_issue:
                raise
            logger.warning(
                "HVG Selection (seurat_v3): %s Original error: %s",
                _SEURAT_V3_NUMERICAL_FALLBACK_WARNING,
                exc,
            )
            flavor_fallback_applied = True
            flavor_fallback_reason = str(exc)
            flavor_executed = "seurat"
            layer = None
            resolved_source_matrix = "X"
            used_counts_like_input = False
            source_matrix = adata.X
            source_profile = _memory_audit_matrix(source_matrix)
            f32_audit = source_profile.get("data_dtype") == str(np.dtype(np.float32))
            source_matrix_appears_integer_like = _matrix_appears_integer_like(source_matrix)
            sc.pp.highly_variable_genes(
                adata,
                n_top_genes=input.n_top_genes,
                flavor=flavor_executed,
                batch_key=resolved_batch_key,
                layer=layer,
                inplace=True,
            )

        n_hvgs = int(adata.var["highly_variable"].sum())

        zerna_block = {
            "flavor_requested": flavor_requested,
            "flavor_executed": flavor_executed,
            "flavor_fallback_applied": flavor_fallback_applied,
            "flavor_fallback_reason": flavor_fallback_reason,
            "requested_hvg_batch_key": requested_hvg_batch_key,
            "resolved_batch_key": resolved_batch_key,
            "resolved_source_matrix": resolved_source_matrix,
            "hvg_layer": layer,
            "used_counts_like_input": used_counts_like_input,
            "seurat_v3_fell_back_to_x": seurat_v3_fell_back_to_x,
            "seurat_v3_fallback_warning": fallback_warning,
            "source_matrix_appears_integer_like": source_matrix_appears_integer_like,
            "hvg_source_matrix_profile": source_profile,
            "scanpy_hvg_layer_argument": layer,
            "float32_friendly_source_audit": f32_audit,
            "subset_genes": False,
            "n_top_genes": input.n_top_genes,
            # Legacy keys for older readers / exports:
            "flavor": flavor_executed,
            "counts_layer": layer,
            "batch_key": resolved_batch_key,
        }
        adata.uns["zerna_hvg"] = zerna_block

        metrics = HVGSelectionMetrics(
            n_genes_total=int(adata.n_vars),
            n_hvgs_selected=n_hvgs,
            flavor_requested=flavor_requested,
            flavor_executed=flavor_executed,
            flavor_fallback_applied=flavor_fallback_applied,
            flavor_fallback_reason=flavor_fallback_reason,
            requested_hvg_batch_key=requested_hvg_batch_key,
            resolved_batch_key=resolved_batch_key,
            resolved_source_matrix=resolved_source_matrix,
            hvg_layer=layer,
            used_counts_like_input=used_counts_like_input,
            seurat_v3_fell_back_to_x=seurat_v3_fell_back_to_x,
            seurat_v3_fallback_warning=fallback_warning,
            source_matrix_appears_integer_like=source_matrix_appears_integer_like,
            subset_genes=False,
            hvg_source_matrix_profile=source_profile,
            scanpy_hvg_layer_argument=layer,
            float32_friendly_source_audit=f32_audit,
        )
        return HVGSelectionOutput(adata=adata, metrics=metrics)
