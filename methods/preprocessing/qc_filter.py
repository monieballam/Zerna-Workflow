"""QC filtering for single-cell RNA-seq (droplet-based) with biology-aware metrics."""

from __future__ import annotations

import json
import logging
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition
from methods.h5ad_uns_coercion import _sanitize_for_h5ad_uns
from methods.preprocessing.qc_species import (
    build_gene_matching_report,
    default_hb_gene_list,
    default_hk_gene_list,
    default_ribo_prefixes,
    mito_gene_mask,
    resolve_effective_species,
)

logger = logging.getLogger(__name__)


def _assert_h5ad_safe_report(report: Any) -> None:
    """Fail fast if structure still contains NaN or non-JSON types that break h5ad I/O."""
    json.dumps(report, allow_nan=False)


def expand_zerna_qc_report_for_export(qc_report: Any) -> Any:
    """Turn ``filter_rules_json`` back into ``filter_rules`` for JSON sidecars / UIs."""
    if not isinstance(qc_report, dict):
        return qc_report
    out = dict(qc_report)
    oqc = out.get("obs_qc_columns")
    if isinstance(oqc, np.ndarray):
        out["obs_qc_columns"] = [str(x).strip() for x in oqc.ravel().tolist() if str(x).strip()]
    frj = out.get("filter_rules_json")
    if isinstance(frj, str) and "filter_rules" not in out:
        try:
            parsed = json.loads(frj)
        except json.JSONDecodeError:
            return qc_report
        out["filter_rules"] = parsed
        out.pop("filter_rules_json", None)
    return out


class QCFilterInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    """QC species: ``auto`` infers from ``var_names``; ``human`` / ``mouse`` use species-aware gene matching."""
    species: str = "auto"
    min_genes: int = 200
    max_genes: int = 6000
    min_cells: int = 3
    max_mito_pct: float = 20.0
    min_counts: float | None = None
    max_counts: float | None = None
    max_ribo_pct: float | None = None
    compute_hb_pct: bool = False
    max_hb_pct: float | None = None
    filter_by_housekeeping: bool = False
    max_hk_pct: float | None = None
    # Legacy / programmatic only (omit in dashboard): single mito prefix overrides species-aware mito matching.
    mito_prefix: str | None = None
    ribo_prefixes: list[str] | None = Field(
        default=None,
        description="Override ribosomal prefixes; default is species-appropriate internal list.",
    )
    hb_gene_names: list[str] | None = Field(
        default=None,
        description="Override hemoglobin gene symbols; default list follows effective species.",
    )
    hk_gene_names: list[str] | None = Field(
        default=None,
        description="Override housekeeping genes; default list follows effective species.",
    )


class QCFilterRuleSummary(BaseModel):
    rule: str
    cells_before: int
    cells_removed: int
    cells_after: int


class QCMetrics(BaseModel):
    n_cells_before: int
    n_cells_after: int
    n_genes_before: int
    n_genes_after: int
    median_genes_per_cell: float
    median_counts_per_cell: float
    filter_rules: list[QCFilterRuleSummary] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)


class QCFilterOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: QCMetrics


