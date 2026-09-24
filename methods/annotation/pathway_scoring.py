"""Pathway scoring method using decoupler for single-cell RNA-seq data."""

from __future__ import annotations

import logging
import threading
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.base import MethodDefinition

# decoupler can trigger Numba's workqueue threading backend, which is not
# thread-safe across concurrent Python threads. Serialize those calls so
# concurrent runs do not crash inside pathway scoring.
_DECOUPLER_EXECUTION_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


class PathwayScoringInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    net: pd.DataFrame = Field(
        description=(
            "Gene set / pathway network DataFrame with columns: "
            "'source' (pathway name), 'target' (gene name), 'weight' (optional, default 1.0). "
            "Loaded from a KnowledgePack (MSigDB, GO, KEGG, etc.)."
        )
    )
    pathway_database: str = Field(
        default="custom",
        description="Name of the pathway database (for provenance; e.g. 'MSigDB', 'GO', 'KEGG')",
    )
    knowledge_pack_version: str | None = Field(
        default=None,
        description="KnowledgePack version for provenance tracking",
    )
    methods: list[str] = Field(
        default=["ulm"],
        description="decoupler activity inference methods to run (e.g. ['ulm', 'mlm', 'aucell'])",
    )
    min_n: int = Field(
        default=5,
        ge=1,
        description="Minimum number of targets per source to include in scoring",
    )
    obsm_key: str = Field(
        default="pathway_scores",
        description="Key under adata.obsm where scores are stored",
    )


class PathwayScoringMetrics(BaseModel):
    n_pathways_scored: int
    n_cells: int
    pathway_database: str
    knowledge_pack_version: str | None
    methods_used: list[str]
    obsm_key: str


class PathwayScoringOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: PathwayScoringMetrics


class PathwayScoringMethod(MethodDefinition):
    """Per-cell pathway *activity scoring* (not contrast-based enrichment).

    Uses decoupler (and a PROGENy fast path) to assign pathway activity scores
    to each cell from expression. This is exploratory cell-level scoring, not
    replicate-aware or DE-contrast pathway enrichment.

    Scores are stored in:
      - adata.obsm[obsm_key]: primary score matrix (n_cells × n_pathways)
        using the first method in `methods`
      - adata.obsm[f"{obsm_key}_{method}"]: scores for each additional method
      - adata.uns["pathway_scoring_meta"]: legacy provenance (unchanged keys)
      - adata.uns["zerna_pathway"]: pipeline-aligned activity-scoring contract
    """

    name = "pathway_scoring"
    version = "1.1.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return PathwayScoringInput

    def output_schema(self):
        return PathwayScoringOutput

    def execute(self, input: PathwayScoringInput, compute) -> PathwayScoringOutput:
        del compute
        adata = input.adata
        net = _prepare_net(input.net)
        expr_matrix, expr_meta = _resolve_expression_matrix(adata)
        score_adata, filtered_net = _prepare_scoring_input(adata, net, expr_matrix)

        methods_used: list[str] = []
        primary_scores: np.ndarray | None = None
        pathway_names: list[str] = []

        for i, method in enumerate(input.methods):
            scores_df, method_used = _score_pathways(
                score_adata,
                filtered_net,
                method,
                input.min_n,
                input.pathway_database,
            )
            if scores_df is None or scores_df.empty:
                continue

            methods_used.append(method_used)
            key = input.obsm_key if i == 0 else f"{input.obsm_key}_{method}"
            adata.obsm[key] = scores_df.values.astype(np.float32)

            if i == 0:
                primary_scores = scores_df.values.astype(np.float32)
                pathway_names = list(scores_df.columns)

        # Ensure primary key always exists (use zeros if all methods failed)
        if input.obsm_key not in adata.obsm:
            adata.obsm[input.obsm_key] = np.zeros((adata.n_obs, 0), dtype=np.float32)

        # Store provenance metadata (legacy block; keep keys stable for older consumers)
        adata.uns["pathway_scoring_meta"] = {
            "method": self.name,
            "version": self.version,
            "pathway_database": input.pathway_database,
            "knowledge_pack_version": input.knowledge_pack_version,
            "methods_used": methods_used,
            "obsm_key": input.obsm_key,
            "n_pathways": len(pathway_names),
            "pathway_names": pathway_names,
            "expression_source_used": expr_meta["expression_source_used"],
            "used_log1p_layer": expr_meta["used_log1p_layer"],
            "fallback_to_adata_x": expr_meta["fallback_to_adata_x"],
        }

        adata.uns["zerna_pathway"] = {
            "pathway_mode": "cell_level_activity_scoring",
            "pathway_database_requested": input.pathway_database,
            "pathway_database_executed": input.pathway_database,
            "pathway_method_requested": list(input.methods),
            "pathway_methods_executed": list(methods_used),
            "expression_source_used": expr_meta["expression_source_used"],
            "used_log1p_layer": expr_meta["used_log1p_layer"],
            "fallback_to_adata_x": expr_meta["fallback_to_adata_x"],
            "per_cell": True,
            "condition_aware": False,
            "replicate_aware": False,
            "obsm_key_written": input.obsm_key,
            "n_pathways": len(pathway_names),
            "knowledge_pack_version": input.knowledge_pack_version,
            "method_version": self.version,
        }

        n_pathways = primary_scores.shape[1] if primary_scores is not None else 0

        metrics = PathwayScoringMetrics(
            n_pathways_scored=n_pathways,
            n_cells=int(adata.n_obs),
            pathway_database=input.pathway_database,
            knowledge_pack_version=input.knowledge_pack_version,
            methods_used=methods_used,
            obsm_key=input.obsm_key,
        )

        return PathwayScoringOutput(adata=adata, metrics=metrics)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_expression_matrix(adata: ad.AnnData) -> tuple[Any, dict[str, Any]]:
    """Prefer log-normalized layer for activity scoring; otherwise adata.X."""
    layers = getattr(adata, "layers", None) or {}
    if "log1p" in layers:
        return layers["log1p"], {
            "expression_source_used": "layers_log1p",
            "used_log1p_layer": True,
            "fallback_to_adata_x": False,
        }
    return adata.X, {
        "expression_source_used": "adata_X",
        "used_log1p_layer": False,
        "fallback_to_adata_x": True,
    }


