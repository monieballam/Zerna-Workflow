"""Differential expression analysis method for single-cell RNA-seq data."""

from __future__ import annotations

import io
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.annotation.cluster_keys import resolve_cluster_key
from methods.annotation.pseudobulk_differential_expression import (
    run_pseudobulk_differential_expression,
)
from methods.base import MethodDefinition

DE_MODE_MARKER = "marker_ranking"
DE_MODE_CONDITION = "condition_de_within_celltype"
DE_MODE_PSEUDOBULK = "pseudobulk_sample_level_contrast"
DE_MODES = frozenset({DE_MODE_MARKER, DE_MODE_CONDITION, DE_MODE_PSEUDOBULK})


def normalize_de_mode(raw: str | None) -> str:
    """Public helper: missing/blank → marker_ranking (backward compatible)."""
    if raw is None or str(raw).strip() == "":
        return DE_MODE_MARKER
    m = str(raw).strip().lower()
    if m in DE_MODES:
        return m
    raise ValueError(
        f"Unsupported de_mode {raw!r}. Expected one of: {', '.join(sorted(DE_MODES))}."
    )


def _scanpy_corr_from_padj(padj: str) -> str:
    p = str(padj or "benjamini-hochberg").strip().lower()
    if p in ("bh", "benjamini-hochberg", "fdr_bh"):
        return "benjamini-hochberg"
    if p in ("bonferroni",):
        return "bonferroni"
    return "benjamini-hochberg"


def write_zerna_de_provenance(
    adata: ad.AnnData,
    record: dict[str, Any],
) -> None:
    adata.uns["zerna_de"] = record


def _ranked_group_names(rgg: dict[str, Any], fallback_clusters: list[str]) -> list[str]:
    names = rgg.get("names")
    dtype_names = getattr(getattr(names, "dtype", None), "names", None)
    if dtype_names:
        return [str(name) for name in dtype_names]
    return fallback_clusters


class DifferentialExpressionInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    cluster_key: str = Field(
        default="leiden",
        description="obs column containing cluster assignments",
    )
    method: str = Field(
        default="wilcoxon",
        description="Statistical test: 'wilcoxon', 't-test', or 't-test_overestim_var'",
    )
    n_genes: int = Field(
        default=0,
        ge=0,
        description="Number of top genes per cluster to return; 0 = all genes",
    )
    min_in_group_fraction: float = Field(default=0.1, ge=0.0, le=1.0)
    min_fold_change: float = Field(default=1.0, ge=0.0)
    max_out_group_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    corr_method: str = Field(
        default="benjamini-hochberg",
        description="Multiple testing correction: 'benjamini-hochberg' or 'bonferroni'",
    )


class DifferentialExpressionMetrics(BaseModel):
    n_clusters: int
    n_comparisons: int
    n_genes_tested: int
    cluster_key: str
    method: str


class DifferentialExpressionOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    results_df: pd.DataFrame
    metrics: DifferentialExpressionMetrics


