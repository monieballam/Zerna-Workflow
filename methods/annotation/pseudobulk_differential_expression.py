"""Replicate-aware pseudobulk differential expression (sample-level contrasts)."""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp
from anndata import AnnData

logger = logging.getLogger(__name__)

DE_MODES_PSEUDOBULK = frozenset(
    {"condition_de_within_celltype", "pseudobulk_sample_level_contrast"}
)

_PYDESEQ2_INSTALL_HINT = (
    "Pseudobulk inferential DE requires the `pydeseq2` package (negative binomial / Wald). "
    "Install it in the compute environment, e.g. add `pydeseq2>=0.5` to the `methods` package "
    "dependencies and reinstall. There is no silent fallback to exploratory marker ranking or "
    "Gaussian t-tests on pseudobulk counts."
)


def _import_pydeseq2() -> tuple[Any, Any, Any]:
    try:
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.default_inference import DefaultInference
        from pydeseq2.ds import DeseqStats

        return DeseqDataSet, DeseqStats, DefaultInference
    except ImportError as e:
        raise ValueError(f"{_PYDESEQ2_INSTALL_HINT} Original import error: {e}") from e


def _parse_contrast(contrast: str | None) -> tuple[str, str] | None:
    if not contrast or not str(contrast).strip():
        return None
    s = str(contrast).strip()
    for sep in ("_vs_", " vs ", " VS ", "v", ":"):
        if sep in s:
            parts = [x.strip() for x in re.split(re.escape(sep), s, maxsplit=1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]
    return None


def _resolve_two_groups(
    conditions: pd.Series,
    reference: str | None,
    compare: str | None,
    contrast: str | None,
) -> tuple[str, str]:
    parsed = _parse_contrast(contrast)
    if parsed:
        return parsed[0], parsed[1]
    if reference and compare:
        return str(compare), str(reference)
    uniq = sorted({str(x).strip() for x in conditions.dropna().unique() if str(x).strip()})
    if len(uniq) != 2:
        raise ValueError(
            f"Pseudobulk DE requires exactly two condition levels after filtering, or set "
            f"de_reference_level and de_compare_level (or de_contrast as 'A_vs_B'). "
            f"Found {len(uniq)} levels: {uniq[:12]!r}{'...' if len(uniq) > 12 else ''}."
        )
    return uniq[0], uniq[1]


def _run_pydeseq2_two_group(
    *,
    var_names: np.ndarray,
    sub_pb: pd.DataFrame,
    num_group: str,
    den_group: str,
    stratum_label: str,
    logfc_threshold: float,
) -> pd.DataFrame:
    """Wald NB GLM via PyDESeq2; counts rows=samples, cols=genes (integers)."""
    DeseqDataSet, DeseqStats, DefaultInference = _import_pydeseq2()

    sample_ids = [str(s) for s in sub_pb["sample"].tolist()]
    mat = np.stack(sub_pb["counts"].to_numpy(), axis=0)
    mat = np.rint(np.asarray(mat, dtype=np.float64)).astype(np.int64)
    counts_df = pd.DataFrame(mat, index=sample_ids, columns=var_names)

    conds = sub_pb["condition"].astype(str).tolist()
    meta = pd.DataFrame({"condition": conds}, index=sample_ids)
    meta["condition"] = pd.Categorical(
        meta["condition"],
        categories=[str(den_group), str(num_group)],
    )

    n_samples = len(sample_ids)
    inference = DefaultInference(n_cpus=1)
    refit_cooks = n_samples >= 10

    try:
        dds = DeseqDataSet(
            counts=counts_df,
            metadata=meta,
            design="~condition",
            refit_cooks=refit_cooks,
            inference=inference,
        )
        dds.deseq2()
        stat_res = DeseqStats(
            dds,
            contrast=["condition", str(num_group), str(den_group)],
            inference=inference,
        )
        stat_res.summary()
    except Exception as e:
        raise ValueError(
            f"PyDESeq2 analysis failed for stratum={stratum_label!r} "
            f"(contrast {num_group!r} vs reference {den_group!r}): {e}"
        ) from e

    res = stat_res.results_df.copy()
    res = res.reindex(var_names.astype(str))

    logfc = res["log2FoldChange"].to_numpy(dtype=np.float64, copy=True)
    stat = (
        res["stat"].to_numpy(dtype=np.float64, copy=True)
        if "stat" in res.columns
        else np.full(len(var_names), np.nan)
    )
    pval = res["pvalue"].to_numpy(dtype=np.float64, copy=True)
    padj = res["padj"].to_numpy(dtype=np.float64, copy=True)

    block = pd.DataFrame(
        {
            "gene": var_names.astype(str),
            "stratum": stratum_label,
            "numerator_condition": str(num_group),
            "denominator_condition": str(den_group),
            "logfoldchange": logfc,
            "stat": stat,
            "pval": pval,
            "pval_adj": padj,
        }
    )
    if logfc_threshold > 0:
        block = block.loc[np.abs(block["logfoldchange"]) >= logfc_threshold]
    return block


def run_pseudobulk_differential_expression(
    adata: AnnData,
    *,
    de_mode: str,
    sample_key: str,
    condition_key: str,
    groupby_key: str | None,
    focus_level: str | None,
    de_reference_level: str | None,
    de_compare_level: str | None,
    de_contrast: str | None,
    min_cells_per_sample: int,
    min_samples_per_group: int,
    padj_method: str,
    logfc_threshold: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Aggregate raw integer counts to sample-level pseudobulk, then run PyDESeq2
    (negative binomial + Wald) for simple two-group contrasts per stratum.

    Returns (results_df, aggregation_meta).
    """
    pm = str(padj_method or "").strip().lower()
    if pm and pm not in ("bh", "benjamini-hochberg", "fdr_bh"):
        logger.info(
            "de_padj_method=%r is ignored for pseudobulk; PyDESeq2 applies Benjamini–Hochberg to Wald p-values.",
            padj_method,
        )

    if "counts" not in getattr(adata, "layers", {}):
        raise ValueError(
            "Pseudobulk DE requires `adata.layers['counts']` with raw (integer) counts. "
            "Ensure normalization persisted counts or use a pipeline stage that writes the counts layer."
        )

    X = adata.layers["counts"]
    obs = adata.obs

    if sample_key not in obs.columns:
        raise ValueError(f"de_sample_key '{sample_key}' not found in adata.obs.")
    if condition_key not in obs.columns:
        raise ValueError(f"de_condition_key '{condition_key}' not found in adata.obs.")

    obs_idx = np.arange(int(adata.n_obs), dtype=np.int64)
    if de_mode == "condition_de_within_celltype":
        if not focus_level or not str(focus_level).strip():
            raise ValueError(
                "condition_de_within_celltype requires de_focus_level (cluster or cell-type label) "
                "to subset cells before pseudobulk aggregation."
            )
        if not groupby_key or not str(groupby_key).strip():
            raise ValueError(
                "condition_de_within_celltype requires de_groupby_key (e.g. leiden or annotation_label) "
                "to define which column is filtered by de_focus_level."
            )
        gk = str(groupby_key).strip()
        if gk not in obs.columns:
            raise ValueError(f"de_groupby_key '{gk}' not found in adata.obs.")
        fl = str(focus_level).strip()
        mask = obs[gk].astype(str).str.strip().to_numpy() == fl
        if int(mask.sum()) < min_cells_per_sample:
            raise ValueError(
                f"No cells (or fewer than de_min_cells_per_sample={min_cells_per_sample}) match "
                f"de_focus_level={fl!r} on column {gk!r}."
            )
        obs_idx = obs_idx[mask]

    if sp.issparse(X):
        Xsub = X[obs_idx, :]
    else:
        Xsub = np.asarray(X[obs_idx, :])

    work_obs = obs.iloc[obs_idx].copy()

    samples = work_obs[sample_key].astype(str)
    conditions = work_obs[condition_key].astype(str)
    strata: pd.Series | None = None
    if de_mode == "pseudobulk_sample_level_contrast" and groupby_key and str(groupby_key).strip():
        gk = str(groupby_key).strip()
        if gk not in work_obs.columns:
            raise ValueError(f"de_groupby_key '{gk}' not found in adata.obs.")
        strata = work_obs[gk].astype(str)

    n_genes = int(adata.n_vars)
    var_names = np.asarray(adata.var_names, dtype=str)

    def aggregate_unit(rows: np.ndarray, label: str) -> tuple[np.ndarray, int]:
        """Return summed counts vector and number of cells."""
        if sp.issparse(Xsub):
            sub = Xsub[rows, :]
            if sub.nnz == 0:
                vec = np.zeros(n_genes, dtype=np.float64)
            else:
                vec = np.asarray(sub.sum(axis=0)).ravel().astype(np.float64)
        else:
            vec = np.asarray(Xsub[rows, :].sum(axis=0)).ravel().astype(np.float64)
        return vec, int(len(rows))

    rows_all = np.arange(work_obs.shape[0])
    pseudobulk_rows: list[dict[str, Any]] = []

    stratum_arr = strata.to_numpy(dtype=object) if strata is not None else None
    sample_arr = samples.to_numpy(dtype=str)
    cond_arr = conditions.to_numpy(dtype=str)

    if stratum_arr is not None:
        for stratum in sorted({str(x) for x in stratum_arr}):
            sub_ix = rows_all[stratum_arr[rows_all] == stratum]
            if sub_ix.size == 0:
                continue
            for sample in sorted(set(sample_arr[sub_ix])):
                r = sub_ix[sample_arr[sub_ix] == sample]
                if r.size == 0:
                    continue
                vec, n_cells = aggregate_unit(r, str(sample))
                if n_cells < min_cells_per_sample:
                    continue
                uc = np.unique(cond_arr[r])
                if uc.size != 1:
                    raise ValueError(
                        f"Multiple {condition_key!r} values for sample={sample!r} stratum={stratum!r}: {uc!r}"
                    )
                pseudobulk_rows.append(
                    {
                        "sample": str(sample),
                        "stratum": str(stratum),
                        "condition": str(uc[0]),
                        "n_cells": n_cells,
                        "counts": vec,
                    }
                )
    else:
        for sample in sorted(set(sample_arr)):
            r = rows_all[sample_arr == sample]
            if r.size == 0:
                continue
            vec, n_cells = aggregate_unit(r, str(sample))
            if n_cells < min_cells_per_sample:
                continue
            uc = np.unique(cond_arr[r])
            if uc.size != 1:
                raise ValueError(f"Multiple {condition_key!r} values for sample={sample!r}: {uc!r}")
            pseudobulk_rows.append(
                {
                    "sample": str(sample),
                    "stratum": None,
                    "condition": str(uc[0]),
                    "n_cells": n_cells,
                    "counts": vec,
                }
            )

    if len(pseudobulk_rows) < 2:
        raise ValueError(
            "After filtering (min_cells_per_sample), fewer than two pseudobulk profiles remain. "
            "Check sample_key, counts layer, and thresholds."
        )

    pb = pd.DataFrame(pseudobulk_rows)
    num_group, den_group = _resolve_two_groups(
        pb["condition"], de_reference_level, de_compare_level, de_contrast
    )

    all_rows: list[pd.DataFrame] = []
    strata_loop = [None] if strata is None else sorted(pb["stratum"].dropna().unique())

    for strat in strata_loop:
        sub_pb = pb if strat is None else pb.loc[pb["stratum"] == strat]
        if sub_pb.empty:
            continue
        g1 = sub_pb.loc[sub_pb["condition"] == num_group]
        g0 = sub_pb.loc[sub_pb["condition"] == den_group]
        if g1.shape[0] < min_samples_per_group or g0.shape[0] < min_samples_per_group:
            raise ValueError(
                f"Pseudobulk DE requires at least de_min_samples_per_group={min_samples_per_group} "
                f"samples in each arm. For stratum={strat!r}: "
                f"'{num_group}' n={g1.shape[0]}, '{den_group}' n={g0.shape[0]}."
            )

        stratum_label = "all" if strat is None else str(strat)
        block = _run_pydeseq2_two_group(
            var_names=var_names,
            sub_pb=pd.concat([g1, g0], axis=0),
            num_group=num_group,
            den_group=den_group,
            stratum_label=stratum_label,
            logfc_threshold=logfc_threshold,
        )
        all_rows.append(block)

    if not all_rows:
        raise ValueError("Pseudobulk DE produced no result blocks.")

    results_df = pd.concat(all_rows, ignore_index=True)
    try:
        import pydeseq2 as _pds2

        pds2_ver = getattr(_pds2, "__version__", "unknown")
    except Exception:
        pds2_ver = "unknown"

    meta = {
        "n_pseudobulk_profiles": int(pb.shape[0]),
        "n_samples_distinct": int(pb["sample"].nunique()),
        "numerator_condition": num_group,
        "denominator_condition": den_group,
        "aggregation_units": "sample_x_stratum" if strata is not None else "sample",
        "padj_method_applied": "benjamini-hochberg (PyDESeq2 Wald)",
        "statistical_model": "pydeseq2_negative_binomial_wald",
        "inferential_backend": "pydeseq2",
        "pydeseq2_version": pds2_ver,
        "design_formula": "~ condition",
        "condition_metadata_column": "condition",
        "lfc_scale": "log2",
        "contrast": [str(num_group), str(den_group)],
    }
    return results_df, meta
