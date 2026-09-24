"""Optional ambient RNA correction via identity scaffolding or SoupX.

SoupX runs through an R helper and uses a filtered-counts-only approximation in this worker:
the filtered counts matrix is used as both ``toc`` and ``tod``, and the soup profile is set
from filtered counts because raw empty-droplet matrices are not available at this step.
Status is recorded explicitly in ``adata.uns['zerna_ambient_correction']`` and in step metrics.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import anndata as ad
import pandas as pd
import scipy.sparse as sp
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field
from scipy import io as spio

from methods.base import MethodDefinition

R_BACKEND_PACKAGES = {
    "soupx": ("SoupX", "Seurat", "Matrix"),
}
R_METHOD_SCRIPT = Path(__file__).resolve().parents[1] / "programs" / "run_ambient_correction.R"


class AmbientCorrectionInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    enabled: bool = False
    method: Literal["off", "identity", "soupx"] = Field(
        default="off",
        description=(
            "off: no-op. identity: copy counts to corrected_counts (scaffold only). "
            "soupx: run SoupX through the R helper using a filtered-counts-only approximation."
        ),
    )
    counts_layer: str = Field(default="counts", description="Source layer for raw counts.")
    corrected_layer: str = Field(
        default="corrected_counts",
        description="Destination layer for ambient-corrected counts.",
    )
    random_state: int = Field(default=0, description="Random seed used by the SoupX helper.")


class AmbientCorrectionMetrics(BaseModel):
    enabled: bool
    requested_method: str
    applied_method: str
    status: str
    message: str | None = None
    source_layer: str | None = None
    output_layer: str | None = None
    counts_layer: str
    corrected_layer: str | None
    counts_materialized_from_x: bool = False
    estimated_contamination_fraction: float | None = None
    soup_profile_source: str | None = None
    raw_droplet_matrix_available: bool | None = None
    clustering_source: str | None = None
    cluster_count: int | None = None
    n_counts_before: int | None = None
    n_counts_after: int | None = None
    counts_removed: int | None = None


class AmbientCorrectionOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: AmbientCorrectionMetrics


def _ambient_uns_block(
    *,
    requested_method: str,
    applied_method: str,
    status: str,
    message: str | None,
    source_layer: str | None,
    output_layer: str | None,
    active_counts_layer: str,
    counts_materialized_from_x: bool = False,
    estimated_contamination_fraction: float | None = None,
    soup_profile_source: str | None = None,
    raw_droplet_matrix_available: bool | None = None,
    clustering_source: str | None = None,
    cluster_count: int | None = None,
    n_counts_before: int | None = None,
    n_counts_after: int | None = None,
    counts_removed: int | None = None,
) -> dict[str, object]:
    return {
        "requested_method": requested_method,
        "applied_method": applied_method,
        "status": status,
        "message": message,
        "source_layer": source_layer,
        "output_layer": output_layer,
        "active_counts_layer": active_counts_layer,
        "counts_materialized_from_x": counts_materialized_from_x,
        "estimated_contamination_fraction": estimated_contamination_fraction,
        "soup_profile_source": soup_profile_source,
        "raw_droplet_matrix_available": raw_droplet_matrix_available,
        "clustering_source": clustering_source,
        "cluster_count": cluster_count,
        "n_counts_before": n_counts_before,
        "n_counts_after": n_counts_after,
        "counts_removed": counts_removed,
    }


def _matrix_total_counts(matrix: Any) -> int:
    total = matrix.sum()
    if hasattr(total, "item"):
        total = total.item()
    return int(round(float(total)))


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AmbientCorrectionMethod(MethodDefinition):
    name = "ambient_correction"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return AmbientCorrectionInput

    def output_schema(self):
        return AmbientCorrectionOutput

    @staticmethod
    def _unsupported_backend(method: str) -> ValueError:
        return ValueError(
            f"Ambient correction method '{method}' requires an R runtime integration that is not "
            "available in this worker yet."
        )

    @staticmethod
    def _ensure_counts_layer(adata: ad.AnnData, counts_layer: str) -> bool:
        if counts_layer in adata.layers:
            return False
        if "zerna_normalization" in getattr(adata, "uns", {}):
            raise ValueError(
                f"Ambient correction requires layers['{counts_layer}'] (raw counts). "
                "This object already shows normalization state, so raw counts cannot be "
                "reconstructed safely from X at this point."
            )
        adata.layers[counts_layer] = adata.X.copy()
        return True

    @staticmethod
    def _missing_r_packages(method: str, rscript: str) -> tuple[str, ...]:
        normalized_method = str(method).strip().lower()
        required_packages = R_BACKEND_PACKAGES.get(normalized_method, ())
        if not required_packages:
            return ()

        package_args = ", ".join(f'"{package}"' for package in required_packages)
        command = [
            rscript,
            "-e",
            (
                f"pkgs <- c({package_args}); "
                "missing <- pkgs[!vapply(pkgs, requireNamespace, quietly = TRUE, FUN.VALUE = logical(1))]; "
                'cat(paste(missing, collapse = ","))'
            ),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AmbientCorrectionMethod._unsupported_backend(method)

        return tuple(package.strip() for package in completed.stdout.split(",") if package.strip())

    @staticmethod
    def _run_soupx(
        matrix,
        *,
        obs_names: list[str],
        var_names: list[str],
        random_state: int,
    ) -> tuple[sp.csr_matrix, dict[str, object]]:
        rscript = os.getenv("ZERNA_RSCRIPT_PATH") or shutil.which("Rscript")
        if not rscript:
            raise AmbientCorrectionMethod._unsupported_backend("soupx")
        missing_packages = AmbientCorrectionMethod._missing_r_packages("soupx", rscript)
        if missing_packages:
            raise ValueError(
                "Ambient correction method 'soupx' requires an R runtime integration with "
                "packages that are not available in this worker yet: "
                f"{', '.join(missing_packages)}."
            )
        if not R_METHOD_SCRIPT.is_file():
            raise FileNotFoundError(f"R helper script not found: {R_METHOD_SCRIPT}")

        matrix_csr = matrix.tocsr() if hasattr(matrix, "tocsr") else sp.csr_matrix(matrix)
        with tempfile.TemporaryDirectory(prefix="zerna_ambient_") as temp_dir:
            temp_path = Path(temp_dir)
            matrix_path = temp_path / "counts.mtx"
            obs_path = temp_path / "obs.csv"
            genes_path = temp_path / "genes.csv"
            output_matrix_path = temp_path / "corrected_counts.mtx"
            output_metrics_path = temp_path / "metrics.csv"

            spio.mmwrite(matrix_path, matrix_csr.transpose().tocoo())
            pd.DataFrame(index=pd.Index(obs_names, name="cell_id")).to_csv(obs_path)
            pd.DataFrame({"gene": list(var_names)}).to_csv(genes_path, index=False)

            cmd = [
                rscript,
                str(R_METHOD_SCRIPT),
                "--matrix",
                str(matrix_path),
                "--obs",
                str(obs_path),
                "--genes",
                str(genes_path),
                "--output_matrix",
                str(output_matrix_path),
                "--metrics",
                str(output_metrics_path),
                "--random_state",
                str(int(random_state)),
            ]
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"SoupX failed with exit code {completed.returncode}: "
                    f"{completed.stdout}{completed.stderr}"
                )

            corrected = spio.mmread(output_matrix_path)
            if hasattr(corrected, "transpose") and hasattr(corrected, "tocsr"):
                corrected_csr = corrected.transpose().tocsr()
            else:
                corrected_csr = sp.csr_matrix(corrected).transpose().tocsr()
            metrics_frame = pd.read_csv(output_metrics_path)
            metrics = metrics_frame.iloc[0].to_dict() if not metrics_frame.empty else {}
            return corrected_csr, metrics

    def execute(self, input: AmbientCorrectionInput, compute) -> AmbientCorrectionOutput:
        adata = input.adata
        cl = input.counts_layer
        corr = input.corrected_layer
        requested = str(input.method).strip().lower()

        if not input.enabled or requested == "off":
            active = cl if cl in adata.layers else "X"
            adata.uns["zerna_active_counts_layer"] = active
            na_msg = (
                "Ambient correction was not applied (step disabled or method is off). "
                "No ambient RNA removal was performed."
            )
            adata.uns["zerna_ambient_correction"] = _ambient_uns_block(
                requested_method=requested,
                applied_method="off",
                status="not_applied",
                message=na_msg,
                source_layer=cl if cl in adata.layers else None,
                output_layer=None,
                active_counts_layer=active,
                counts_materialized_from_x=False,
            )
            return AmbientCorrectionOutput(
                adata=adata,
                metrics=AmbientCorrectionMetrics(
                    enabled=False,
                    requested_method=requested,
                    applied_method="off",
                    status="not_applied",
                    message=na_msg,
                    source_layer=cl if cl in adata.layers else None,
                    output_layer=None,
                    counts_layer=cl,
                    corrected_layer=None,
                    counts_materialized_from_x=False,
                ),
            )

        if requested == "identity":
            counts_materialized = self._ensure_counts_layer(adata, cl)
            adata.layers[corr] = adata.layers[cl].copy()
            adata.uns["zerna_active_counts_layer"] = corr
            msg = (
                f"Identity mode: {corr} is a copy of raw counts only. "
                "This is a pipeline scaffold — no SoupX or other ambient removal was run."
            )
            if counts_materialized:
                msg += (
                    f" Raw counts layer '{cl}' was materialized from the pre-normalization X "
                    "matrix because it was missing."
                )
            adata.uns["zerna_ambient_correction"] = _ambient_uns_block(
                requested_method=requested,
                applied_method="identity",
                status="identity_scaffold_only",
                message=msg,
                source_layer=cl,
                output_layer=corr,
                active_counts_layer=corr,
                counts_materialized_from_x=counts_materialized,
            )
            return AmbientCorrectionOutput(
                adata=adata,
                metrics=AmbientCorrectionMetrics(
                    enabled=True,
                    requested_method=requested,
                    applied_method="identity",
                    status="identity_scaffold_only",
                    message=msg,
                    source_layer=cl,
                    output_layer=corr,
                    counts_layer=cl,
                    corrected_layer=corr,
                    counts_materialized_from_x=counts_materialized,
                ),
            )

        if requested == "soupx":
            counts_materialized = self._ensure_counts_layer(adata, cl)
            counts_before = _matrix_total_counts(adata.layers[cl])
            corrected_matrix, soupx_metrics = self._run_soupx(
                adata.layers[cl],
                obs_names=list(map(str, adata.obs_names)),
                var_names=list(map(str, adata.var_names)),
                random_state=int(input.random_state),
            )
            if corrected_matrix.shape != adata.layers[cl].shape:
                raise RuntimeError(
                    "SoupX returned a corrected matrix with shape "
                    f"{corrected_matrix.shape}, expected {adata.layers[cl].shape}."
                )
            adata.layers[corr] = corrected_matrix
            adata.uns["zerna_active_counts_layer"] = corr

            counts_after = _matrix_total_counts(corrected_matrix)
            counts_removed = max(0, counts_before - counts_after)
            rho = _coerce_optional_float(soupx_metrics.get("estimated_contamination_fraction"))
            soup_profile_source = str(
                soupx_metrics.get("soup_profile_source") or "filtered_counts_only"
            )
            clustering_source = str(soupx_metrics.get("clustering_source") or "seurat_graph")
            cluster_count = _coerce_optional_int(soupx_metrics.get("cluster_count"))
            msg = (
                "SoupX ambient correction was applied and wrote corrected counts to "
                f"layers['{corr}']. This worker used the filtered counts matrix as both toc and "
                "tod because a raw empty-droplet matrix is not available at this pipeline stage."
            )
            if rho is not None:
                msg += f" Estimated global contamination fraction: {rho:.4f}."
            if counts_materialized:
                msg += (
                    f" Raw counts layer '{cl}' was materialized from the pre-normalization X "
                    "matrix because it was missing."
                )
            adata.uns["zerna_ambient_correction"] = _ambient_uns_block(
                requested_method=requested,
                applied_method="soupx",
                status="soupx_applied_filtered_counts_only",
                message=msg,
                source_layer=cl,
                output_layer=corr,
                active_counts_layer=corr,
                counts_materialized_from_x=counts_materialized,
                estimated_contamination_fraction=rho,
                soup_profile_source=soup_profile_source,
                raw_droplet_matrix_available=False,
                clustering_source=clustering_source,
                cluster_count=cluster_count,
                n_counts_before=counts_before,
                n_counts_after=counts_after,
                counts_removed=counts_removed,
            )
            return AmbientCorrectionOutput(
                adata=adata,
                metrics=AmbientCorrectionMetrics(
                    enabled=True,
                    requested_method=requested,
                    applied_method="soupx",
                    status="soupx_applied_filtered_counts_only",
                    message=msg,
                    source_layer=cl,
                    output_layer=corr,
                    counts_layer=cl,
                    corrected_layer=corr,
                    counts_materialized_from_x=counts_materialized,
                    estimated_contamination_fraction=rho,
                    soup_profile_source=soup_profile_source,
                    raw_droplet_matrix_available=False,
                    clustering_source=clustering_source,
                    cluster_count=cluster_count,
                    n_counts_before=counts_before,
                    n_counts_after=counts_after,
                    counts_removed=counts_removed,
                ),
            )

        raise ValueError(f"Unknown ambient correction method: {input.method!r}")
