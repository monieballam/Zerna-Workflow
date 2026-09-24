"""PCA dimensionality reduction method for single-cell RNA-seq data."""

from __future__ import annotations

import logging
import os
from typing import Literal

import anndata as ad
import numpy as np
import scanpy as sc
import scipy.sparse as sp
from zerna_contracts.enums import ComputeBackend, ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition

logger = logging.getLogger(__name__)

_PCA_FLOAT = np.float32
_F32_NAME = np.dtype(np.float32).name


def _memory_audit_x(x) -> dict[str, str | bool]:
    if sp.issparse(x):
        return {
            "sparse": True,
            "format": type(x).__name__,
            "data_dtype": str(x.data.dtype),
        }
    arr = np.asarray(x)
    return {"sparse": False, "format": "ndarray", "data_dtype": str(arr.dtype)}


class PCAInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    n_components: int = Field(default=50, ge=2, le=500)
    use_highly_variable: bool = True
    random_state: int = 0


class PCAMetrics(BaseModel):
    n_components_computed: int
    variance_ratio_top10: list[float]
    n_genes_used_for_pca: int
    use_highly_variable_effective: bool
    pca_decomposition_backend: Literal["scanpy", "torch_svd"]
    pca_input_x_profile: dict[str, str | bool] | None = None
    obsm_x_pca_dtype: str | None = None
    varm_pcs_dtype: str | None = None
    float32_pca_outputs: bool | None = None


class PCAOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: PCAMetrics


def _resolve_hvg_usage(
    adata: ad.AnnData, use_highly_variable_requested: bool
) -> tuple[bool, bool, int]:
    """Return (column_present, use_effective, n_genes_for_cap)."""
    col_present = "highly_variable" in adata.var.columns
    n_vars = int(adata.n_vars)
    if not use_highly_variable_requested:
        return col_present, False, n_vars
    if not col_present:
        logger.warning(
            "PCA: use_highly_variable=True but adata.var has no 'highly_variable' column; "
            "using all genes."
        )
        return False, False, n_vars
    n_hvg = int(adata.var["highly_variable"].sum())
    if n_hvg <= 0:
        logger.warning(
            "PCA: 'highly_variable' column present but no genes marked True; using all genes."
        )
        return True, False, n_vars
    return True, True, n_hvg


def _expand_loadings_to_varm(
    adata: ad.AnnData,
    loadings_sub: np.ndarray,
    *,
    use_hvg: bool,
    hvg_mask: np.ndarray,
) -> np.ndarray:
    """Shape (n_vars, n_comps). loadings_sub is (n_hvg, n_comps) in var order of the subset."""
    loadings_sub = np.asarray(loadings_sub, dtype=_PCA_FLOAT)
    n_comp = loadings_sub.shape[1]
    out = np.zeros((adata.n_vars, n_comp), dtype=_PCA_FLOAT)
    if use_hvg:
        out[hvg_mask, :] = loadings_sub
    else:
        out[:, :] = loadings_sub
    return out


def _ensure_pca_uns_complete(adata: ad.AnnData) -> None:
    """Ensure uns['pca'] has variance + variance_ratio aligned with X_pca width."""
    n = int(adata.obsm["X_pca"].shape[1])
    block = dict(adata.uns.get("pca", {}))
    vr = np.asarray(block.get("variance_ratio", []), dtype=np.float64).ravel()
    var = np.asarray(block.get("variance", []), dtype=np.float64).ravel()
    if vr.size >= n and var.size >= n:
        block["variance"] = var[:n].tolist()
        block["variance_ratio"] = vr[:n].tolist()
        adata.uns["pca"] = block
        return
    x = np.asarray(adata.obsm["X_pca"][:, :n], dtype=_PCA_FLOAT)
    var_f = np.var(x, axis=0, ddof=1).astype(np.float64) * float(max(adata.n_obs - 1, 1))
    tot = float(var_f.sum())
    block["variance"] = var_f.tolist()
    block["variance_ratio"] = (var_f / tot).tolist() if tot > 0 else [0.0] * n
    if "params" not in block:
        block["params"] = {"zero_center": True, "use_highly_variable": False, "mask_var": None}
    adata.uns["pca"] = block