def _prepare_net(net: pd.DataFrame) -> pd.DataFrame:
    """Ensure net has required columns: source, target, weight."""
    net = net.copy()
    if "weight" not in net.columns:
        net["weight"] = 1.0
    required = {"source", "target", "weight"}
    missing = required - set(net.columns)
    if missing:
        raise ValueError(f"net DataFrame is missing columns: {missing}")
    return net[["source", "target", "weight"]]


def _prepare_scoring_input(
    adata: ad.AnnData,
    net: pd.DataFrame,
    expression_matrix: Any,
) -> tuple[ad.AnnData, pd.DataFrame]:
    """Subset the resolved expression matrix to pathway targets before scoring."""
    target_names = pd.Index(net["target"].astype(str).unique())
    feature_index = pd.Index(np.asarray(adata.var_names, dtype=str))
    feature_positions = feature_index.get_indexer(target_names)
    present_mask = feature_positions >= 0

    if not present_mask.any():
        raise ValueError("No pathway target genes overlap with the dataset")

    selected_targets = target_names[present_mask]
    selected_positions = feature_positions[present_mask]
    filtered_net = net.loc[net["target"].astype(str).isin(selected_targets)].copy()
    sub = expression_matrix[:, selected_positions]
    if sp.issparse(sub) or hasattr(sub, "copy"):
        x_sub = sub.copy()
    else:
        x_sub = np.asarray(sub)
    scoring_adata = ad.AnnData(
        X=x_sub,
        obs=adata.obs.copy(),
        var=adata.var.iloc[selected_positions].copy(),
    )
    scoring_adata.obs_names = adata.obs_names.copy()
    scoring_adata.var_names = np.asarray(adata.var_names, dtype=str)[selected_positions]

    logger.info(
        "Pathway scoring will use %d target genes across %d pathways",
        int(scoring_adata.n_vars),
        int(filtered_net["source"].nunique()),
    )
    return scoring_adata, filtered_net


def _score_pathways(
    adata: ad.AnnData,
    net: pd.DataFrame,
    method: str,
    min_n: int,
    pathway_database: str,
) -> tuple[pd.DataFrame | None, str]:
    """Score pathways, using a lightweight fallback for PROGENy defaults."""
    normalized_db = str(pathway_database or "").strip().lower()
    if normalized_db == "progeny" and method in {"ulm", "mlm"}:
        return _run_weighted_linear_scoring(adata, net, min_n), f"{method}_weighted"
    if method == "wsum":
        import decoupler as dc

        if getattr(dc.mt, "wsum", None) is None:
            logger.warning(
                "Pathway scoring requested method='wsum', but decoupler.mt.wsum is unavailable "
                "in this runtime. Falling back to Zerna weighted sparse scoring."
            )
            return _run_weighted_linear_scoring(adata, net, min_n), "wsum_weighted"
    return _run_decoupler(adata, net, method, min_n), method


