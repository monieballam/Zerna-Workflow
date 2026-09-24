"""Normalization method for single-cell RNA-seq data."""

from __future__ import annotations

from typing import Any, Literal

import anndata as ad
import numpy as np
import scanpy as sc
import scipy.sparse as sp
from zerna_contracts.enums import ComputeBackend, ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition

_ACTIVE_COUNTS_UNS_KEY = "zerna_active_counts_layer"
_WORK_DTYPE = np.float32


def _sparse_data_dtype(mat: sp.spmatrix) -> np.dtype:
    return mat.data.dtype


def _memory_profile_matrix(matrix: Any) -> dict[str, Any]:
    if sp.issparse(matrix):
        return {
            "sparse": True,
            "format": type(matrix).__name__,
            "data_dtype": str(_sparse_data_dtype(matrix)),
        }
    arr = np.asarray(matrix)
    return {"sparse": False, "format": "ndarray", "data_dtype": str(arr.dtype)}


class NormalizationInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    target_sum: float = Field(default=1e4, gt=0)
    scale: bool = False
    max_value: float | None = Field(default=10.0)
    persist_counts_layer: bool = True
    source_counts_layer: str | None = Field(
        default=None,
        description=(
            "Explicit layer to normalize from (count-scale matrix). "
            "Use 'X' to force adata.X. When unset, resolution follows: optional pipeline hint "
            f"({_ACTIVE_COUNTS_UNS_KEY}) if that layer exists, else layers['counts'] if present, "
            "else adata.X with optional snapshot into layers['counts']."
        ),
    )


class NormalizationMetrics(BaseModel):
    """Step metrics and backward-compatible ``source_counts_layer`` (= resolved source)."""

    requested_source_counts_layer: str | None = None
    resolved_source_matrix: str
    used_pipeline_active_counts_layer: bool = False
    counts_layer_existed_before: bool
    counts_layer_created_during_step: bool
    target_sum: float
    log1p_applied: bool = True
    scale_applied: bool
    scale_max_value: float | None = None
    x_representation_at_exit: Literal["log1p", "scaled"]
    source_counts_layer: str
    # Memory / dtype audit (optional for backward-compatible JSON readers)
    source_count_matrix_profile: dict[str, Any] | None = None
    active_matrix_dtype: str | None = None
    log1p_layer_dtype: str | None = None
    counts_layer_dtype: str | None = None
    sparse_active_matrix: bool | None = None
    float32_normalized_output: bool | None = None


class NormalizationOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: NormalizationMetrics