class PCAMethod(MethodDefinition):
    name = "pca"
    version = "1.2.0"
    compute_preference = ComputePreference.GPU_PREFERRED
    supported_backends = {
        ComputeBackend.CPU,
        ComputeBackend.CUDA,
        ComputeBackend.ROCM,
        ComputeBackend.METAL,
    }

    def input_schema(self):
        return PCAInput

    def output_schema(self):
        return PCAOutput

    def execute(self, input: PCAInput, compute) -> PCAOutput:
        adata = input.adata
        pca_input_profile = _memory_audit_x(adata.X)
        n_obs = int(adata.n_obs)
        n_vars_total = int(adata.n_vars)

        hv_col_present, use_effective, n_genes_for_cap = _resolve_hvg_usage(
            adata, input.use_highly_variable
        )
        max_components = max(min(n_obs, n_genes_for_cap) - 1, 1)
        n_components = max(1, min(input.n_components, max_components))

        use_gpu = compute is not None and compute.selected_backend not in (None, ComputeBackend.CPU)
        pca_solver: Literal["scanpy", "torch_svd"] = "scanpy"
        pca_compute_backend = "cpu"

        if use_gpu:
            try:
                pca_compute_backend, pca_solver = self._pca_gpu(
                    adata,
                    n_components,
                    use_effective,
                    input.random_state,
                    compute,
                )
            except Exception as exc:
                logger.warning("PCA GPU path failed (%s); falling back to Scanpy CPU.", exc)
                sc.tl.pca(
                    adata,
                    n_comps=n_components,
                    use_highly_variable=use_effective,
                    random_state=input.random_state,
                )
                pca_solver = "scanpy"
                pca_compute_backend = "cpu"
        else:
            sc.tl.pca(
                adata,
                n_comps=n_components,
                use_highly_variable=use_effective,
                random_state=input.random_state,
            )
            pca_solver = "scanpy"
            pca_compute_backend = "cpu"

        n_computed = int(adata.obsm["X_pca"].shape[1])
        _ensure_pca_uns_complete(adata)

        if "PCs" not in adata.varm or adata.varm["PCs"].shape != (
            adata.n_vars,
            n_computed,
        ):
            _reconstruct_varm_pcs_from_obsm(adata, n_computed, use_effective)

        _downcast_pca_outputs_float32(adata)

        variance_ratio = adata.uns.get("pca", {}).get("variance_ratio", [])
        top10 = [float(v) for v in variance_ratio[:10]]

        n_genes_used = int(adata.var["highly_variable"].sum()) if use_effective else n_vars_total

        x_pca_dt = str(np.asarray(adata.obsm["X_pca"]).dtype)
        pcs_dt = str(np.asarray(adata.varm["PCs"]).dtype) if "PCs" in adata.varm else None
        f32_out = x_pca_dt == _F32_NAME
        if pcs_dt is not None:
            f32_out = f32_out and pcs_dt == _F32_NAME

        adata.uns["zerna_pca"] = {
            "n_components_requested": int(input.n_components),
            "n_components_computed": n_computed,
            "use_highly_variable_requested": bool(input.use_highly_variable),
            "use_highly_variable_effective": use_effective,
            "highly_variable_column_present": hv_col_present,
            "n_genes_used_for_pca": n_genes_used,
            "matrix_representation_at_entry": "X",
            "compute_backend": pca_compute_backend,
            "pca_decomposition_backend": pca_solver,
            "random_state": int(input.random_state),
            "output_representation": "X_pca",
            "pca_input_x_profile": pca_input_profile,
            "obsm_x_pca_dtype": x_pca_dt,
            "varm_pcs_dtype": pcs_dt,
            "float32_pca_outputs": f32_out,
        }
        adata.uns["zerna_active_representation"] = "X_pca"

        return PCAOutput(
            adata=adata,
            metrics=PCAMetrics(
                n_components_computed=n_computed,
                variance_ratio_top10=top10,
                n_genes_used_for_pca=n_genes_used,
                use_highly_variable_effective=use_effective,
                pca_decomposition_backend=pca_solver,
                pca_input_x_profile=pca_input_profile,
                obsm_x_pca_dtype=x_pca_dt,
                varm_pcs_dtype=pcs_dt,
                float32_pca_outputs=f32_out,
            ),
        )

    def _pca_gpu(
        self,
        adata: ad.AnnData,
        n_components: int,
        use_effective: bool,
        random_state: int,
        compute,
    ) -> tuple[str, Literal["torch_svd"]]:
        """Run torch SVD; return (pca_compute_backend_label, solver name)."""
        import torch

        force_device = os.environ.get("ZERNA_PCA_FORCE_TORCH_DEVICE", "").strip()
        if force_device:
            device = force_device
        elif compute.selected_backend == ComputeBackend.METAL:
            device = "mps"
        else:
            device = "cuda"

        hvg_mask = (
            np.asarray(adata.var["highly_variable"].values, dtype=bool)
            if use_effective and "highly_variable" in adata.var.columns
            else np.ones(adata.n_vars, dtype=bool)
        )
        if use_effective:
            X_sub = adata[:, hvg_mask].X
        else:
            X_sub = adata.X

        if sp.issparse(X_sub):
            X = np.asarray(X_sub.toarray(), dtype=_PCA_FLOAT)
        else:
            X = np.asarray(X_sub, dtype=_PCA_FLOAT)
        t = torch.tensor(X, dtype=torch.float32, device=device)
        mean = t.mean(dim=0)
        t = t - mean
        torch.manual_seed(random_state)
        U, S, Vh = torch.linalg.svd(t, full_matrices=False)
        k = min(n_components, U.shape[1], S.shape[0])
        coords = (U[:, :k] * S[:k]).cpu().numpy()
        adata.obsm["X_pca"] = coords.astype(np.float32, copy=False)

        n_samples = max(int(adata.n_obs) - 1, 1)
        variance = (S[:k] ** 2 / n_samples).cpu().numpy().astype(np.float64)
        total_var = float((S**2 / n_samples).sum().cpu())
        vr = (variance / total_var).tolist() if total_var > 0 else [0.0] * k

        loadings_sub = Vh[:k, :].T.cpu().numpy().astype(_PCA_FLOAT, copy=False)
        pcs_full = _expand_loadings_to_varm(
            adata, loadings_sub, use_hvg=use_effective, hvg_mask=hvg_mask
        )
        adata.varm["PCs"] = pcs_full

        adata.uns["pca"] = {
            "params": {
                "zero_center": True,
                "use_highly_variable": use_effective,
                "mask_var": "highly_variable" if use_effective else None,
            },
            "variance": variance.tolist(),
            "variance_ratio": vr,
        }

        if device == "cpu":
            backend_label = "cpu"
        elif device == "mps":
            backend_label = "metal"
        else:
            backend_label = str(compute.selected_backend.value)
        return backend_label, "torch_svd"