class DifferentialExpressionMethod(MethodDefinition):
    """Differential expression analysis between all cluster pairs.

    Uses scanpy's rank_genes_groups to compute log fold change, p-values,
    and adjusted p-values for every gene across all clusters (one-vs-rest).

    Results are stored as:
      - adata.uns["rank_genes_groups"]: scanpy-native DE results
      - output.results_df: tidy DataFrame with columns:
          cluster, gene, logfoldchange, pval, pval_adj, score
        sorted by cluster then pval_adj ascending.
    """

    name = "differential_expression"
    version = "1.0.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return DifferentialExpressionInput

    def output_schema(self):
        return DifferentialExpressionOutput

    def execute(self, input: DifferentialExpressionInput, compute) -> DifferentialExpressionOutput:
        adata = input.adata.copy()
        cluster_key = resolve_cluster_key(adata, input.cluster_key)
        if cluster_key is None:
            raise ValueError(
                f"cluster_key '{input.cluster_key}' not found in adata.obs. "
                f"Available columns: {list(adata.obs.columns)}"
            )

        clusters = adata.obs[cluster_key].astype(str).unique().tolist()
        n_clusters = len(clusters)

        rank_kwargs: dict[str, object] = {}
        if "log1p" in getattr(adata, "layers", {}):
            rank_kwargs["layer"] = "log1p"
            rank_kwargs["use_raw"] = False

        # Run rank_genes_groups (one-vs-rest for each cluster)
        corr = _scanpy_corr_from_padj(input.corr_method)
        sc.tl.rank_genes_groups(
            adata,
            groupby=cluster_key,
            method=input.method,
            corr_method=corr,
            n_genes=adata.n_vars,  # always compute all genes; filter later
            **rank_kwargs,
        )

        # Convert to tidy DataFrame
        ranked_groups = _ranked_group_names(adata.uns["rank_genes_groups"], clusters)
        results_df = _extract_de_results(adata, ranked_groups, input.n_genes)

        metrics = DifferentialExpressionMetrics(
            n_clusters=n_clusters,
            n_comparisons=len(ranked_groups),
            n_genes_tested=adata.n_vars,
            cluster_key=cluster_key,
            method=input.method,
        )

        return DifferentialExpressionOutput(
            adata=adata,
            results_df=results_df,
            metrics=metrics,
        )