class QCFilterMethod(MethodDefinition):
    name = "qc_filter"
    version = "2.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return QCFilterInput

    def output_schema(self):
        return QCFilterOutput

    def execute(self, input: QCFilterInput, compute) -> QCFilterOutput:
        adata = input.adata
        n_cells_before = adata.n_obs
        n_genes_before = adata.n_vars

        species_req = str(input.species or "auto").strip().lower()
        if species_req not in ("auto", "human", "mouse"):
            species_req = "auto"

        legacy_mito = input.mito_prefix.strip() if input.mito_prefix else None
        if legacy_mito == "":
            legacy_mito = None

        species_eff, species_inference = resolve_effective_species(
            species_req, list(adata.var_names)
        )
        if species_req in ("human", "mouse"):
            species_inference = {
                "mode": "explicit",
                "ambiguous": False,
                "warning": None,
                "requested": species_req,
            }

        ribo_list = (
            list(input.ribo_prefixes)
            if input.ribo_prefixes is not None
            else default_ribo_prefixes(species_eff)
        )

        need_hb_metrics = (
            bool(input.compute_hb_pct)
            or input.hb_gene_names is not None
            or input.max_hb_pct is not None
        )
        hb_genes = (
            list(input.hb_gene_names)
            if input.hb_gene_names is not None
            else (
                default_hb_gene_list(species_eff)
                if bool(input.compute_hb_pct) or input.max_hb_pct is not None
                else None
            )
        )

        need_hk_metrics = bool(
            input.filter_by_housekeeping
            or input.max_hk_pct is not None
            or input.hk_gene_names is not None
        )
        hk_genes = (
            list(input.hk_gene_names)
            if input.hk_gene_names is not None
            else (default_hk_gene_list(species_eff) if need_hk_metrics else None)
        )

        effective_max_hb = input.max_hb_pct
        if need_hb_metrics and effective_max_hb is None and bool(input.compute_hb_pct):
            effective_max_hb = 5.0

        effective_max_hk = input.max_hk_pct
        if input.filter_by_housekeeping and effective_max_hk is None:
            effective_max_hk = 50.0

        gene_matching = build_gene_matching_report(
            species_request=species_req,
            species_effective=species_eff,
            species_inference=species_inference,
            legacy_mito_prefix=legacy_mito,
            ribo_prefixes=ribo_list,
            hb_gene_names=hb_genes,
            hk_gene_names=hk_genes,
        )

        _compute_qc_metrics(
            adata,
            var_index=adata.var_names,
            species_effective=species_eff,
            legacy_mito_prefix=legacy_mito,
            ribo_prefixes=ribo_list,
            hb_gene_names=hb_genes,
            hk_gene_names=hk_genes,
        )

        rule_summaries: list[QCFilterRuleSummary] = []
        mask = np.ones(adata.n_obs, dtype=bool)

        def apply_rule(name: str, rule_mask: np.ndarray) -> None:
            nonlocal mask
            before = int(mask.sum())
            mask = mask & rule_mask
            after = int(mask.sum())
            rule_summaries.append(
                QCFilterRuleSummary(
                    rule=name,
                    cells_before=before,
                    cells_removed=before - after,
                    cells_after=after,
                )
            )

        n_genes = np.asarray(adata.obs["n_genes_by_counts"])
        apply_rule("min_genes", n_genes >= input.min_genes)
        apply_rule("max_genes", n_genes <= input.max_genes)
        apply_rule("max_mito_pct", np.asarray(adata.obs["pct_counts_mt"]) < input.max_mito_pct)

        if input.min_counts is not None:
            apply_rule(
                "min_counts",
                np.asarray(adata.obs["total_counts"]) >= float(input.min_counts),
            )
        if input.max_counts is not None:
            apply_rule(
                "max_counts",
                np.asarray(adata.obs["total_counts"]) <= float(input.max_counts),
            )
        if input.max_ribo_pct is not None and "pct_counts_ribo" in adata.obs.columns:
            apply_rule(
                "max_ribo_pct",
                np.asarray(adata.obs["pct_counts_ribo"]) < float(input.max_ribo_pct),
            )
        if effective_max_hk is not None and "pct_counts_hk" in adata.obs.columns:
            apply_rule(
                "max_hk_pct",
                np.asarray(adata.obs["pct_counts_hk"]) < float(effective_max_hk),
            )
        if (
            need_hb_metrics
            and effective_max_hb is not None
            and "pct_counts_hb" in adata.obs.columns
        ):
            apply_rule(
                "max_hb_pct",
                np.asarray(adata.obs["pct_counts_hb"]) < float(effective_max_hb),
            )
        adata = _subset_adata_inplace(adata, obs_mask=mask)
        n_cells_after_cell_filters = adata.n_obs

        n_genes_before_gene_filter = adata.n_vars
        if adata.n_obs > 0:
            gene_counts = _nonzero_counts(adata.X, axis=0)
            gene_mask = gene_counts >= input.min_cells
            adata = _subset_adata_inplace(adata, var_mask=gene_mask)
        genes_removed = n_genes_before_gene_filter - adata.n_vars

        _compute_qc_metrics(
            adata,
            var_index=adata.var_names,
            species_effective=species_eff,
            legacy_mito_prefix=legacy_mito,
            ribo_prefixes=ribo_list,
            hb_gene_names=hb_genes,
            hk_gene_names=hk_genes,
        )

        thresholds: dict[str, Any] = {
            "qc_species": species_req,
            "species_effective": species_eff,
            "min_genes": input.min_genes,
            "max_genes": input.max_genes,
            "min_cells": input.min_cells,
            "max_mito_pct": input.max_mito_pct,
            "mito_prefix": legacy_mito,
            "min_counts": input.min_counts,
            "max_counts": input.max_counts,
            "max_ribo_pct": input.max_ribo_pct,
            "compute_hb_pct": input.compute_hb_pct,
            "max_hb_pct": input.max_hb_pct,
            "max_hb_pct_effective": effective_max_hb if need_hb_metrics else None,
            "filter_by_housekeeping": input.filter_by_housekeeping,
            "max_hk_pct": input.max_hk_pct,
            "max_hk_pct_effective": effective_max_hk,
        }

        # mode='json' forces plain Python scalars (no np.int64) in each rule dict.
        filter_rules_plain = [r.model_dump(mode="json") for r in rule_summaries]
        report = {
            "version": 2,
            "n_cells_input": int(n_cells_before),
            "n_cells_after_cell_filters": int(n_cells_after_cell_filters),
            "n_genes_before_gene_filter": int(n_genes_before_gene_filter),
            "n_genes_removed_low_detection": int(genes_removed),
            "n_genes_after_gene_filter": int(adata.n_vars),
            "filter_rules_json": json.dumps(filter_rules_plain, allow_nan=False),
            "thresholds": thresholds,
            "gene_matching": gene_matching,
            "obs_qc_columns": [
                c
                for c in (
                    "n_genes_by_counts",
                    "total_counts",
                    "pct_counts_mt",
                    "pct_counts_ribo",
                    "pct_counts_hk",
                    "pct_counts_hb",
                )
                if c in adata.obs.columns
            ],
        }
        safe_report = _sanitize_for_h5ad_uns(report, _path="zerna_qc_report")
        _assert_h5ad_safe_report(safe_report)
        adata.uns["zerna_qc_report"] = safe_report

        metrics = QCMetrics(
            n_cells_before=n_cells_before,
            n_cells_after=adata.n_obs,
            n_genes_before=n_genes_before,
            n_genes_after=adata.n_vars,
            median_genes_per_cell=float(adata.obs["n_genes_by_counts"].median())
            if adata.n_obs > 0
            else 0.0,
            median_counts_per_cell=float(adata.obs["total_counts"].median())
            if adata.n_obs > 0
            else 0.0,
            filter_rules=rule_summaries,
            thresholds=thresholds,
        )

        return QCFilterOutput(adata=adata, metrics=metrics)