def _downcast_pca_outputs_float32(adata: ad.AnnData) -> None:
    if "X_pca" in adata.obsm:
        adata.obsm["X_pca"] = np.asarray(adata.obsm["X_pca"], dtype=_PCA_FLOAT)
    if "PCs" in adata.varm:
        adata.varm["PCs"] = np.asarray(adata.varm["PCs"], dtype=_PCA_FLOAT)


def _reconstruct_varm_pcs_from_obsm(adata: ad.AnnData, n_comps: int, use_hvg: bool) -> None:
    """Reconstruct varm['PCs'] (n_vars × n_comps) from centered X via SVD."""
    hvg_mask = (
        np.asarray(adata.var["highly_variable"].values, dtype=bool)
        if use_hvg and "highly_variable" in adata.var.columns
        else None
    )
    if use_hvg and hvg_mask is not None:
        sub = adata[:, hvg_mask]
        x_src = sub.X
    else:
        x_src = adata.X
    if sp.issparse(x_src):
        X = np.asarray(x_src.toarray(), dtype=_PCA_FLOAT)
    else:
        X = np.asarray(x_src, dtype=_PCA_FLOAT)
    mu = X.mean(axis=0, keepdims=True)
    X = X - np.asarray(mu, dtype=_PCA_FLOAT)
    _, _, vt = np.linalg.svd(X, full_matrices=False)
    loadings = np.asarray(vt.T[:, :n_comps], dtype=_PCA_FLOAT)
    if use_hvg and hvg_mask is not None:
        full = np.zeros((adata.n_vars, n_comps), dtype=_PCA_FLOAT)
        full[hvg_mask, :] = loadings
    else:
        full = loadings
    adata.varm["PCs"] = full
