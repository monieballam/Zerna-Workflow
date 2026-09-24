"""Doublet detection method for single-cell RNA-seq data."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
import scrublet as scr
from zerna_contracts.enums import ComputeBackend, ComputePreference
from pydantic import BaseModel, Field
from scipy import io as spio

from methods.base import MethodDefinition
from methods.data.obs_keys import resolve_batch_key

logger = logging.getLogger(__name__)

# Product surface (dashboard / new templates): scrublet | solo. Others remain for legacy runs.
USER_FACING_DOUBLET_METHODS = frozenset({"scrublet", "solo"})
R_BACKENDS = {"scdblfinder", "doubletfinder", "scds"}
R_BACKEND_PACKAGES = {
    "scdblfinder": ("BiocParallel", "SingleCellExperiment", "scDblFinder"),
    "doubletfinder": ("DoubletFinder", "Seurat"),
    "scds": ("SingleCellExperiment", "scds"),
}
R_METHOD_SCRIPT = Path(__file__).resolve().parents[1] / "programs" / "run_doublet_detection.R"


class DoubletDetectionInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    method: str = Field(
        default="scrublet",
        description=(
            "Primary methods: scrublet, solo. Legacy backends (doubletdetection, scDblFinder, "
            "DoubletFinder, scds) are accepted for older templates and programmatic runs."
        ),
    )
    expected_doublet_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    filter_doublets: bool = True
    doublet_mode: str | None = Field(
        default=None,
        description="flag_only | remove_doublets. When set, overrides filter_doublets.",
    )
    random_state: int = 0
    batch_key: str | None = None
    sample_key: str | None = Field(
        default=None,
        description="Optional obs column for per-sample doublet calls (defaults to batch_key).",
    )
    solo_batch_size: int = Field(default=512, ge=16)
    solo_gene_likelihood: str = Field(default="zinb")
    solo_max_epochs: int = Field(default=100, ge=1)
    doubletdetection_voter_thresh: float = Field(default=0.5, ge=0.0, le=1.0)
    doubletdetection_p_thresh: float = Field(default=1e-16, ge=0.0)


class DoubletDetectionMetrics(BaseModel):
    n_cells: int
    n_cells_before: int
    n_cells_after: int
    n_predicted_doublets: int
    doublet_rate: float
    mean_doublet_score: float
    method_used: str
    method_requested: str
    method_executed: str
    batch_key_used: str | None = None
    doublet_mode: str
    expected_doublet_rate: float
    threshold: float
    execution_layout: str  # whole_object | grouped | pooled
    cells_removed: int = 0
    warnings: list[str] = Field(default_factory=list)
    per_sample: dict[str, dict[str, float | int | bool]] = Field(default_factory=dict)


class DoubletDetectionOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: DoubletDetectionMetrics


class DoubletDetectionMethod(MethodDefinition):
    name = "doublet_detection"
    version = "1.0.0"
    # Scrublet is sklearn/CPU-heavy; reserving Metal (GPU_PREFERRED) still ran the worker
    # through the GPU slot on Apple Silicon and correlated with abrupt process death during
    # "Calculating doublet scores..." on local workers. SOLO already avoids MPS unless
    # ZERNA_SOLO_ENABLE_MPS is set. CUDA SOLO GPU acceleration is a rare need vs stability.
    compute_preference = ComputePreference.CPU_ONLY
    supported_backends = {
        ComputeBackend.CPU,
        ComputeBackend.CUDA,
        ComputeBackend.ROCM,
        ComputeBackend.METAL,
    }

    def input_schema(self):
        return DoubletDetectionInput

    def output_schema(self):
        return DoubletDetectionOutput

    @staticmethod
    def _coerce_scrublet_counts(matrix):
        """Scrublet uses CSC internally; normalize dtype/layout to reduce native crashes."""
        if sp.issparse(matrix):
            x = matrix.tocsc()
            x.eliminate_zeros()
            x.sum_duplicates()
            x.sort_indices()
            if x.dtype != np.float64:
                x = x.astype(np.float64, copy=False)
            return x
        return np.asarray(matrix, dtype=np.float64, order="C")

    @staticmethod
    def _run_scrublet(
        matrix,
        *,
        expected_doublet_rate: float,
        threshold: float,
        random_state: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        matrix = DoubletDetectionMethod._coerce_scrublet_counts(matrix)
        scrub = scr.Scrublet(
            matrix,
            expected_doublet_rate=expected_doublet_rate,
            random_state=random_state,
        )
        n_obs = int(matrix.shape[0])
        n_prin_comps = max(2, min(30, n_obs - 1)) if n_obs > 2 else 2
        # Annoy (approx neighbors) has produced SIGBUS / signal-10 hard exits on Apple
        # Silicon + recent Python after PCA; sklearn NearestNeighbors is slower but stable.
        env_exact = os.getenv("ZERNA_SCRUBLET_EXACT_NEIGHBORS", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        env_approx = os.getenv("ZERNA_SCRUBLET_APPROX_NEIGHBORS", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        use_approx = True
        if sys.platform == "darwin":
            use_approx = False
        if env_exact:
            use_approx = False
        if env_approx:
            use_approx = True
        svd_solver = "randomized" if sys.platform == "darwin" else "arpack"
        doublet_scores, _ = scrub.scrub_doublets(
            use_approx_neighbors=use_approx,
            n_prin_comps=n_prin_comps,
            svd_solver=svd_solver,
            verbose=False,
        )
        # Always re-apply the configured threshold so run parameters control the
        # singlet/doublet decision instead of silently deferring to Scrublet's
        # internal auto-thresholding.
        predicted_doublets = scrub.call_doublets(threshold=threshold, verbose=False)
        return np.asarray(doublet_scores, dtype=np.float32), np.asarray(
            predicted_doublets, dtype=bool
        )

    @staticmethod
    def _run_doubletdetection(
        matrix,
        *,
        p_thresh: float,
        voter_thresh: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        import doubletdetection

        clf = doubletdetection.BoostClassifier(
            n_iters=10,
            clustering_algorithm="leiden",
            standard_scaling=True,
            pseudocount=0.1,
            n_jobs=-1,
        )
        predicted_doublets = clf.fit(matrix).predict(
            p_thresh=p_thresh,
            voter_thresh=voter_thresh,
        )
        doublet_scores = clf.doublet_score()
        return np.asarray(doublet_scores, dtype=np.float32), np.asarray(
            predicted_doublets,
            dtype=bool,
        )

    @staticmethod
    def _resolve_solo_accelerator(compute) -> tuple[str, int, int]:
        backend = getattr(compute, "selected_backend", None)
        if backend in (ComputeBackend.CUDA, ComputeBackend.ROCM):
            return "gpu", 1, min(8, os.cpu_count() or 1)
        if backend == ComputeBackend.METAL:
            # SOLO on Apple MPS has been much less predictable than scVI in
            # the local worker: long stalls are common even on small datasets.
            # Prefer CPU on Metal hosts unless explicitly overridden.
            if os.getenv("ZERNA_SOLO_ENABLE_MPS", "").strip().lower() in {"1", "true", "yes"}:
                return "mps", 1, 0
            return "cpu", 1, min(4, os.cpu_count() or 1)
        return "cpu", 1, min(4, os.cpu_count() or 1)

    def _run_solo(
        self,
        adata: ad.AnnData,
        *,
        batch_key: str | None,
        threshold: float,
        gene_likelihood: str,
        batch_size: int,
        max_epochs: int,
        compute,
    ) -> tuple[np.ndarray, np.ndarray]:
        import scvi
        import torch

        adata_solo = adata.copy()
        if "counts" in adata_solo.layers:
            counts = adata_solo.layers["counts"]
            adata_solo.X = counts.copy() if hasattr(counts, "copy") else counts
        if sp.issparse(adata_solo.X) and not sp.isspmatrix_csr(adata_solo.X):
            adata_solo.X = sp.csr_matrix(adata_solo.X)

        accelerator, devices, num_workers = self._resolve_solo_accelerator(compute)
        if accelerator == "cpu":
            n_threads = os.cpu_count() or 4
            torch.set_num_threads(n_threads)
            scvi.settings.num_threads = n_threads

        scvi.model.SCVI.setup_anndata(adata_solo, batch_key=batch_key)
        scvi.settings.batch_size = batch_size

        vae = scvi.model.SCVI(adata_solo, gene_likelihood=gene_likelihood)
        vae.train(
            max_epochs=max_epochs,
            early_stopping=True,
            accelerator=accelerator,
            devices=devices,
            batch_size=batch_size,
            enable_progress_bar=False,
            datasplitter_kwargs={
                "num_workers": num_workers,
                "persistent_workers": num_workers > 0,
            },
        )

        solo = scvi.external.SOLO.from_scvi_model(vae)
        solo.train(
            max_epochs=max_epochs,
            early_stopping=True,
            accelerator=accelerator,
            devices=devices,
            batch_size=batch_size,
            enable_progress_bar=False,
            datasplitter_kwargs={
                "num_workers": num_workers,
                "persistent_workers": num_workers > 0,
            },
        )

        predictions = solo.predict()
        if hasattr(predictions, "to_dict"):
            scores = np.asarray(predictions["doublet"], dtype=np.float32)
        else:
            scores = np.asarray(predictions, dtype=np.float32)
        predicted = scores > float(threshold)
        return scores, predicted

    @staticmethod
    def _unsupported_backend(method: str) -> ValueError:
        return ValueError(
            f"Doublet detection method '{method}' requires an R runtime integration that is not "
            "available in this worker yet."
        )

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
            raise DoubletDetectionMethod._unsupported_backend(method)

        missing = tuple(
            package.strip() for package in completed.stdout.split(",") if package.strip()
        )
        return missing

    @staticmethod
    def _run_r_backend(
        matrix,
        *,
        method: str,
        threshold: float,
        expected_doublet_rate: float,
        random_state: int,
        obs_names: list[str],
        var_names: list[str],
    ) -> tuple[np.ndarray, np.ndarray]:
        rscript = os.getenv("ZERNA_RSCRIPT_PATH") or shutil.which("Rscript")
        if not rscript:
            raise DoubletDetectionMethod._unsupported_backend(method)
        missing_packages = DoubletDetectionMethod._missing_r_packages(method, rscript)
        if missing_packages:
            raise ValueError(
                f"Doublet detection method '{method}' requires an R runtime integration with "
                f"packages that are not available in this worker yet: {', '.join(missing_packages)}."
            )
        if not R_METHOD_SCRIPT.is_file():
            raise FileNotFoundError(f"R helper script not found: {R_METHOD_SCRIPT}")

        matrix_csr = matrix.tocsr() if hasattr(matrix, "tocsr") else sp.csr_matrix(matrix)
        with tempfile.TemporaryDirectory(prefix="zerna_doublets_") as temp_dir:
            temp_path = Path(temp_dir)
            matrix_path = temp_path / "counts.mtx"
            obs_path = temp_path / "obs.csv"
            genes_path = temp_path / "genes.csv"
            output_path = temp_path / "result.csv"

            spio.mmwrite(matrix_path, matrix_csr.transpose().tocoo())
            pd.DataFrame(index=pd.Index(obs_names, name="cell_id")).to_csv(obs_path)
            pd.DataFrame({"gene": list(var_names)}).to_csv(genes_path, index=False)

            cmd = [
                rscript,
                str(R_METHOD_SCRIPT),
                "--method",
                method,
                "--matrix",
                str(matrix_path),
                "--obs",
                str(obs_path),
                "--genes",
                str(genes_path),
                "--output",
                str(output_path),
                "--threshold",
                str(float(threshold)),
                "--expected_doublet_rate",
                str(float(expected_doublet_rate)),
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
                    f"{method} failed with exit code {completed.returncode}: "
                    f"{completed.stdout}{completed.stderr}"
                )

            result = pd.read_csv(output_path)
            scores = result["doublet_score"].to_numpy(dtype=np.float32)
            predicted = (
                result["predicted_doublet"]
                .astype(str)
                .str.strip()
                .str.lower()
                .isin({"true", "1", "t", "yes"})
                .to_numpy()
            )
            return scores, predicted

    def execute(self, input: DoubletDetectionInput, compute) -> DoubletDetectionOutput:
        adata = input.adata
        n_cells_before = adata.n_obs
        method_requested = str(input.method or "scrublet").strip()
        normalized_method = method_requested.lower()

        known_methods = USER_FACING_DOUBLET_METHODS | {"doubletdetection"} | R_BACKENDS
        if normalized_method not in known_methods:
            raise ValueError(
                f"Unknown doublet detection method '{method_requested}'. "
                "Supported: scrublet, solo, doubletdetection, scDblFinder, DoubletFinder, scds."
            )

        group_key = resolve_batch_key(adata, input.sample_key, strict=False) or resolve_batch_key(
            adata, input.batch_key, strict=False
        )

        mode = (input.doublet_mode or "").strip().lower()
        if mode == "flag_only":
            do_filter = False
        elif mode == "remove_doublets":
            do_filter = True
        else:
            do_filter = bool(input.filter_doublets)
        mode_label = "flag_only" if not do_filter else "remove_doublets"

        doublet_scores = np.zeros(n_cells_before, dtype=np.float32)
        predicted_doublets = np.zeros(n_cells_before, dtype=bool)
        per_sample: dict[str, dict[str, float | int | bool]] = {}
        warnings: list[str] = []
        execution_layout = "pooled"

        if normalized_method == "solo":
            execution_layout = "whole_object"
            if not group_key:
                warnings.append(
                    "SOLO ran without a resolved batch/sample column; scVI setup_anndata used no batch key."
                )
            doublet_scores, predicted_doublets = self._run_solo(
                adata,
                batch_key=group_key,
                threshold=input.threshold,
                gene_likelihood=input.solo_gene_likelihood,
                batch_size=input.solo_batch_size,
                max_epochs=input.solo_max_epochs,
                compute=compute,
            )
            if group_key:
                bv = (
                    adata.obs[group_key]
                    .where(adata.obs[group_key].notna(), "__missing__")
                    .astype(str)
                )
                for sample, idx in bv.groupby(bv, sort=False).indices.items():
                    m = np.asarray(idx, dtype=int)
                    pred = predicted_doublets[m]
                    per_sample[str(sample)] = {
                        "n_cells": int(m.size),
                        "n_predicted_doublets": int(pred.sum()),
                        "doublet_fraction": float(pred.mean()) if m.size else 0.0,
                    }
            else:
                per_sample["_all"] = {
                    "n_cells": n_cells_before,
                    "n_predicted_doublets": int(predicted_doublets.sum()),
                    "doublet_fraction": float(predicted_doublets.mean()) if n_cells_before else 0.0,
                }
        elif group_key and normalized_method in {"scrublet", "doubletdetection", *R_BACKENDS}:
            execution_layout = "grouped"
            batch_values = adata.obs[group_key]
            normalized_batches = batch_values.where(batch_values.notna(), "__missing__").astype(str)
            groups_ran = 0
            skipped_groups: list[str] = []
            for sample, batch_index in normalized_batches.groupby(
                normalized_batches, sort=False
            ).indices.items():
                mask = np.asarray(batch_index, dtype=int)
                sn = str(sample)
                if mask.size < 50:
                    skipped_groups.append(sn)
                    per_sample[sn] = {
                        "n_cells": int(mask.size),
                        "n_predicted_doublets": 0,
                        "doublet_fraction": 0.0,
                        "skipped_low_n": True,
                    }
                    continue
                groups_ran += 1
                X_batch = adata.X[mask]
                X_batch = X_batch.tocsr() if hasattr(X_batch, "tocsr") else X_batch
                if normalized_method == "scrublet":
                    batch_scores, batch_doublets = self._run_scrublet(
                        X_batch,
                        expected_doublet_rate=input.expected_doublet_rate,
                        threshold=input.threshold,
                        random_state=input.random_state,
                    )
                elif normalized_method == "doubletdetection":
                    batch_scores, batch_doublets = self._run_doubletdetection(
                        X_batch,
                        p_thresh=input.doubletdetection_p_thresh,
                        voter_thresh=input.doubletdetection_voter_thresh,
                    )
                else:
                    batch_scores, batch_doublets = self._run_r_backend(
                        X_batch,
                        method=method_requested,
                        threshold=input.threshold,
                        expected_doublet_rate=input.expected_doublet_rate,
                        random_state=input.random_state,
                        obs_names=list(adata.obs_names[mask]),
                        var_names=list(adata.var_names),
                    )
                doublet_scores[mask] = batch_scores
                predicted_doublets[mask] = batch_doublets
                per_sample[sn] = {
                    "n_cells": int(mask.size),
                    "n_predicted_doublets": int(batch_doublets.sum()),
                    "doublet_fraction": float(batch_doublets.mean()),
                }
            if skipped_groups:
                preview = ", ".join(skipped_groups[:12])
                if len(skipped_groups) > 12:
                    preview += ", …"
                warnings.append(
                    f"Skipped {len(skipped_groups)} group(s) with fewer than 50 cells "
                    f"(per-sample path): {preview}"
                )
            if groups_ran == 0:
                warnings.append(
                    "Per-sample doublet detection did not run on any group (all groups had fewer than 50 cells); "
                    "doublet_score and predicted_doublet were left at zero."
                )
        else:
            X = adata.X.tocsr() if hasattr(adata.X, "tocsr") else adata.X
            if normalized_method == "scrublet":
                if not group_key:
                    msg = (
                        "Scrublet ran on pooled cells (no valid doublet_sample_key or batch_key); "
                        "per-sample detection was not used."
                    )
                    warnings.append(msg)
                    logger.info("Zerna doublet_detection: %s", msg)
                doublet_scores, predicted_doublets = self._run_scrublet(
                    X,
                    expected_doublet_rate=input.expected_doublet_rate,
                    threshold=input.threshold,
                    random_state=input.random_state,
                )
            elif normalized_method == "doubletdetection":
                doublet_scores, predicted_doublets = self._run_doubletdetection(
                    X,
                    p_thresh=input.doubletdetection_p_thresh,
                    voter_thresh=input.doubletdetection_voter_thresh,
                )
            elif normalized_method in R_BACKENDS:
                doublet_scores, predicted_doublets = self._run_r_backend(
                    X,
                    method=method_requested,
                    threshold=input.threshold,
                    expected_doublet_rate=input.expected_doublet_rate,
                    random_state=input.random_state,
                    obs_names=list(adata.obs_names),
                    var_names=list(adata.var_names),
                )
            else:
                raise ValueError(
                    "Unknown doublet detection method "
                    f"'{method_requested}'. Supported backends: scrublet, solo, doubletdetection, "
                    "scDblFinder, DoubletFinder, scds."
                )
            per_sample["_all"] = {
                "n_cells": n_cells_before,
                "n_predicted_doublets": int(predicted_doublets.sum()),
                "doublet_fraction": float(predicted_doublets.mean()) if n_cells_before else 0.0,
            }

        adata.obs["doublet_score"] = doublet_scores
        adata.obs["predicted_doublet"] = predicted_doublets

        n_doublets = int(predicted_doublets.sum())
        if do_filter and n_doublets > 0:
            adata = adata[~adata.obs["predicted_doublet"], :].copy()

        predicted_fraction = float(n_doublets / n_cells_before) if n_cells_before > 0 else 0.0
        cells_removed = int(n_cells_before - adata.n_obs)

        summary = {
            "version": 2,
            "method": method_requested,
            "method_requested": method_requested,
            "method_executed": method_requested,
            "execution_layout": execution_layout,
            "doublet_mode": mode_label,
            "expected_doublet_rate": float(input.expected_doublet_rate),
            "threshold": float(input.threshold),
            "threshold_applicable": True,
            "sample_or_batch_key": group_key,
            "grouping_key": group_key,
            "n_cells_before": n_cells_before,
            "n_predicted_doublets": n_doublets,
            "predicted_doublet_fraction": predicted_fraction,
            "n_cells_after": int(adata.n_obs),
            "cells_removed": cells_removed,
            "per_sample": per_sample,
            "warnings": warnings,
        }
        adata.uns["zerna_doublet_summary"] = summary

        metrics = DoubletDetectionMetrics(
            n_cells=n_cells_before,
            n_cells_before=n_cells_before,
            n_cells_after=adata.n_obs,
            n_predicted_doublets=n_doublets,
            doublet_rate=predicted_fraction,
            mean_doublet_score=float(doublet_scores.mean()) if len(doublet_scores) > 0 else 0.0,
            method_used=method_requested,
            method_requested=method_requested,
            method_executed=method_requested,
            batch_key_used=group_key,
            doublet_mode=mode_label,
            expected_doublet_rate=float(input.expected_doublet_rate),
            threshold=float(input.threshold),
            execution_layout=execution_layout,
            cells_removed=cells_removed,
            warnings=warnings,
            per_sample=per_sample,
        )

        return DoubletDetectionOutput(adata=adata, metrics=metrics)