def _nonzero_counts(matrix, axis: int) -> np.ndarray:
    if sp.issparse(matrix):
        return np.asarray(matrix.getnnz(axis=axis)).ravel()
    return np.asarray(np.count_nonzero(matrix, axis=axis)).ravel()


def _sum_axis(matrix, axis: int) -> np.ndarray:
    return np.asarray(matrix.sum(axis=axis)).ravel()


def _pct_of_total(counts: np.ndarray, total: np.ndarray) -> np.ndarray:
    return np.divide(
        counts * 100.0,
        total,
        out=np.zeros_like(total, dtype=np.float32),
        where=total > 0,
    )


def _subset_adata_inplace(adata: ad.AnnData, *, obs_mask=None, var_mask=None) -> ad.AnnData:
    """Subset AnnData without forcing full matrix copies on sparse inputs."""
    if obs_mask is not None:
        obs_mask = np.asarray(obs_mask, dtype=bool)
        if obs_mask.shape[0] != adata.n_obs:
            raise ValueError("Observation mask length does not match adata.n_obs")
        adata._inplace_subset_obs(obs_mask)
    if var_mask is not None:
        var_mask = np.asarray(var_mask, dtype=bool)
        if var_mask.shape[0] != adata.n_vars:
            raise ValueError("Variable mask length does not match adata.n_vars")
        adata._inplace_subset_var(var_mask)
    return adata


