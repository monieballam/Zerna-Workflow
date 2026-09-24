#!/usr/bin/env python3
"""Run a deep local pipeline validation sweep on the largest bundled dataset.

This script:
1. chooses the largest locally bundled *raw* dataset suitable for end-to-end runs,
2. enriches it with validation metadata columns,
3. executes multiple full pipeline runs through the production-like `_run_step` path,
4. writes per-run artifacts and a summary report to the Desktop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc

from apps.api.services.pipeline_catalog import STANDARD_METHODS
from methods.annotation.uns_h5ad_serialization import sanitize_explorer_uns_for_h5ad
from workflows.run_execution.activities import _prepare_executable_steps, _run_step

DATA_DIR = REPO_ROOT / "data"
DEFAULT_DESKTOP_ROOT = Path.home() / "Desktop"
DEFAULT_INPUT_CANDIDATES = (DATA_DIR / "pbmc3k_raw.h5ad",)
PROCESSED_REFERENCE_PATH = DATA_DIR / "pbmc3k_processed.h5ad"

SAMPLE_ORDER = (
    "control_r1",
    "control_r2",
    "control_r3",
    "stim_r1",
    "stim_r2",
    "stim_r3",
)
SAMPLE_META = {
    "control_r1": {"condition": "control", "patient_id": "patient_1", "batch_id": "batch_a"},
    "control_r2": {"condition": "control", "patient_id": "patient_2", "batch_id": "batch_b"},
    "control_r3": {"condition": "control", "patient_id": "patient_3", "batch_id": "batch_c"},
    "stim_r1": {"condition": "stim", "patient_id": "patient_1", "batch_id": "batch_a"},
    "stim_r2": {"condition": "stim", "patient_id": "patient_2", "batch_id": "batch_b"},
    "stim_r3": {"condition": "stim", "patient_id": "patient_3", "batch_id": "batch_c"},
}
VALIDATION_FIXES = (
    "SoupX support was added for ambient correction, using filtered counts at this pipeline stage and writing corrected counts to the requested output layer.",
    "HVG selection now falls back from seurat_v3 to seurat when Scanpy's loess fit fails numerically on small or aggressively filtered matrices.",
    "KEGG wsum validation now falls back to Zerna weighted sparse scoring when the current decoupler runtime does not expose decoupler.mt.wsum.",
    "Validation snapshots are sanitized before H5AD writeout so mixed-type obs/var/uns content produced by downstream methods can still be archived.",
    "The SOLO validation branch runs in flag_only mode so the SOLO backend is exercised without collapsing the tiny bundled PBMC dataset.",
    "Synthetic validation_stratum labels are split within each sample to guarantee valid replicate coverage for pseudobulk sample-level contrasts.",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Categorical):
        return value.astype(str).tolist()
    if pd.isna(value):
        return None
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")


def _sanitize_dataframe_for_h5ad(frame: pd.DataFrame) -> None:
    for column in frame.columns:
        series = frame[column]
        is_categorical = isinstance(series.dtype, pd.CategoricalDtype)
        if pd.api.types.is_object_dtype(series) or is_categorical:
            converted = series.astype(object).map(
                lambda value: pd.NA if pd.isna(value) else str(value)
            )
            if is_categorical:
                frame[column] = converted.astype("string").astype("category")
            else:
                frame[column] = converted.astype("string")


def _write_sanitized_h5ad(adata: ad.AnnData, path: Path) -> None:
    snapshot = adata.copy()
    sanitize_explorer_uns_for_h5ad(snapshot)
    _sanitize_dataframe_for_h5ad(snapshot.obs)
    _sanitize_dataframe_for_h5ad(snapshot.var)
    with ad.settings.override(allow_write_nullable_strings=True):
        snapshot.write_h5ad(path, compression="gzip")


def _largest_raw_dataset(candidates: Iterable[Path]) -> Path:
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise FileNotFoundError(
            f"No candidate raw datasets were found. Checked: {[str(path) for path in candidates]}"
        )
    return max(existing, key=lambda path: path.stat().st_size)


def _load_base_dataset() -> tuple[Path, ad.AnnData, ad.AnnData]:
    raw_path = _largest_raw_dataset(DEFAULT_INPUT_CANDIDATES)
    if not PROCESSED_REFERENCE_PATH.is_file():
        raise FileNotFoundError(
            f"Processed reference dataset not found: {PROCESSED_REFERENCE_PATH}"
        )
    raw = ad.read_h5ad(raw_path)
    processed = ad.read_h5ad(PROCESSED_REFERENCE_PATH)
    return raw_path, raw, processed


def _enrich_validation_columns(
    raw: ad.AnnData, processed: ad.AnnData
) -> tuple[ad.AnnData, dict[str, Any]]:
    adata = raw.copy()
    ref_labels = (
        processed.obs["louvain"].astype(str).reindex(adata.obs_names).fillna("NotInProcessed")
    )
    adata.obs["processed_louvain_ref"] = pd.Categorical(ref_labels)

    sample_assignments = pd.Series(index=adata.obs_names, dtype="object")

    for label, names in adata.obs.groupby("processed_louvain_ref", observed=True).groups.items():
        ordered_names = sorted(str(name) for name in names)
        for idx, cell_id in enumerate(ordered_names):
            sample_name = SAMPLE_ORDER[idx % len(SAMPLE_ORDER)]
            sample_assignments.loc[cell_id] = sample_name

    adata.obs["sample_id"] = sample_assignments.astype("category")
    adata.obs["orig.ident"] = adata.obs["sample_id"].astype(str).astype("category")
    adata.obs["condition"] = (
        adata.obs["sample_id"]
        .astype(str)
        .map(lambda s: SAMPLE_META[s]["condition"])
        .astype("category")
    )
    adata.obs["patient_id"] = (
        adata.obs["sample_id"]
        .astype(str)
        .map(lambda s: SAMPLE_META[s]["patient_id"])
        .astype("category")
    )
    adata.obs["batch_id"] = (
        adata.obs["sample_id"]
        .astype(str)
        .map(lambda s: SAMPLE_META[s]["batch_id"])
        .astype("category")
    )
    adata.obs["library_id"] = (
        adata.obs["sample_id"].astype(str).map(lambda s: f"library_{s}").astype("category")
    )
    sample_positions = adata.obs.groupby("sample_id", observed=True).cumcount()
    adata.obs["validation_stratum"] = pd.Categorical(
        np.where(sample_positions.to_numpy() % 2 == 0, "stratum_a", "stratum_b")
    )
    adata.obs["validation_column_bundle"] = pd.Categorical(
        adata.obs["batch_id"].astype(str) + "|" + adata.obs["condition"].astype(str)
    )

    label_counts = adata.obs["processed_louvain_ref"].astype(str).value_counts()
    non_synthetic_focus = label_counts.drop(labels=["NotInProcessed"], errors="ignore")
    focus_level = str(
        non_synthetic_focus.index[0] if not non_synthetic_focus.empty else label_counts.index[0]
    )
    sample_stratum_counts = pd.crosstab(
        adata.obs["sample_id"].astype(str),
        adata.obs["validation_stratum"].astype(str),
    )
    condition_stratum_counts = pd.crosstab(
        adata.obs["condition"].astype(str),
        adata.obs["validation_stratum"].astype(str),
    )

    metadata = {
        "n_obs": int(adata.n_obs),
        "n_vars": int(adata.n_vars),
        "obs_columns_added": [
            "processed_louvain_ref",
            "sample_id",
            "orig.ident",
            "condition",
            "patient_id",
            "batch_id",
            "library_id",
            "validation_stratum",
            "validation_column_bundle",
        ],
        "sample_counts": adata.obs["sample_id"].astype(str).value_counts().to_dict(),
        "condition_counts": adata.obs["condition"].astype(str).value_counts().to_dict(),
        "validation_stratum_counts": (
            adata.obs["validation_stratum"].astype(str).value_counts().sort_index().to_dict()
        ),
        "condition_stratum_counts": condition_stratum_counts.to_dict(),
        "sample_stratum_counts": sample_stratum_counts.to_dict(),
        "reference_counts": label_counts.to_dict(),
        "de_focus_level_selected": focus_level,
        "overlap_with_processed": int(adata.obs_names.isin(processed.obs_names).sum()),
    }
    return adata, metadata


def _base_parameters() -> dict[str, Any]:
    return {
        "min_genes": 50,
        "max_genes": 8000,
        "min_cells": 3,
        "max_mito_pct": 20.0,
        "expected_doublet_rate": 0.06,
        "doublet_threshold": 0.25,
        "doublet_sample_key": "sample_id",
        "ambient_correction": True,
        "ambient_method": "soupx",
        "ambient_counts_layer": "counts",
        "ambient_corrected_layer": "corrected_counts",
        "target_sum": 1e4,
        "persist_counts_layer": True,
        "scale": False,
        "max_value": 10.0,
        "n_top_genes": 2000,
        "hvg_flavor": "seurat_v3",
        "hvg_batch_key": "library_id",
        "n_pcs": 25,
        "resolution": 0.45,
        "n_neighbors": 15,
        "batch_correction": True,
        "integration_mode": "harmony",
        "batch_key": "batch_id",
        "max_iter_harmony": 10,
        "max_epochs": 12,
        "n_latent": 20,
        "n_layers": 2,
        "clustering_method": "leiden",
        "cluster_key": "leiden",
        "embedding_method": "umap",
        "umap_min_dist": 0.35,
        "tsne_perplexity": 30.0,
        "annotation_method": "celltypist",
        "annotation_cluster_key": "leiden",
        "annotation_benchmark_reference_key": "processed_louvain_ref",
        "annotation_species": "human",
        "annotation_model": "Immune_All_Low.pkl",
        "annotation_tissue_context": "blood",
        "annotation_marker_database": "zerna_default",
        "annotation_min_marker_overlap": 2,
        "de_mode": "marker_ranking",
        "de_groupby_key": "leiden",
        "de_method": "wilcoxon",
        "de_n_genes": 50,
        "de_sample_key": "sample_id",
        "de_condition_key": "condition",
        "de_reference_level": "control",
        "de_compare_level": "stim",
        "de_min_cells_per_sample": 10,
        "de_min_samples_per_group": 2,
        "de_logfc_threshold": 0.0,
        "pathway_scoring": True,
        "pathway_database": "PROGENy",
        "pathway_method": "ulm",
        "pathway_min_n": 5,
        "pathway_progeny_top": 500,
        "ligand_receptor": True,
        "lr_resource_name": "consensus",
        "lr_expr_prop": 0.1,
        "lr_min_cells": 10,
        "lr_n_perms": 10,
        "lr_communication_grouping": "auto",
        "random_seed": 42,
        "solo_batch_size": 256,
        "solo_gene_likelihood": "zinb",
        "solo_max_epochs": 6,
    }


@dataclass(frozen=True)
class RunSpec:
    name: str
    description: str
    overrides: dict[str, Any]


def _build_run_specs(focus_level: str) -> list[RunSpec]:
    return [
        RunSpec(
            name="agentv3_scvi_soupx",
            description=(
                "Full baseline using SoupX, Scrublet, scVI integration, Leiden/UMAP, "
                "AnnotationAgentV3, marker-ranking DE, PROGENy pathway scoring, and LR auto grouping."
            ),
            overrides={
                "doublet_method": "scrublet",
                "integration_mode": "scvi",
                "batch_key": "batch_id",
                "clustering_method": "leiden",
                "cluster_key": "leiden",
                "annotation_cluster_key": "leiden",
                "embedding_method": "umap",
                "annotation_method": "celltypist",
                "de_mode": "marker_ranking",
                "de_groupby_key": "leiden",
                "pathway_database": "PROGENy",
                "pathway_method": "ulm",
                "lr_communication_grouping": "auto",
            },
        ),
        RunSpec(
            name="conservative_harmony_identity_condition_de",
            description=(
                "Legacy-leaning branch coverage using scDblFinder, identity ambient correction, "
                "Harmony, Louvain/t-SNE, conservative annotation, focused within-celltype pseudobulk DE, "
                "Hallmark activity scoring, and LR cluster grouping."
            ),
            overrides={
                "doublet_method": "scDblFinder",
                "ambient_method": "identity",
                "hvg_flavor": "seurat",
                "integration_mode": "harmony",
                "batch_key": "orig.ident",
                "clustering_method": "louvain",
                "cluster_key": "louvain",
                "annotation_cluster_key": "louvain",
                "embedding_method": "tsne",
                "annotation_method": "conservative",
                "de_mode": "condition_de_within_celltype",
                "de_groupby_key": "processed_louvain_ref",
                "de_focus_level": focus_level,
                "pathway_database": "Hallmark",
                "pathway_method": "aucell",
                "lr_communication_grouping": "cluster",
            },
        ),
        RunSpec(
            name="hybrid_solo_pseudobulk",
            description=(
                "SOLO-backed full run with hybrid annotation, stratified pseudobulk sample-level DE, "
                "Reactome MLM pathway activity, and LR grouping on cci_minor. This validation keeps "
                "SOLO in flag-only mode so the backend is exercised without over-pruning the tiny test dataset."
            ),
            overrides={
                "doublet_method": "solo",
                "doublet_mode": "flag_only",
                "integration_mode": "harmony",
                "batch_key": "patient_id",
                "annotation_method": "hybrid",
                "de_mode": "pseudobulk_sample_level_contrast",
                "de_groupby_key": "validation_stratum",
                "pathway_database": "Reactome",
                "pathway_method": "mlm",
                "lr_communication_grouping": "cci_minor",
            },
        ),
        RunSpec(
            name="markerpack_doubletdetection_dorothea",
            description=(
                "Python alternative doublet path with marker-pack annotation, DoRothEA scoring, "
                "t-SNE, and LR auto grouping."
            ),
            overrides={
                "doublet_method": "doubletdetection",
                "ambient_method": "identity",
                "integration_mode": "harmony",
                "batch_key": "batch_id",
                "clustering_method": "leiden",
                "cluster_key": "leiden",
                "annotation_cluster_key": "leiden",
                "embedding_method": "tsne",
                "annotation_method": "marker_pack",
                "de_mode": "marker_ranking",
                "de_groupby_key": "processed_louvain_ref",
                "pathway_database": "DoRothEA",
                "pathway_method": "zscore",
                "lr_communication_grouping": "auto",
            },
        ),
        RunSpec(
            name="celltypist_doubletfinder_kegg",
            description=(
                "CellTypist-focused run with DoubletFinder, scVI integration, KEGG pathway scoring, "
                "and LR grouping on cci_fine."
            ),
            overrides={
                "doublet_method": "DoubletFinder",
                "ambient_method": "soupx",
                "integration_mode": "scvi",
                "batch_key": "batch_id",
                "clustering_method": "louvain",
                "cluster_key": "louvain",
                "annotation_cluster_key": "louvain",
                "embedding_method": "umap",
                "annotation_method": "celltypist",
                "de_mode": "marker_ranking",
                "de_groupby_key": "louvain",
                "pathway_database": "KEGG",
                "pathway_method": "wsum",
                "lr_communication_grouping": "cci_fine",
            },
        ),
    ]


def _sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _record_obs_profile(adata: ad.AnnData) -> dict[str, Any]:
    profile: dict[str, Any] = {}
    for column in sorted(adata.obs.columns):
        series = adata.obs[column].astype(str)
        top_counts = series.value_counts().head(10)
        profile[column] = {
            "n_unique": int(series.nunique(dropna=False)),
            "top_values": {str(label): int(count) for label, count in top_counts.items()},
        }
    return profile


def _summarize_run(
    adata: ad.AnnData,
    *,
    spec: RunSpec,
    params: dict[str, Any],
    step_metrics: dict[str, dict[str, Any]],
    steps_executed: list[str],
    status: str,
    error: str | None,
    traceback_text: str | None,
) -> dict[str, Any]:
    pathway_meta = adata.uns.get("pathway_scoring_meta", {}) if status == "passed" else {}
    lr_meta = adata.uns.get("zerna_ligand_receptor", {}) if status == "passed" else {}
    batch_meta = adata.uns.get("zerna_batch_correction", {}) if status == "passed" else {}
    return {
        "name": spec.name,
        "description": spec.description,
        "status": status,
        "error": error,
        "traceback": traceback_text,
        "parameters": params,
        "steps_executed": steps_executed,
        "step_metrics": step_metrics,
        "n_obs_final": int(adata.n_obs),
        "n_vars_final": int(adata.n_vars),
        "final_obs_columns": sorted(str(col) for col in adata.obs.columns),
        "final_uns_keys": sorted(str(key) for key in adata.uns),
        "cluster_columns_present": [
            col for col in ("leiden", "louvain") if col in adata.obs.columns
        ],
        "annotation_columns_present": [
            col
            for col in (
                "annotation_label",
                "annotation_cell_type",
                "celltypist_cell_type",
                "cci_celltype_major",
                "cci_celltype_minor",
                "cci_celltype_fine",
            )
            if col in adata.obs.columns
        ],
        "pathway_summary": {
            "database": pathway_meta.get("pathway_database"),
            "n_pathways": pathway_meta.get("n_pathways"),
            "obsm_key": pathway_meta.get("obsm_key"),
        },
        "lr_summary": {
            "grouping_requested": lr_meta.get("lr_communication_grouping_requested"),
            "grouping_effective": lr_meta.get("lr_communication_grouping_effective"),
            "groupby_column": lr_meta.get("groupby_column"),
            "n_interactions": lr_meta.get("n_interactions"),
        },
        "batch_summary": {
            "requested_method": batch_meta.get("method_requested"),
            "executed_method": batch_meta.get("method_executed"),
            "batch_key": batch_meta.get("batch_key"),
        },
    }


def _run_single_spec(
    base_adata: ad.AnnData,
    *,
    spec: RunSpec,
    root_output_dir: Path,
) -> dict[str, Any]:
    run_dir = root_output_dir / _sanitize_name(spec.name)
    run_dir.mkdir(parents=True, exist_ok=True)

    params = _base_parameters()
    params.update(spec.overrides)
    params["random_seed"] = int(params.get("random_seed", 42))
    params["run_name"] = spec.name

    executable = _prepare_executable_steps(STANDARD_METHODS, params)
    steps_executed = [str(step["step_name"]) for step in executable]
    _write_json(run_dir / "parameters.json", params)
    _write_json(run_dir / "steps.json", executable)

    adata = base_adata.copy()
    step_metrics: dict[str, dict[str, Any]] = {}
    current_step = None
    error_text: str | None = None
    traceback_text: str | None = None
    status = "passed"

    work_dir = Path(tempfile.mkdtemp(prefix=f"zerna_validation_{_sanitize_name(spec.name)}_"))
    original_cwd = Path.cwd()
    sc.settings.cachedir = work_dir / "scanpy_cache"
    sc.settings.datasetdir = work_dir / "scanpy_datasets"

    try:
        os.chdir(work_dir)
        for step in executable:
            current_step = str(step["step_name"])
            adata, metrics = _run_step(
                current_step,
                adata,
                dict(step["parameters"]),
                random_seed=int(params["random_seed"]),
            )
            step_metrics[current_step] = json.loads(json.dumps(metrics, default=_json_default))
            _write_json(
                run_dir / f"{_sanitize_name(current_step)}_metrics.json", step_metrics[current_step]
            )
    except Exception as exc:
        status = "failed"
        error_text = f"{type(exc).__name__}: {exc}"
        traceback_text = traceback.format_exc()
        if current_step is not None:
            step_metrics.setdefault(
                current_step,
                {"error": error_text, "traceback": traceback_text},
            )
    finally:
        os.chdir(original_cwd)

    if status == "passed":
        _write_sanitized_h5ad(adata, run_dir / "final_output.h5ad")
        obs_profile = _record_obs_profile(adata)
        _write_json(run_dir / "final_obs_profile.json", obs_profile)
        (run_dir / "final_uns_keys.txt").write_text(
            "\n".join(sorted(map(str, adata.uns.keys()))) + "\n"
        )
    elif traceback_text is not None:
        (run_dir / "failure_traceback.txt").write_text(traceback_text)

    summary = _summarize_run(
        adata,
        spec=spec,
        params=params,
        step_metrics=step_metrics,
        steps_executed=steps_executed,
        status=status,
        error=error_text,
        traceback_text=traceback_text,
    )
    _write_json(run_dir / "summary.json", summary)
    return summary


def _markdown_report(
    *,
    raw_path: Path,
    processed_path: Path,
    base_metadata: dict[str, Any],
    run_summaries: list[dict[str, Any]],
    output_dir: Path,
) -> str:
    passed = [summary for summary in run_summaries if summary["status"] == "passed"]
    failed = [summary for summary in run_summaries if summary["status"] != "passed"]
    option_coverage = {
        "doublet_method": sorted(
            {str(summary["parameters"].get("doublet_method")) for summary in run_summaries}
        ),
        "ambient_method": sorted(
            {str(summary["parameters"].get("ambient_method")) for summary in run_summaries}
        ),
        "integration_mode": sorted(
            {str(summary["parameters"].get("integration_mode")) for summary in run_summaries}
        ),
        "clustering_method": sorted(
            {str(summary["parameters"].get("clustering_method")) for summary in run_summaries}
        ),
        "embedding_method": sorted(
            {str(summary["parameters"].get("embedding_method")) for summary in run_summaries}
        ),
        "annotation_method": sorted(
            {str(summary["parameters"].get("annotation_method")) for summary in run_summaries}
        ),
        "de_mode": sorted({str(summary["parameters"].get("de_mode")) for summary in run_summaries}),
        "pathway_combo": sorted(
            {
                f"{summary['parameters'].get('pathway_database')}/{summary['parameters'].get('pathway_method')}"
                for summary in run_summaries
            }
        ),
        "lr_grouping": sorted(
            {
                str(summary["parameters"].get("lr_communication_grouping"))
                for summary in run_summaries
            }
        ),
        "column_driven_keys": sorted(
            {
                key
                for summary in run_summaries
                for key in (
                    summary["parameters"].get("doublet_sample_key"),
                    summary["parameters"].get("hvg_batch_key"),
                    summary["parameters"].get("batch_key"),
                    summary["parameters"].get("annotation_cluster_key"),
                    summary["parameters"].get("de_groupby_key"),
                    summary["parameters"].get("de_sample_key"),
                    summary["parameters"].get("de_condition_key"),
                )
                if key
            }
        ),
    }
    lines: list[str] = []
    lines.append("# Zerna Deep Pipeline Validation Report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- Repository: `{REPO_ROOT}`")
    lines.append(f"- Raw dataset used: `{raw_path}`")
    lines.append(f"- Processed reference used: `{processed_path}`")
    lines.append(f"- Output bundle: `{output_dir}`")
    lines.append("")
    lines.append("## Input dataset")
    lines.append("")
    lines.append(f"- Cells x genes: `{base_metadata['n_obs']} x {base_metadata['n_vars']}`")
    lines.append(
        f"- Overlap with processed reference: `{base_metadata['overlap_with_processed']}` cells"
    )
    lines.append("- Validation columns added:")
    for column in base_metadata["obs_columns_added"]:
        lines.append(f"  - `{column}`")
    lines.append(f"- Condition counts: `{base_metadata['condition_counts']}`")
    lines.append(f"- Sample counts: `{base_metadata['sample_counts']}`")
    lines.append(f"- Validation stratum counts: `{base_metadata['validation_stratum_counts']}`")
    lines.append(f"- Condition x stratum counts: `{base_metadata['condition_stratum_counts']}`")
    lines.append(f"- Sample x stratum counts: `{base_metadata['sample_stratum_counts']}`")
    lines.append(
        "- Notes: `processed_louvain_ref` came from the bundled processed PBMC reference; "
        "sample/batch/condition columns were synthesized to exercise column-driven pipeline options "
        "because the raw bundled dataset does not include them."
    )
    lines.append("")
    lines.append("## Option coverage")
    lines.append("")
    lines.append(f"- Doublet methods covered: `{option_coverage['doublet_method']}`")
    lines.append(f"- Ambient methods covered: `{option_coverage['ambient_method']}`")
    lines.append(f"- Integration modes covered: `{option_coverage['integration_mode']}`")
    lines.append(f"- Clustering methods covered: `{option_coverage['clustering_method']}`")
    lines.append(f"- Embedding methods covered: `{option_coverage['embedding_method']}`")
    lines.append(f"- Annotation methods covered: `{option_coverage['annotation_method']}`")
    lines.append(f"- DE modes covered: `{option_coverage['de_mode']}`")
    lines.append(f"- Pathway scoring combinations covered: `{option_coverage['pathway_combo']}`")
    lines.append(f"- LR grouping modes covered: `{option_coverage['lr_grouping']}`")
    lines.append(f"- Column-driven keys exercised: `{option_coverage['column_driven_keys']}`")
    lines.append("")
    lines.append("## Compatibility fixes validated during the sweep")
    lines.append("")
    for note in VALIDATION_FIXES:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Overall result")
    lines.append("")
    lines.append(f"- Passed runs: `{len(passed)}`")
    lines.append(f"- Failed runs: `{len(failed)}`")
    lines.append("")
    lines.append("## Run matrix")
    lines.append("")
    for summary in run_summaries:
        params = summary["parameters"]
        lr_metrics = summary.get("step_metrics", {}).get("ligand_receptor_analysis", {})
        lr_grouping_effective = summary["lr_summary"].get("grouping_effective") or lr_metrics.get(
            "lr_communication_grouping_effective"
        )
        pathway_metrics = summary.get("step_metrics", {}).get("pathway_scoring", {})
        pathway_methods_used = pathway_metrics.get("methods_used")
        lines.append(f"### {summary['name']}")
        lines.append("")
        lines.append(f"- Status: `{summary['status']}`")
        lines.append(
            f"- Description: {next(spec.description for spec in _build_run_specs(base_metadata['de_focus_level_selected']) if spec.name == summary['name'])}"
        )
        lines.append(
            "- Key options: "
            f"`doublet={params.get('doublet_method')}`, "
            f"`ambient={params.get('ambient_method')}`, "
            f"`integration={params.get('integration_mode')}`, "
            f"`cluster={params.get('clustering_method')}`, "
            f"`embed={params.get('embedding_method')}`, "
            f"`annotation={params.get('annotation_method')}`, "
            f"`de_mode={params.get('de_mode')}`, "
            f"`pathway={params.get('pathway_database')}/{params.get('pathway_method')}`, "
            f"`lr_grouping={params.get('lr_communication_grouping')}`"
        )
        lines.append(f"- Run directory: `{output_dir / _sanitize_name(summary['name'])}`")
        lines.append(f"- Steps executed: `{summary['steps_executed']}`")
        if summary["status"] == "passed":
            lines.append(
                f"- Final shape: `{summary['n_obs_final']} x {summary['n_vars_final']}`; "
                f"pathway db `{summary['pathway_summary'].get('database')}`, "
                f"pathway methods `{pathway_methods_used}`, "
                f"LR grouping effective `{lr_grouping_effective}`."
            )
        else:
            lines.append(f"- Failure: `{summary['error']}`")
        lines.append("")
    if failed:
        lines.append("## Failures")
        lines.append("")
        for summary in failed:
            lines.append(f"- `{summary['name']}`: `{summary['error']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the validation bundle. Defaults to a timestamped folder on the Desktop.",
    )
    parser.add_argument(
        "--runs",
        nargs="*",
        default=None,
        help="Optional subset of run names to execute.",
    )
    return parser.parse_args()


def main() -> int:
    os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")
    os.environ.setdefault("ZERNA_SCRUBLET_EXACT_NEIGHBORS", "1")

    args = _parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or (
        DEFAULT_DESKTOP_ROOT / f"zerna_deep_pipeline_validation_{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path, raw, processed = _load_base_dataset()
    enriched, base_metadata = _enrich_validation_columns(raw, processed)

    _write_sanitized_h5ad(enriched, output_dir / "enriched_input.h5ad")
    _write_json(output_dir / "input_metadata.json", base_metadata)

    run_specs = _build_run_specs(base_metadata["de_focus_level_selected"])
    if args.runs:
        requested = set(args.runs)
        run_specs = [spec for spec in run_specs if spec.name in requested]
        missing = requested - {spec.name for spec in run_specs}
        if missing:
            raise SystemExit(f"Unknown run names requested: {sorted(missing)}")
    if not run_specs:
        raise SystemExit("No run specs selected.")

    summaries: list[dict[str, Any]] = []
    for spec in run_specs:
        summaries.append(_run_single_spec(enriched, spec=spec, root_output_dir=output_dir))

    _write_json(output_dir / "run_summaries.json", summaries)
    report = _markdown_report(
        raw_path=raw_path,
        processed_path=PROCESSED_REFERENCE_PATH,
        base_metadata=base_metadata,
        run_summaries=summaries,
        output_dir=output_dir,
    )
    (output_dir / "REPORT.md").write_text(report)

    status_line = {
        "output_dir": str(output_dir),
        "passed": sum(1 for summary in summaries if summary["status"] == "passed"),
        "failed": sum(1 for summary in summaries if summary["status"] != "passed"),
        "runs": [summary["name"] for summary in summaries],
    }
    print(json.dumps(status_line, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