def _extract_de_results(
    adata: ad.AnnData,
    clusters: list[str],
    n_genes: int,
) -> pd.DataFrame:
    """Extract rank_genes_groups results into a tidy DataFrame."""
    rgg = adata.uns["rank_genes_groups"]
    rows = []

    def _cluster_values(field: str, cluster_name: str, size: int) -> np.ndarray:
        if field not in rgg:
            return np.full(size, np.nan, dtype=float)
        return np.asarray(rgg[field][cluster_name])

    for cluster in clusters:
        genes = np.asarray(rgg["names"][cluster])
        scores = np.asarray(rgg["scores"][cluster])
        logfcs = _cluster_values("logfoldchanges", cluster, len(genes))
        pvals = _cluster_values("pvals", cluster, len(genes))
        pvals_adj = _cluster_values("pvals_adj", cluster, len(genes))

        n = n_genes if n_genes > 0 else len(genes)
        for i in range(min(n, len(genes))):
            rows.append(
                {
                    "cluster": cluster,
                    "gene": genes[i],
                    "score": float(scores[i]),
                    "logfoldchange": float(logfcs[i]),
                    "pval": float(pvals[i]),
                    "pval_adj": float(pvals_adj[i]),
                }
            )

    df = pd.DataFrame(
        rows, columns=["cluster", "gene", "score", "logfoldchange", "pval", "pval_adj"]
    )
    # Some Scanpy methods (for example logreg) do not emit p-values/log fold changes.
    # Keep p-value-driven ordering when available, otherwise fall back to score ranking.
    df["_has_pval_adj"] = df["pval_adj"].notna()
    df["_sort_pval_adj"] = df["pval_adj"].fillna(np.inf)
    df["_sort_score"] = -df["score"].fillna(-np.inf)
    df = df.sort_values(
        ["cluster", "_has_pval_adj", "_sort_pval_adj", "_sort_score"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
    df = df.drop(columns=["_has_pval_adj", "_sort_pval_adj", "_sort_score"])
    return df


def results_to_csv(results_df: pd.DataFrame) -> bytes:
    """Serialise DE results DataFrame to CSV bytes for artifact storage."""
    buf = io.BytesIO()
    results_df.to_csv(buf, index=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Multi-mode DE (marker ranking vs pseudobulk inferential)
# ---------------------------------------------------------------------------


class MultiModeDEInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    de_mode: str = Field(
        default=DE_MODE_MARKER,
        description="marker_ranking | condition_de_within_celltype | pseudobulk_sample_level_contrast",
    )
    de_groupby_key: str | None = Field(
        default=None,
        description="Marker mode: cluster/cell-type column (defaults to cluster_key). Pseudobulk: optional stratum column.",
    )
    de_method: str = Field(
        default="wilcoxon", description="Scanpy rank_genes_groups method (marker mode)."
    )
    de_n_genes: int = Field(default=0, ge=0)
    de_sample_key: str | None = None
    de_condition_key: str | None = None
    de_focus_level: str | None = Field(
        default=None,
        description="condition_de_within_celltype: label in de_groupby_key column to subset cells.",
    )
    de_reference_level: str | None = None
    de_compare_level: str | None = None
    de_contrast: str | None = Field(default=None, description="e.g. 'Treatment_vs_Control'")
    de_min_cells_per_sample: int = Field(default=10, ge=1)
    de_min_samples_per_group: int = Field(default=2, ge=2)
    de_padj_method: str = Field(default="benjamini-hochberg")
    de_logfc_threshold: float = Field(default=0.0, ge=0.0)
    cluster_key: str = Field(
        default="leiden",
        description="Legacy alias used when de_groupby_key is unset (marker mode).",
    )


class MultiModeDEMetrics(BaseModel):
    de_mode: str
    method_requested: str
    method_executed: str
    n_genes_tested: int | None = None
    n_clusters: int | None = None
    n_comparisons: int | None = None
    cluster_key: str | None = None
    n_pseudobulk_profiles: int | None = None
    statistical_warning: str | None = None


class MultiModeDEOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    results_df: pd.DataFrame
    pseudobulk_results_df: pd.DataFrame | None = None
    metrics: MultiModeDEMetrics


class MultiModeDifferentialExpressionMethod(MethodDefinition):
    """Unified DE step: exploratory marker ranking or replicate-aware pseudobulk contrasts."""

    name = "differential_expression"
    version = "2.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return MultiModeDEInput

    def output_schema(self):
        return MultiModeDEOutput

    def execute(self, input: MultiModeDEInput, compute) -> MultiModeDEOutput:
        del compute
        mode = normalize_de_mode(input.de_mode)
        adata = input.adata

        if mode == DE_MODE_MARKER:
            groupby = (input.de_groupby_key or input.cluster_key or "leiden").strip()
            marker_in = DifferentialExpressionInput(
                adata=adata,
                cluster_key=groupby,
                method=input.de_method,
                n_genes=input.de_n_genes,
                corr_method=input.de_padj_method,
            )
            marker_out = DifferentialExpressionMethod().execute(marker_in, compute=None)
            expr_src = "layers_log1p" if "log1p" in getattr(adata, "layers", {}) else "adata_X"
            prov = {
                "de_mode": DE_MODE_MARKER,
                "method_requested": input.de_method,
                "method_executed": input.de_method,
                "groupby_key_used": marker_out.metrics.cluster_key,
                "condition_key_used": None,
                "sample_key_used": None,
                "expression_source_used": expr_src,
                "counts_source_used": None,
                "pseudobulk": False,
                "replicate_aware": False,
                "condition_aware": False,
                "cell_level_analysis": True,
                "sample_level_contrast": False,
                "statistical_warning": (
                    "Exploratory marker ranking (Scanpy rank_genes_groups); not a replicate-aware "
                    "inferential test at the sample level."
                ),
            }
            write_zerna_de_provenance(marker_out.adata, prov)
            metrics = MultiModeDEMetrics(
                de_mode=DE_MODE_MARKER,
                method_requested=input.de_method,
                method_executed=input.de_method,
                n_genes_tested=marker_out.metrics.n_genes_tested,
                n_clusters=marker_out.metrics.n_clusters,
                n_comparisons=marker_out.metrics.n_comparisons,
                cluster_key=marker_out.metrics.cluster_key,
                statistical_warning=prov["statistical_warning"],
            )
            return MultiModeDEOutput(
                adata=marker_out.adata,
                results_df=marker_out.results_df,
                pseudobulk_results_df=None,
                metrics=metrics,
            )

        # Pseudobulk modes
        if not input.de_sample_key or not str(input.de_sample_key).strip():
            raise ValueError(
                f"de_mode={mode!r} requires de_sample_key (obs column identifying biological replicates)."
            )
        if not input.de_condition_key or not str(input.de_condition_key).strip():
            raise ValueError(
                f"de_mode={mode!r} requires de_condition_key (obs column for the contrast factor)."
            )

        pb_df, agg_meta = run_pseudobulk_differential_expression(
            adata,
            de_mode=mode,
            sample_key=str(input.de_sample_key).strip(),
            condition_key=str(input.de_condition_key).strip(),
            groupby_key=(str(input.de_groupby_key).strip() if input.de_groupby_key else None),
            focus_level=(str(input.de_focus_level).strip() if input.de_focus_level else None),
            de_reference_level=input.de_reference_level,
            de_compare_level=input.de_compare_level,
            de_contrast=input.de_contrast,
            min_cells_per_sample=int(input.de_min_cells_per_sample),
            min_samples_per_group=int(input.de_min_samples_per_group),
            padj_method=input.de_padj_method,
            logfc_threshold=float(input.de_logfc_threshold),
        )

        out_adata = adata.copy()
        if "rank_genes_groups" in out_adata.uns:
            del out_adata.uns["rank_genes_groups"]
        out_adata.uns["de_pseudobulk_aggregation"] = agg_meta
        out_adata.uns["de_pseudobulk_tidy_records"] = pb_df.to_dict(orient="records")

        prov = {
            "de_mode": mode,
            "method_requested": input.de_method,
            "method_executed": agg_meta.get("statistical_model", "pydeseq2_negative_binomial_wald"),
            "groupby_key_used": (input.de_groupby_key or input.cluster_key or "").strip() or None,
            "condition_key_used": str(input.de_condition_key).strip(),
            "sample_key_used": str(input.de_sample_key).strip(),
            "expression_source_used": "pseudobulk_aggregated_counts_pydeseq2",
            "counts_source_used": "layers_counts",
            "pseudobulk": True,
            "replicate_aware": True,
            "condition_aware": True,
            "cell_level_analysis": False,
            "sample_level_contrast": mode == DE_MODE_PSEUDOBULK,
            "statistical_warning": None,
            "aggregation_summary": agg_meta,
            "inferential_backend_requested": "pydeseq2",
            "inferential_backend_executed": str(agg_meta.get("inferential_backend", "pydeseq2")),
            "count_model_based": True,
            "sample_level_metadata_used": True,
            "design_summary": str(agg_meta.get("design_formula", "~ condition")),
            "contrast_summary": (
                f"{agg_meta.get('numerator_condition')} vs {agg_meta.get('denominator_condition')} "
                f"(Wald; log2 fold change from PyDESeq2)"
            ),
            "fallback_applied": False,
            "lfc_scale": str(agg_meta.get("lfc_scale", "log2")),
        }
        if mode == DE_MODE_CONDITION:
            prov["de_focus_level"] = (
                str(input.de_focus_level).strip() if input.de_focus_level else None
            )
            prov["sample_level_contrast"] = False
        write_zerna_de_provenance(out_adata, prov)

        metrics = MultiModeDEMetrics(
            de_mode=mode,
            method_requested=input.de_method,
            method_executed=str(prov["method_executed"]),
            n_genes_tested=int(out_adata.n_vars),
            n_pseudobulk_profiles=agg_meta.get("n_pseudobulk_profiles"),
            statistical_warning=None,
        )
        empty_marker = pd.DataFrame(
            columns=["cluster", "gene", "score", "logfoldchange", "pval", "pval_adj"]
        )
        return MultiModeDEOutput(
            adata=out_adata,
            results_df=empty_marker,
            pseudobulk_results_df=pb_df,
            metrics=metrics,
        )