def _compute_qc_metrics(
    adata: ad.AnnData,
    *,
    var_index: pd.Index,
    species_effective: str,
    legacy_mito_prefix: str | None,
    ribo_prefixes: list[str],
    hb_gene_names: list[str] | None,
    hk_gene_names: list[str] | None,
) -> None:
    """Populate per-cell QC columns (uses ``adata.X``). Gene masks follow species or legacy mito prefix."""
    vn = var_index.astype(str)
    upper = vn.str.upper()

    mt_mask = mito_gene_mask(
        vn, species_effective=species_effective, legacy_mito_prefix=legacy_mito_prefix
    )
    adata.var["mt"] = mt_mask

    rp_tuples = tuple(p.upper() for p in ribo_prefixes if p)
    ribo_mask = (
        np.asarray(upper.str.startswith(rp_tuples), dtype=bool)
        if rp_tuples
        else np.zeros(len(vn), dtype=bool)
    )
    adata.var["ribo"] = ribo_mask

    if hk_gene_names:
        hk_set = {g.upper() for g in hk_gene_names}
        hk_mask = np.asarray(upper.isin(hk_set), dtype=bool)
    else:
        hk_mask = np.zeros(len(vn), dtype=bool)
    adata.var["hk"] = hk_mask

    if hb_gene_names:
        hb_set = {g.upper() for g in hb_gene_names}
        hb_mask = np.asarray(upper.isin(hb_set), dtype=bool)
    else:
        hb_mask = np.zeros(len(vn), dtype=bool)
    adata.var["hb"] = hb_mask

    n_genes_by_counts = _nonzero_counts(adata.X, axis=1).astype(np.int32, copy=False)
    total_counts = _sum_axis(adata.X, axis=1).astype(np.float32, copy=False)

    if mt_mask.any():
        mt_c = _sum_axis(adata.X[:, mt_mask], axis=1).astype(np.float32, copy=False)
    else:
        mt_c = np.zeros(adata.n_obs, dtype=np.float32)
    if ribo_mask.any():
        ribo_c = _sum_axis(adata.X[:, ribo_mask], axis=1).astype(np.float32, copy=False)
    else:
        ribo_c = np.zeros(adata.n_obs, dtype=np.float32)
    if hk_mask.any():
        hk_c = _sum_axis(adata.X[:, hk_mask], axis=1).astype(np.float32, copy=False)
    else:
        hk_c = np.zeros(adata.n_obs, dtype=np.float32)
    if hb_mask.any():
        hb_c = _sum_axis(adata.X[:, hb_mask], axis=1).astype(np.float32, copy=False)
    else:
        hb_c = np.zeros(adata.n_obs, dtype=np.float32)

    adata.obs["n_genes_by_counts"] = n_genes_by_counts
    adata.obs["total_counts"] = total_counts
    adata.obs["pct_counts_mt"] = _pct_of_total(mt_c, total_counts)
    adata.obs["pct_counts_ribo"] = _pct_of_total(ribo_c, total_counts)
    adata.obs["pct_counts_hk"] = _pct_of_total(hk_c, total_counts)
    if hb_gene_names:
        adata.obs["pct_counts_hb"] = _pct_of_total(hb_c, total_counts)
    elif "pct_counts_hb" in adata.obs.columns:
        del adata.obs["pct_counts_hb"]