class NormalizationMethod(MethodDefinition):
    name = "normalization"
    version = "1.3.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return NormalizationInput

    def output_schema(self):
        return NormalizationOutput

    @staticmethod
    def _resolve_normalization_source_matrix(
        adata: ad.AnnData,
        requested_layer: str | None,
        persist_counts_layer: bool,
    ) -> tuple[Any, str, bool, bool]:
        """Return (matrix, resolved_label, counts_created, used_pipeline_active).

        *counts_created* is True only when this step created ``layers['counts']``.
        *used_pipeline_active* is True when ``zerna_active_counts_layer`` selected the source
        (legacy compatibility with ambient correction and similar writers).
        """
        counts_created = False

        if requested_layer is not None:
            if requested_layer == "X":
                if persist_counts_layer and "counts" not in adata.layers:
                    adata.layers["counts"] = adata.X.copy()
                    counts_created = True
                return adata.X, "X", counts_created, False
            if requested_layer not in adata.layers:
                available = list(adata.layers.keys())
                raise ValueError(
                    f"normalize_source_counts_layer={requested_layer!r} is not in adata.layers "
                    f"(available layers: {available})."
                )
            return adata.layers[requested_layer], requested_layer, counts_created, False

        active = adata.uns.get(_ACTIVE_COUNTS_UNS_KEY)
        if isinstance(active, str) and active.strip():
            key = active.strip()
            if key in adata.layers:
                return adata.layers[key], key, counts_created, True

        if "counts" in adata.layers:
            return adata.layers["counts"], "counts", counts_created, False

        if persist_counts_layer:
            adata.layers["counts"] = adata.X.copy()
            counts_created = True
            return adata.layers["counts"], "counts", counts_created, False

        return adata.X, "X", counts_created, False

    def execute(self, input: NormalizationInput, compute) -> NormalizationOutput:
        adata = input.adata
        counts_layer_existed_before = "counts" in adata.layers

        raw_requested = input.source_counts_layer
        requested_norm = (raw_requested or "").strip() or None

        count_matrix, resolved, counts_created, used_active = (
            self._resolve_normalization_source_matrix(
                adata,
                requested_norm,
                input.persist_counts_layer,
            )
        )
        source_profile = _memory_profile_matrix(count_matrix)

        scale_applied = bool(input.scale)
        x_exit: Literal["log1p", "scaled"] = "scaled" if scale_applied else "log1p"
        scale_max_value = input.max_value if scale_applied else None

        norm_block: dict[str, Any] = {
            "requested_source_counts_layer": requested_norm,
            "resolved_source_matrix": resolved,
            "used_pipeline_active_counts_layer": used_active,
            "counts_layer_existed_before": counts_layer_existed_before,
            "counts_layer_created_during_step": counts_created,
            "target_sum": float(input.target_sum),
            "log1p_applied": True,
            "scale_applied": scale_applied,
            "scale_max_value": scale_max_value,
            "x_representation_at_exit": x_exit,
            "source_counts_layer": resolved,
            "scale": scale_applied,
            "source_count_matrix_profile": source_profile,
            "work_matrix_dtype": str(_WORK_DTYPE),
        }
        adata.uns["zerna_normalization"] = norm_block

        normed = self._normalize_total(count_matrix, input.target_sum)
        logged = self._log1p_inplace(normed)
        adata.X = logged
        if scale_applied:
            adata.layers["log1p"] = logged.copy() if hasattr(logged, "copy") else logged
            if compute is not None and compute.selected_backend not in (None, ComputeBackend.CPU):
                self._scale_gpu(adata, input.max_value, compute)
            else:
                sc.pp.scale(adata, max_value=input.max_value)
                _downcast_scaled_x_to_float32(adata)
        else:
            adata.layers["log1p"] = logged

        counts_dtype = None
        if "counts" in adata.layers:
            cl = adata.layers["counts"]
            counts_dtype = (
                str(_sparse_data_dtype(cl)) if sp.issparse(cl) else str(np.asarray(cl).dtype)
            )
        active_dtype, active_sparse = _active_x_dtype_and_sparse(adata.X)
        f32_ok = active_dtype == np.dtype(_WORK_DTYPE) or str(active_dtype) == str(_WORK_DTYPE)

        log1p_aliases_x = (not scale_applied) and (adata.X is adata.layers.get("log1p"))
        norm_block.update(
            {
                "active_matrix_dtype": str(active_dtype),
                "log1p_layer_dtype": (
                    str(_sparse_data_dtype(adata.layers["log1p"]))
                    if sp.issparse(adata.layers["log1p"])
                    else str(np.asarray(adata.layers["log1p"]).dtype)
                ),
                "counts_layer_dtype": counts_dtype,
                "sparse_active_matrix": active_sparse,
                "float32_normalized_output": bool(f32_ok),
                "log1p_aliases_active_x": log1p_aliases_x,
            }
        )
        adata.uns["zerna_normalization"] = norm_block

        metrics = NormalizationMetrics(
            requested_source_counts_layer=requested_norm,
            resolved_source_matrix=resolved,
            used_pipeline_active_counts_layer=used_active,
            counts_layer_existed_before=counts_layer_existed_before,
            counts_layer_created_during_step=counts_created,
            target_sum=float(input.target_sum),
            log1p_applied=True,
            scale_applied=scale_applied,
            scale_max_value=scale_max_value,
            x_representation_at_exit=x_exit,
            source_counts_layer=resolved,
            source_count_matrix_profile=source_profile,
            active_matrix_dtype=str(active_dtype),
            log1p_layer_dtype=norm_block.get("log1p_layer_dtype"),
            counts_layer_dtype=counts_dtype,
            sparse_active_matrix=active_sparse,
            float32_normalized_output=f32_ok,
        )

        return NormalizationOutput(adata=adata, metrics=metrics)

    @staticmethod
    def _normalize_total(matrix, target_sum: float):
        """Normalize to ``target_sum`` per cell; output sparse CSR or dense ndarray in float32."""
        if sp.issparse(matrix):
            normalized = matrix.tocsr(copy=True)
            cell_sums = np.asarray(normalized.sum(axis=1), dtype=np.float64).ravel()
            scale = np.divide(
                float(target_sum),
                cell_sums,
                out=np.zeros_like(cell_sums, dtype=np.float64),
                where=cell_sums > 0,
            ).astype(_WORK_DTYPE)
            normalized = normalized.multiply(scale[:, None])
            normalized = normalized.tocsr()
            normalized.data = np.asarray(normalized.data, dtype=_WORK_DTYPE)
            return normalized

        arr = np.asarray(matrix)
        work = arr.astype(_WORK_DTYPE, copy=True)
        cell_sums = np.asarray(work.sum(axis=1), dtype=np.float64).ravel()
        scale = np.divide(
            float(target_sum),
            cell_sums,
            out=np.zeros(work.shape[0], dtype=np.float64),
            where=cell_sums > 0,
        )
        work *= scale[:, np.newaxis].astype(_WORK_DTYPE)
        return work

    @staticmethod
    def _log1p_inplace(matrix: Any) -> Any:
        """log1p in place; no second full matrix. Output dtype float32."""
        if sp.issparse(matrix):
            mat = matrix.tocsr()
            mat.data = np.asarray(mat.data, dtype=_WORK_DTYPE)
            np.log1p(mat.data, out=mat.data)
            return mat
        arr = np.asarray(matrix, dtype=_WORK_DTYPE, order="C")
        if not arr.flags.writeable:
            arr = arr.copy()
        np.log1p(arr, out=arr)
        return arr

    def _scale_gpu(self, adata: ad.AnnData, max_value: float | None, compute) -> None:
        if sp.issparse(adata.X):
            sc.pp.scale(adata, max_value=max_value)
            _downcast_scaled_x_to_float32(adata)
            return
        try:
            import torch

            X = np.asarray(adata.X, dtype=_WORK_DTYPE)
            X = np.asarray(X, dtype=_WORK_DTYPE)
            device = "mps" if compute.selected_backend == ComputeBackend.METAL else "cuda"
            t = torch.tensor(X, dtype=torch.float32, device=device)
            mean = t.mean(dim=0)
            std = t.std(dim=0)
            std[std == 0] = 1.0
            t = (t - mean) / std
            if max_value is not None:
                t = t.clamp(-max_value, max_value)
            adata.X = np.asarray(t.cpu().numpy(), dtype=_WORK_DTYPE)
        except Exception:
            sc.pp.scale(adata, max_value=max_value)
            _downcast_scaled_x_to_float32(adata)


def _active_x_dtype_and_sparse(x: Any) -> tuple[np.dtype, bool]:
    if sp.issparse(x):
        return _sparse_data_dtype(x), True
    return np.asarray(x).dtype, False


def _downcast_scaled_x_to_float32(adata: ad.AnnData) -> None:
    x = adata.X
    if sp.issparse(x):
        x.data = np.asarray(x.data, dtype=_WORK_DTYPE)
    else:
        adata.X = np.asarray(x, dtype=_WORK_DTYPE)