def _run_weighted_linear_scoring(
    adata: ad.AnnData,
    net: pd.DataFrame,
    min_n: int,
) -> pd.DataFrame:
    """Approximate PROGENy activity with sparse-safe weighted z-scored sums."""
    X = adata.X
    feature_index = pd.Index(np.asarray(adata.var_names, dtype=str))

    pathway_scores: list[np.ndarray] = []
    pathway_names: list[str] = []

    for pathway, group in net.groupby("source", sort=False):
        target_names = group["target"].astype(str).to_numpy()
        positions = feature_index.get_indexer(target_names)
        present_mask = positions >= 0
        if int(present_mask.sum()) < min_n:
            continue

        selected_positions = positions[present_mask]
        weights = group["weight"].to_numpy(dtype=np.float32)[present_mask]
        scores = _weighted_sparse_gene_score(X, selected_positions, weights, sparse=sp)
        pathway_scores.append(scores.astype(np.float32, copy=False))
        pathway_names.append(str(pathway))

    if not pathway_scores:
        return pd.DataFrame(index=adata.obs_names)

    matrix = np.column_stack(pathway_scores).astype(np.float32, copy=False)
    return pd.DataFrame(matrix, index=adata.obs_names, columns=pathway_names)


def _weighted_sparse_gene_score(
    X, positions: np.ndarray, weights: np.ndarray, *, sparse
) -> np.ndarray:
    """Compute a per-cell weighted pathway score without densifying the matrix."""
    if sparse.issparse(X):
        X_sub = X[:, positions].tocsr().astype(np.float32)
        mean = np.asarray(X_sub.mean(axis=0)).ravel()
        mean_sq = np.asarray(X_sub.power(2).mean(axis=0)).ravel()
    else:
        X_sub = np.asarray(X[:, positions], dtype=np.float32)
        mean = X_sub.mean(axis=0)
        mean_sq = np.square(X_sub).mean(axis=0)

    variance = np.maximum(mean_sq - np.square(mean), 1e-8)
    scale = np.sqrt(variance, dtype=np.float32)
    coeff = weights / scale
    offset = float(mean @ coeff)

    if sparse.issparse(X_sub):
        scores = np.asarray(X_sub @ coeff).ravel()
    else:
        scores = X_sub @ coeff

    norm = float(np.sum(np.abs(weights)))
    if norm > 0:
        scores = (scores - offset) / norm
    else:
        scores = scores - offset
    return np.asarray(scores, dtype=np.float32)


def _run_decoupler(
    adata: ad.AnnData,
    net: pd.DataFrame,
    method: str,
    min_n: int,
) -> pd.DataFrame | None:
    """Run a single decoupler method and return scores as a DataFrame.

    decoupler v2 API: methods are accessed via dc.mt.<method>(adata, net, tmin=...)
    Results are stored in adata.obsm["score_{method}"].
    """
    import decoupler as dc

    supported = {"ulm", "mlm", "aucell", "wsum", "gsva", "zscore", "ora"}
    if method not in supported:
        raise ValueError(f"Unknown decoupler method '{method}'. Supported: {sorted(supported)}")

    run_fn = getattr(dc.mt, method, None)
    if run_fn is None:
        raise ValueError(f"decoupler.mt has no method '{method}'")

    try:
        with _DECOUPLER_EXECUTION_LOCK:
            run_fn(adata, net=net, tmin=min_n, verbose=False)
    except Exception:
        return None

    # decoupler v2 stores scores in obsm["score_{method}"]
    score_key = f"score_{method}"
    if score_key in adata.obsm:
        scores = adata.obsm[score_key]
        if isinstance(scores, pd.DataFrame):
            return scores
        # Wrap numpy array with pathway column names
        pathways = net["source"].unique().tolist()
        n_cols = scores.shape[1] if scores.ndim > 1 else 1
        cols = (
            pathways[:n_cols]
            if len(pathways) >= n_cols
            else [f"pathway_{i}" for i in range(n_cols)]
        )
        return pd.DataFrame(scores, index=adata.obs_names, columns=cols)

    return None
