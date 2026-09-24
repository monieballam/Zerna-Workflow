"""Cell type annotation method using CellTypist with hierarchical enrichment."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp
import yaml
from zerna_contracts.enums import ComputePreference
from pydantic import BaseModel, Field

from methods.annotation.write_guard import preserve_annotation_columns_before_rewrite
from methods.annotation.cluster_keys import (
    detect_cluster_key,
    resolve_annotation_cluster_key,
    resolve_cluster_key,
)
from methods.annotation.cluster_marker_de import _compute_cluster_markers
from methods.annotation.conservative import (
    AnnotationBenchmarkReport,
    ConservativeThresholds,
    benchmark_predictions,
)
from methods.annotation.conservative import annotate_clusters as annotate_clusters_conservatively
from methods.annotation.guardrails import normalize_label
from methods.annotation.species import resolve_species
from methods.annotation.stromal_resolution import (
    STROMAL_MARKER_PANELS,
)
from methods.annotation.stromal_resolution import (
    resolve as resolve_stromal,
)
from methods.annotation.zerna_index import ZernaEntry
from methods.annotation.zerna_index import lookup as lookup_zerna
from methods.base import MethodDefinition

try:
    from methods.annotation.retrieval_prior import load_index_from_jsonl
except ImportError:  # pragma: no cover - optional module not yet ported
    load_index_from_jsonl = None

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]

ANNOTATION_DASHBOARD_CANONICAL_OBS: tuple[str, ...] = (
    "annotation_label",
    "final_display",
    "annotation_confidence",
    "celltypist_provenance",
)


def _effective_hierarchy_cluster_key(adata: ad.AnnData, requested: str | None) -> str:
    """Pick a cluster column for global_cluster / L3 confidence grouping."""
    if requested and requested in adata.obs.columns:
        return requested
    detected = detect_cluster_key(adata)
    if detected:
        return detected
    for cand in ("leiden", "cluster", "louvain"):
        if cand in adata.obs.columns:
            return cand
    return "leiden"


def _finalize_independent_annotation_columns(adata: ad.AnnData) -> None:
    """Copy CellTypist / marker labels into explorer display columns."""
    label_col = None
    for candidate in (
        "annotation_label",
        "celltypist_majority_voting",
        "celltypist_cell_type",
        "predicted_labels",
    ):
        if candidate in adata.obs.columns:
            label_col = candidate
            break
    if label_col is None:
        return
    labels = adata.obs[label_col].astype(str)
    adata.obs["annotation_label"] = labels
    adata.obs["final_display"] = labels
    if "celltypist_conf_score" in adata.obs.columns:
        adata.obs["annotation_confidence"] = pd.to_numeric(
            adata.obs["celltypist_conf_score"], errors="coerce"
        ).fillna(0.0)
    elif "annotation_confidence" not in adata.obs.columns:
        adata.obs["annotation_confidence"] = 0.0


DEFAULT_MARKER_PACK_PATH = (
    REPO_ROOT / "scripts" / "data" / "knowledge_packs" / "cell_type_markers_v1.json"
)
LEGACY_MARKER_PACK_DIR_CANDIDATES = (
    REPO_ROOT / "scripts" / "data" / "knowledge_packs" / "marker_packs",
)
LEGACY_TISSUE_MARKER_PACK_CANDIDATES: tuple[Path, ...] = ()
LEGACY_ZERNA_DIR_CANDIDATES: tuple[Path, ...] = ()
LEGACY_MARKER_DATABASE_FILES = {
    "legacy_zerna_taxonomy": "zerna_hierarchical_taxonomy.yaml",
    "legacy_universal_immune": "universal_immune.yaml",
    "legacy_universal_stromal": "universal_stromal.yaml",
    "legacy_universal_epithelial": "universal_epithelial.yaml",
    "legacy_universal_endothelial": "universal_endothelial.yaml",
    "legacy_universal_states": "universal_states.yaml",
    "legacy_myeloid_hgm_subtypes": "myeloid_hgm_subtypes.yaml",
    "legacy_stromal_hgm_subtypes": "stromal_hgm_subtypes.yaml",
}
LEGACY_ZERNA_MARKER_DATABASE_FILES: dict[str, str] = {}
LEGACY_ZERNA_COMPOSITE_DATABASES: dict[str, tuple[str, ...]] = {}
LEGACY_ZERNA_DEFAULT_DATABASE_BY_SPECIES: dict[str, str] = {}
LEGACY_MARKER_FIELDS = {
    "core",
    "high",
    "medium",
    "all",
    "genes",
    "include",
    "exclude",
    "tolerant_include",
    "support_genes",
    "not_genes",
    "not_genes_soft",
    "soft_exclude",
}
DEFAULT_CELLTYPIST_MODEL_BY_SPECIES = {
    "human": "Immune_All_Low.pkl",
    "mouse": "Adult_Mouse_Gut.pkl",
}
ANNOTATION_METHODS = {
    "conservative",
    "celltypist",
    "marker_pack",
    "hybrid",
}
REMOVED_ANNOTATION_METHODS = {
    "annotation_agent_v3",
    "legacy_pan_prostate",
    "legacy_pan_prostate_v2_yaml",
    "legacy_pan_prostate_v3_zerna",
    "legacy_pan_prostate_v3_zerna",
}
ANNOTATION_CONFIDENCE_SCORES = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
}


class CellTypistInput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    annotation_method: str = Field(
        default="celltypist",
        description=(
            "Annotation backend. 'celltypist' (default) uses a CellTypist reference model. "
            "'conservative' is an audit-first, abstaining cluster engine. "
            "'marker_pack' scores clusters with bundled marker YAML. "
            "'hybrid' combines CellTypist with marker-pack refinement."
        ),
    )
    model_name: str = Field(
        default="auto",
        description="CellTypist model name or path. Use `auto` to pick a species-appropriate default.",
    )
    majority_voting: bool = Field(
        default=True,
        description="Apply majority voting to smooth predictions within clusters",
    )
    cluster_key: str | None = Field(
        default=None,
        description="obs column for majority voting; auto-detected if None",
    )
    pipeline_cluster_key_hint: str | None = Field(
        default=None,
        description="Workflow-only: resolved cluster_key from the cluster step when cluster_key is unset.",
    )
    annotation_input_is_main_adata: bool = Field(
        default=True,
        description="False when the worker passes slim log-input AnnData (CellTypist/hybrid engines).",
    )
    min_prob: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence probability to keep a prediction",
    )
    knowledge_pack_version: str | None = Field(
        default=None,
        description="KnowledgePack version used for provenance tracking",
    )
    marker_pack: dict[str, Any] | None = Field(
        default=None,
        description="Optional inline marker pack for cluster-level scoring",
    )
    marker_pack_path: str | None = Field(
        default=None,
        description="Optional JSON marker pack path for cluster-level scoring",
    )
    marker_database: str = Field(
        default="zerna_default",
        description=(
            "Marker database to use for marker-pack or hybrid annotation. "
            "'zerna_default' loads the bundled Zerna marker knowledge pack; the legacy_* options "
            "use bundled marker YAML shipped in this repository; "
            "'custom' uses annotation_marker_pack_path."
        ),
    )
    cluster_prior_path: str | None = Field(
        default=None,
        description="Optional JSONL retrieval prior index for similar-cluster evidence",
    )
    tissue_context: str = Field(
        default="",
        description="Optional tissue context used for retrieval priors",
    )
    cancer_type: str | None = Field(
        default=None,
        description="Optional cancer context used for retrieval priors",
    )
    species: str = Field(
        default="auto",
        description="Species context used for marker-pack scoring and retrieval priors",
    )
    cluster_marker_top_n: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Number of top marker genes to compute per cluster",
    )
    min_marker_overlap: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Minimum marker overlap required for marker-pack scoring",
    )
    cluster_markers_export_path: str | None = Field(
        default=None,
        description="Optional CSV export path for per-cluster marker genes",
    )
    benchmark_reference_key: str | None = Field(
        default=None,
        description="Optional obs column used to benchmark final annotation calls.",
    )


class CellTypistMetrics(BaseModel):
    n_cells_annotated: int
    n_cell_types_predicted: int
    mean_confidence: float
    model_used: str
    annotation_method_used: str
    knowledge_pack_version: str | None
    n_harmonized_labels: int = 0
    n_unknown_labels: int = 0
    n_stromal_resolved: int = 0
    n_clusters_annotated: int = 0
    n_clusters_abstained: int = 0
    n_lineage_only_clusters: int = 0
    cluster_annotation_mode: str = "celltypist_consensus"
    retrieval_prior_used: bool = False
    benchmark_reference_key: str | None = None
    benchmark_coverage: float | None = None
    benchmark_accuracy_on_covered: float | None = None
    benchmark_lineage_consistent_accuracy: float | None = None
    benchmark_macro_f1: float | None = None
    annotation_method_requested: str | None = None
    cluster_key_resolved: str | None = None
    clustering_method_detected: str | None = None
    expression_source_used: str | None = None
    log_normalization_applied: bool | None = None
    annotation_input_is_main_adata: bool | None = None


class CellTypistOutput(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    adata: ad.AnnData
    metrics: CellTypistMetrics


def _detect_cluster_key(adata: ad.AnnData) -> str | None:
    """Auto-detect a cluster column in obs."""
    return resolve_cluster_key(adata, None)


def _resolve_annotation_method(method_name: str | None) -> str:
    """Normalize and validate the requested annotation backend."""
    normalized = str(method_name or "celltypist").strip().lower()
    if normalized in REMOVED_ANNOTATION_METHODS:
        return "celltypist"
    if normalized not in ANNOTATION_METHODS:
        raise ValueError(
            "Unsupported annotation method "
            f"'{method_name}'. Expected one of: {', '.join(sorted(ANNOTATION_METHODS))}."
        )
    return normalized


def _normalize_legacy_annotation_inputs(
    input: CellTypistInput, annotation_method: str
) -> CellTypistInput:
    """Compatibility hook. Removed engines are remapped before this runs."""
    return input


def _default_marker_pack_path() -> str | None:
    """Return the bundled Zerna marker pack path when available."""
    return _resolve_marker_database_path("zerna_default")


def _resolve_marker_database_path(marker_database: str | None) -> str | None:
    """Resolve a bundled or legacy marker-database identifier to a file path."""
    normalized_database = str(marker_database or "zerna_default").strip().lower()
    if normalized_database == "zerna_default":
        if DEFAULT_MARKER_PACK_PATH.is_file():
            return str(DEFAULT_MARKER_PACK_PATH)
        return None

    file_name = LEGACY_MARKER_DATABASE_FILES.get(normalized_database)
    if file_name:
        for directory in LEGACY_MARKER_PACK_DIR_CANDIDATES:
            candidate = directory / file_name
            if candidate.is_file():
                return str(candidate)
        return None

    file_name = LEGACY_ZERNA_MARKER_DATABASE_FILES.get(normalized_database)
    if file_name:
        for directory in LEGACY_ZERNA_DIR_CANDIDATES:
            candidate = directory / file_name
            if candidate.is_file():
                return str(candidate)
    return None


def _dedupe_genes(genes: list[str]) -> list[str]:
    """Preserve marker order while removing duplicates."""
    return list(dict.fromkeys(str(gene).strip().upper() for gene in genes if str(gene).strip()))


def _merge_normalized_marker_packs(
    packs: list[dict[str, dict[str, list[str]]]],
) -> dict[str, dict[str, list[str]]]:
    """Merge normalized marker packs using the legacy tissue > universal/HGM priority."""
    merged: dict[str, dict[str, list[str]]] = {}
    for pack in packs:
        for label, tier_map in pack.items():
            destination = merged.setdefault(str(label), {})
            for tier, genes in tier_map.items():
                destination[tier] = _dedupe_genes([*genes, *destination.get(tier, [])])
    return merged


def _resolve_legacy_merged_marker_pack(
    marker_database: str | None,
) -> dict[str, dict[str, list[str]]] | None:
    """Load merged bundled marker packs when requested."""
    normalized_database = str(marker_database or "").strip().lower()
    if normalized_database not in {"legacy_zerna_taxonomy"}:
        return None

    ordered_paths: list[str] = []
    for database_name in (
        "legacy_zerna_taxonomy",
        "legacy_universal_immune",
        "legacy_universal_stromal",
        "legacy_universal_endothelial",
        "legacy_universal_epithelial",
        "legacy_universal_states",
        "legacy_myeloid_hgm_subtypes",
        "legacy_stromal_hgm_subtypes",
    ):
        resolved = _resolve_marker_database_path(database_name)
        if resolved:
            ordered_paths.append(resolved)

    if not ordered_paths:
        return None

    merged_packs: list[dict[str, dict[str, list[str]]]] = []
    for pack_path in ordered_paths:
        normalized_pack = _load_marker_pack(None, pack_path)
        if normalized_pack:
            merged_packs.append(normalized_pack)

    return _merge_normalized_marker_packs(merged_packs) if merged_packs else None


def _merge_marker_tiers(
    destination: dict[str, dict[str, list[str]]],
    label: str,
    tiers: dict[str, list[str]],
) -> None:
    """Merge normalized marker tiers into a destination pack."""
    cleaned_label = _humanize_marker_label(str(label))
    label_entry = destination.setdefault(cleaned_label, {})
    for tier, genes in tiers.items():
        if not genes:
            continue
        label_entry[tier] = _dedupe_genes([*label_entry.get(tier, []), *genes])


def _extract_legacy_zerna_marker_pack(
    raw_pack: Any,
    *,
    tissue_context: str = "",
) -> dict[str, dict[str, list[str]]] | None:
    """Normalize old Zerna JSON marker resources into the rebuilt marker-pack format."""
    if not isinstance(raw_pack, dict) or not raw_pack:
        return None

    normalized: dict[str, dict[str, list[str]]] = {}

    normalized_tissue = str(tissue_context or "").strip().lower()
    if normalized_tissue:
        tissue_matches = [
            key
            for key in raw_pack
            if normalized_tissue in str(key).strip().lower()
            or str(key).strip().lower() in normalized_tissue
        ]
        if tissue_matches and all(isinstance(raw_pack[key], dict) for key in tissue_matches):
            raw_pack = {key: raw_pack[key] for key in tissue_matches}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            return
        if not isinstance(node, dict):
            return

        for label, payload in node.items():
            if isinstance(payload, list):
                _merge_marker_tiers(
                    normalized,
                    str(label),
                    {"all": _normalize_gene_list(payload)},
                )
                continue

            if not isinstance(payload, dict):
                continue

            if _is_legacy_marker_definition(payload):
                _merge_marker_tiers(normalized, str(label), _normalize_marker_tiers(payload))
                continue

            grouped_gene_fields = {
                key: _coerce_gene_list(payload.get(key, []))
                for key in ("markers", "primary_markers", "secondary_markers")
                if key in payload
            }
            if grouped_gene_fields:
                grouped_genes: list[Any] = []
                for genes in grouped_gene_fields.values():
                    grouped_genes.extend(genes)
                _merge_marker_tiers(
                    normalized,
                    str(label),
                    {"all": _normalize_gene_list(grouped_genes)},
                )
                continue

            visit(payload)

    visit(raw_pack)
    return normalized or None


def _resolve_legacy_zerna_marker_pack(
    marker_database: str | None,
    *,
    tissue_context: str = "",
) -> dict[str, dict[str, list[str]]] | None:
    """Resolve old Zerna JSON marker resources, including merged pan-prostate packs."""
    normalized_database = str(marker_database or "").strip().lower()
    component_databases = LEGACY_ZERNA_COMPOSITE_DATABASES.get(normalized_database)
    if component_databases:
        merged_packs: list[dict[str, dict[str, list[str]]]] = []
        for component in component_databases:
            pack = _resolve_legacy_zerna_marker_pack(
                component,
                tissue_context=tissue_context,
            )
            if pack:
                merged_packs.append(pack)
        return _merge_normalized_marker_packs(merged_packs) if merged_packs else None

    pack_path = _resolve_marker_database_path(normalized_database)
    if not pack_path:
        return None

    raw_pack = _load_raw_marker_pack(pack_path)
    return _extract_legacy_zerna_marker_pack(
        raw_pack,
        tissue_context=tissue_context,
    )


def _resolve_marker_pack_inputs(
    input: CellTypistInput,
    *,
    annotation_method: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve inline/path marker-pack inputs, defaulting to the bundled Zerna pack."""
    if input.marker_pack is not None or input.marker_pack_path:
        return input.marker_pack, input.marker_pack_path

    normalized_database = str(input.marker_database or "zerna_default").strip().lower()
    merged_legacy_pack = _resolve_legacy_merged_marker_pack(normalized_database)
    if merged_legacy_pack is not None:
        return merged_legacy_pack, None

    if (
        annotation_method in {"conservative", "marker_pack", "hybrid"}
        and normalized_database != "custom"
    ):
        zerna_pack = _resolve_legacy_zerna_marker_pack(
            normalized_database,
            tissue_context=input.tissue_context,
        )
        if zerna_pack is not None:
            return zerna_pack, None

        resolved_path = _resolve_marker_database_path(normalized_database)
        if not resolved_path:
            raise ValueError(
                f"Marker database '{input.marker_database}' is not available in this environment"
            )
        return None, resolved_path
    return None, None


def _confidence_bucket_to_score(bucket: str) -> float:
    """Map legacy confidence buckets to stable numeric scores."""
    return float(ANNOTATION_CONFIDENCE_SCORES.get(str(bucket).strip().lower(), 0.3))


def _build_probability_frame(
    adata: ad.AnnData,
    labels: np.ndarray,
    conf_scores: np.ndarray,
) -> pd.DataFrame:
    """Construct a lightweight probability matrix for non-CellTypist backends."""
    unique_labels = sorted({str(label) for label in labels})
    if not unique_labels:
        return pd.DataFrame(index=adata.obs_names)

    prob_matrix = np.zeros((adata.n_obs, len(unique_labels)), dtype=np.float32)
    label_to_index = {label: idx for idx, label in enumerate(unique_labels)}
    for row_idx, label in enumerate(labels):
        prob_matrix[row_idx, label_to_index[str(label)]] = float(conf_scores[row_idx])
    return pd.DataFrame(prob_matrix, index=adata.obs_names, columns=unique_labels)


def _build_marker_pack_predictions(
    adata: ad.AnnData,
    *,
    cluster_key: str,
    input: CellTypistInput,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, dict[str, Any]]:
    """Derive per-cell labels from cluster-level Zerna marker-pack scoring."""
    placeholder_annotations = [
        build_hierarchical_annotation("Unknown", tissue=tissue, confidence=0.0)
        for tissue in _derive_tissue_values(adata)
    ]
    cluster_meta = _populate_legacy_cluster_outputs(
        adata=adata,
        cluster_key=cluster_key,
        annotations=placeholder_annotations,
        input=input,
    )
    labels = adata.obs["annotation_label"].astype(str).to_numpy(dtype=object)
    confidence_buckets = adata.obs["annotation_confidence"].astype(str).to_numpy(dtype=object)
    conf_scores = np.asarray(
        [_confidence_bucket_to_score(bucket) for bucket in confidence_buckets],
        dtype=np.float32,
    )
    probability_matrix = _build_probability_frame(adata, labels, conf_scores)
    return labels, conf_scores, probability_matrix, cluster_meta


def _resolve_celltypist_model(model_name: str):
    """Load the requested CellTypist model without triggering a full catalog bootstrap."""
    with _suspended_celltypist_auto_download() as celltypist_models:
        requested_model = str(model_name or "").strip() or celltypist_models.get_default_model()
        if Path(requested_model).is_file():
            logger.info("Using CellTypist model from local path %s", requested_model)
            return celltypist_models.Model.load(requested_model)

        cached_model_path = Path(celltypist_models.get_model_path(requested_model))
        if not cached_model_path.is_file():
            logger.info(
                "CellTypist model %s is not cached; downloading the requested model only",
                requested_model,
            )
            celltypist_models.download_models(model=requested_model)
        else:
            logger.info("Using cached CellTypist model %s", requested_model)

        if not cached_model_path.is_file():
            raise FileNotFoundError(
                f"Requested CellTypist model was not downloaded: {cached_model_path}"
            )

        return celltypist_models.Model.load(str(cached_model_path))


def _resolve_celltypist_feature_alignment(
    adata: ad.AnnData,
    model,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (adata indices, model indices) for overlapping model features."""
    adata_genes = np.asarray(adata.var_names, dtype=str)
    model_features = np.asarray(model.classifier.features, dtype=str)

    adata_index = pd.Index(adata_genes)
    direct_match = adata_index.get_indexer(model_features)
    direct_mask = direct_match >= 0

    if direct_mask.any():
        return direct_match[direct_mask].astype(np.int64), np.where(direct_mask)[0].astype(np.int64)

    adata_upper = np.char.upper(adata_genes)
    model_upper = np.char.upper(model_features)
    upper_index = pd.Index(adata_upper)
    upper_match = upper_index.get_indexer(model_upper)
    upper_mask = upper_match >= 0
    if upper_mask.any():
        logger.warning(
            "Case-sensitive overlap only %d, but case-insensitive overlap is %d. Converting var_names to uppercase to match model.",
            int(direct_mask.sum()),
            int(upper_mask.sum()),
        )
        adata.var_names = adata_upper
        adata.var_names_make_unique()
        adata_index = pd.Index(np.asarray(adata.var_names, dtype=str))
        refreshed_match = adata_index.get_indexer(model_upper[upper_mask])
        return refreshed_match.astype(np.int64), np.where(upper_mask)[0].astype(np.int64)

    raise ValueError("No features overlap with the selected CellTypist model")


def _scale_celltypist_chunk(
    matrix: np.ndarray | sp.spmatrix,
    *,
    means: np.ndarray | int,
    scales: np.ndarray,
    with_mean: bool,
) -> np.ndarray | sp.csr_matrix:
    """Scale one CellTypist chunk without materializing the entire dataset."""
    safe_scales = np.where(scales == 0, 1.0, scales).astype(np.float32, copy=False)

    if sp.issparse(matrix):
        chunk = matrix.tocsr(copy=True).astype(np.float32)
        if with_mean:
            dense = chunk.toarray()
            dense -= np.asarray(means, dtype=np.float32)
            dense /= safe_scales
            np.minimum(dense, 10.0, out=dense)
            return dense

        chunk = chunk.multiply((1.0 / safe_scales).astype(np.float32, copy=False))
        if chunk.nnz:
            np.minimum(chunk.data, 10.0, out=chunk.data)
        return chunk

    dense = np.asarray(matrix, dtype=np.float32, order="C")
    if with_mean:
        dense -= np.asarray(means, dtype=np.float32)
    dense /= safe_scales
    np.minimum(dense, 10.0, out=dense)
    return dense


def _apply_majority_voting(
    predicted_labels: pd.DataFrame,
    cluster_labels: pd.Series,
    *,
    min_prop: float = 0.0,
) -> np.ndarray:
    """Reproduce CellTypist majority voting without keeping full decision matrices."""
    cluster_series = cluster_labels.astype(str)
    votes = pd.crosstab(predicted_labels["predicted_labels"], cluster_series)
    majority = votes.idxmax(axis=0).astype(str)
    freqs = (votes / votes.sum(axis=0).values).max(axis=0)
    majority[freqs < min_prop] = "Heterogeneous"
    resolved = cluster_series.map(majority).fillna("Unknown")
    predicted_labels["over_clustering"] = cluster_series.values
    predicted_labels["majority_voting"] = pd.Categorical(resolved.values)
    return resolved.to_numpy(dtype=object)


def _predict_celltypist_in_chunks(
    adata: ad.AnnData,
    model,
    *,
    cluster_key: str | None,
    majority_voting: bool,
    chunk_size: int = 2048,
):
    """Run CellTypist prediction in chunks to avoid large dense allocations."""
    data_feature_indices, model_feature_indices = _resolve_celltypist_feature_alignment(
        adata, model
    )
    n_features = int(model_feature_indices.size)
    logger.info("CellTypist will use %d overlapping features for prediction", n_features)

    scaler = model.scaler
    means = scaler.mean_[model_feature_indices] if getattr(scaler, "with_mean", False) else 0
    scales = scaler.scale_[model_feature_indices]
    classifier = model.classifier

    original_n_features = classifier.n_features_in_
    original_features = classifier.features
    original_coef = classifier.coef_
    original_classes = np.asarray(classifier.classes_, dtype=str)

    classifier.n_features_in_ = n_features
    classifier.features = original_features[model_feature_indices]
    classifier.coef_ = classifier.coef_[:, model_feature_indices]

    try:
        probabilities: list[np.ndarray] = []
        predicted_labels_list: list[np.ndarray] = []
        total_chunks = max(1, (adata.n_obs + chunk_size - 1) // chunk_size)

        for chunk_idx, start in enumerate(range(0, adata.n_obs, chunk_size), start=1):
            stop = min(start + chunk_size, adata.n_obs)
            chunk_matrix = adata.X[start:stop, :]
            if sp.issparse(chunk_matrix):
                chunk_matrix = chunk_matrix[:, data_feature_indices]
            else:
                chunk_matrix = np.asarray(chunk_matrix)[:, data_feature_indices]

            scaled_chunk = _scale_celltypist_chunk(
                chunk_matrix,
                means=means,
                scales=scales,
                with_mean=bool(getattr(scaler, "with_mean", False)),
            )
            _, prob_chunk, label_chunk = model.predict_labels_and_prob(
                scaled_chunk, mode="best match"
            )
            probabilities.append(np.asarray(prob_chunk, dtype=np.float32))
            predicted_labels_list.append(np.asarray(label_chunk, dtype=object))

            logger.info(
                "CellTypist prediction chunk %d/%d completed (%d cells)",
                chunk_idx,
                total_chunks,
                stop - start,
            )
    finally:
        classifier.n_features_in_ = original_n_features
        classifier.features = original_features
        classifier.coef_ = original_coef

    probability_matrix = np.vstack(probabilities)
    predicted_values = np.concatenate(predicted_labels_list)
    predicted_labels = pd.DataFrame(
        {"predicted_labels": pd.Categorical(predicted_values)},
        index=adata.obs_names,
    )

    majority_labels = None
    if majority_voting and cluster_key is not None and cluster_key in adata.obs:
        majority_labels = _apply_majority_voting(
            predicted_labels,
            adata.obs[cluster_key],
        )

    return SimpleNamespace(
        predicted_labels=predicted_labels,
        probability_matrix=pd.DataFrame(
            probability_matrix,
            columns=original_classes,
            index=adata.obs_names,
        ),
        majority_voting=majority_labels,
    )


@contextmanager
def _suspended_celltypist_auto_download():
    """Temporarily disable CellTypist's global 'download everything' bootstrap."""
    from celltypist import models as celltypist_models

    original = getattr(celltypist_models, "download_if_required", None)
    if original is None:
        yield celltypist_models
        return

    celltypist_models.download_if_required = lambda: None
    try:
        yield celltypist_models
    finally:
        celltypist_models.download_if_required = original


def _derive_tissue_values(adata: ad.AnnData) -> list[str]:
    """Return per-cell tissue labels, falling back to ``Unknown``."""
    for candidate in ("annotation_tissue", "tissue", "organ", "site", "sample_tissue"):
        if candidate not in adata.obs.columns:
            continue
        series = adata.obs[candidate].astype(str)
        tissues: list[str] = []
        for value in series:
            cleaned = value.strip()
            tissues.append(cleaned if cleaned and cleaned.lower() != "nan" else "Unknown")
        return tissues
    return ["Unknown"] * adata.n_obs


def _infer_lineage(entry: ZernaEntry | None, canonical_label: str) -> str:
    """Infer a broad lineage label from a canonical label or ontology entry."""
    if entry is not None:
        path = entry.hierarchy_path
        if "Lymphocyte" in path:
            return "Lymphoid"
        if "Myeloid cell" in path:
            return "Myeloid"
        if "Stromal cell" in path:
            return "Stromal"
        if "Epithelial cell" in path or entry.canonical_label == "Epithelial cell":
            return "Epithelial"

    label = canonical_label.lower()
    if label == "unknown":
        return "Unknown"
    if any(token in label for token in ("t cell", "b cell", "nk cell", "plasma cell", "lymph")):
        return "Lymphoid"
    if any(
        token in label
        for token in ("monocyte", "macrophage", "dendritic", "neutrophil", "mast", "myeloid")
    ):
        return "Myeloid"
    if any(
        token in label
        for token in ("fibroblast", "stromal", "pericyte", "smooth muscle", "endothelial")
    ):
        return "Stromal"
    if "epithelial" in label:
        return "Epithelial"
    return normalize_label(canonical_label)


def _fallback_hierarchy_path(lineage: str, canonical_label: str) -> list[str]:
    """Build a minimal hierarchy path when ontology-backed lookup is unavailable."""
    if canonical_label == "Unknown":
        return ["Unknown"]
    if lineage in {"Unknown", canonical_label}:
        return [canonical_label]
    return [lineage, canonical_label]


def build_hierarchical_annotation(
    label: str,
    *,
    tissue: str | None = None,
    confidence: float | None = None,
) -> dict[str, object]:
    """Normalize a label into a hierarchy-aware per-cell annotation record."""
    raw_label = str(label).strip() or "Unknown"
    normalized = normalize_label(raw_label)
    entry = lookup_zerna(raw_label) or lookup_zerna(normalized)
    canonical_label = entry.canonical_label if entry is not None else normalized
    lineage = _infer_lineage(entry, canonical_label)
    hierarchy_path = (
        entry.hierarchy_path
        if entry is not None
        else _fallback_hierarchy_path(lineage, canonical_label)
    )
    source = "zerna_harmonized" if entry is not None else "label_normalized"

    return {
        "tissue": (tissue or "Unknown").strip() or "Unknown",
        "lineage": lineage,
        "cell_type": canonical_label,
        "ontology_id": entry.ontology_id if entry is not None else "",
        "hierarchy_path": hierarchy_path,
        "confidence": float(confidence or 0.0),
        "source": source,
    }


def _canonical_level1(lineage: str) -> str:
    """Collapse lineage labels into the old broad canonical top level."""
    if lineage in {"Lymphoid", "Myeloid"}:
        return "Immune"
    if lineage in {"Stromal", "Epithelial"}:
        return lineage
    return normalize_label(lineage)


def _canonical_level2(annotation: dict[str, object]) -> str:
    """Derive a stable middle level compatible with the legacy explorer."""
    lineage = str(annotation["lineage"])
    cell_type = str(annotation["cell_type"])
    broad = _canonical_level1(lineage)
    entry = lookup_zerna(cell_type)

    if entry is not None and len(entry.hierarchy_path) >= 2:
        leaf_path = list(entry.hierarchy_path)
        if leaf_path and leaf_path[0] in {"Hematopoietic cell", "Stromal cell"}:
            leaf_path = leaf_path[1:]
        if broad == "Immune" and len(leaf_path) >= 2:
            return normalize_label(str(leaf_path[-2]))
        if broad == "Stromal" and len(leaf_path) >= 2:
            return normalize_label(str(leaf_path[-1]))

    if lineage == "Lymphoid":
        ct_lower = cell_type.lower()
        compact = ct_lower.replace(" ", "").replace("-", "").replace("_", "")
        # Structural zr_level2 hints: map coarse Lymphoid leaves toward Immune L2 buckets that
        # normalize cleanly (NK cells, Innate lymphoid, T cells) instead of bare "Lymphoid".
        if "innatelymphoid" in compact or ct_lower.strip().startswith(
            ("ilc", "group 1 ilc", "group 2 ilc", "group 3 ilc")
        ):
            return "Innate lymphoid"
        if "natural killer t" in ct_lower or ("nkt" in compact and "innate" not in ct_lower):
            return "T cell"
        if "t cell" in ct_lower:
            return "T cell"
        if cell_type in {"B cell", "Plasma cell"}:
            return "B cell"
        if cell_type == "NK cell":
            return "NK cell"
        return "Lymphoid"
    if lineage == "Myeloid":
        return normalize_label(cell_type)
    if lineage == "Stromal":
        return normalize_label(cell_type) if cell_type != "Unknown" else "Stromal"
    if lineage == "Epithelial":
        return "Epithelial"
    return normalize_label(cell_type)


def _canonical_level3(annotation: dict[str, object]) -> str:
    """Return the leaf label for legacy canonical outputs."""
    return normalize_label(str(annotation["cell_type"]))


def _canonical_display(level1: str, level2: str, level3: str) -> str:
    """Build a compact display label without duplicate segments."""
    parts: list[str] = []
    for part in (level1, level2, level3):
        cleaned = str(part).strip()
        if cleaned and (not parts or parts[-1] != cleaned):
            parts.append(cleaned)
    return " | ".join(parts) if parts else "Unknown"


def _build_expression_map(
    adata: ad.AnnData,
    cell_indices: list[int],
    genes: list[str],
) -> dict[str, dict[str, float]]:
    """Extract a sparse-safe expression map for a small set of genes."""
    if not cell_indices:
        return {}

    index_by_gene: dict[str, int] = {}
    for idx, gene in enumerate(adata.var_names):
        index_by_gene.setdefault(str(gene).upper(), idx)
    present_genes = [gene for gene in genes if gene.upper() in index_by_gene]
    if not present_genes:
        return {}

    present_indices = [index_by_gene[gene.upper()] for gene in present_genes]
    subset = adata[cell_indices, present_indices].X
    subset = subset.toarray() if hasattr(subset, "toarray") else np.asarray(subset)

    expression_map: dict[str, dict[str, float]] = {}
    for row_idx, cell_idx in enumerate(cell_indices):
        cell_id = str(adata.obs_names[cell_idx])
        expression_map[cell_id] = {
            gene: float(subset[row_idx, col_idx]) for col_idx, gene in enumerate(present_genes)
        }
    return expression_map


def _resolve_stromal_annotations(
    adata: ad.AnnData,
    annotations: list[dict[str, object]],
) -> int:
    """Refine generic stromal labels into specific stromal subtypes."""
    candidate_indices = [
        idx for idx, ann in enumerate(annotations) if str(ann["cell_type"]).lower() == "stromal"
    ]
    if not candidate_indices:
        return 0

    marker_genes = sorted({gene for panel in STROMAL_MARKER_PANELS.values() for gene in panel})
    expression_map = _build_expression_map(adata, candidate_indices, marker_genes)
    if not expression_map:
        logger.debug("No stromal marker genes available for refinement")
        return 0

    stromal_cells = [str(adata.obs_names[idx]) for idx in candidate_indices]
    result = resolve_stromal(expression_map, stromal_cells)

    resolved = 0
    for idx in candidate_indices:
        cell_id = str(adata.obs_names[idx])
        subtype = result.subtype_labels.get(cell_id, "Stromal")
        if subtype == "Stromal":
            continue

        updated = build_hierarchical_annotation(
            subtype,
            tissue=str(annotations[idx]["tissue"]),
            confidence=max(
                float(annotations[idx]["confidence"]),
                float(result.confidence_scores.get(cell_id, 0.0)),
            ),
        )
        updated["source"] = "stromal_resolution"
        annotations[idx] = updated
        resolved += 1

    return resolved


_MARKER_WEIGHTS = {
    "core": 3.0,
    "high": 2.0,
    "medium": 1.0,
    "all": 0.5,
}
_NEGATIVE_MARKER_WEIGHTS = {
    "exclude": 2.0,
    "soft_exclude": 1.0,
}


def _normalize_gene_list(genes: list[Any]) -> list[str]:
    """Normalize marker genes to uppercase strings."""
    return [str(gene).strip().upper() for gene in genes if str(gene).strip()]


def _coerce_gene_list(value: Any) -> list[Any]:
    """Normalize YAML/JSON marker values to a list-like structure."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _humanize_marker_label(label: str) -> str:
    """Convert snake_case legacy labels into display-friendly names."""
    return " ".join(part for part in str(label).replace("_", " ").split() if part).strip()


def _is_legacy_marker_definition(payload: Any) -> bool:
    """Return whether a YAML mapping looks like a legacy marker definition."""
    return isinstance(payload, dict) and any(key in payload for key in LEGACY_MARKER_FIELDS)


def _normalize_marker_tiers(payload: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize marker definitions from JSON or legacy YAML into weighted tiers."""
    tiers = {tier: [] for tier in (*_MARKER_WEIGHTS, *_NEGATIVE_MARKER_WEIGHTS)}
    for tier in _MARKER_WEIGHTS:
        tiers[tier].extend(_normalize_gene_list(_coerce_gene_list(payload.get(tier, []))))
    for tier in _NEGATIVE_MARKER_WEIGHTS:
        tiers[tier].extend(_normalize_gene_list(_coerce_gene_list(payload.get(tier, []))))

    tiers["core"].extend(_normalize_gene_list(_coerce_gene_list(payload.get("include", []))))
    tiers["high"].extend(_normalize_gene_list(_coerce_gene_list(payload.get("genes", []))))
    tiers["medium"].extend(
        _normalize_gene_list(_coerce_gene_list(payload.get("support_genes", [])))
    )
    tiers["medium"].extend(
        _normalize_gene_list(_coerce_gene_list(payload.get("tolerant_include", [])))
    )
    tiers["exclude"].extend(_normalize_gene_list(_coerce_gene_list(payload.get("exclude", []))))
    tiers["exclude"].extend(_normalize_gene_list(_coerce_gene_list(payload.get("not_genes", []))))
    tiers["soft_exclude"].extend(
        _normalize_gene_list(_coerce_gene_list(payload.get("not_genes_soft", [])))
    )
    return {key: list(dict.fromkeys(values)) for key, values in tiers.items() if values}


def _flatten_legacy_marker_pack(raw_pack: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Flatten the nested legacy YAML marker-pack structure into label → tier mapping."""
    normalized: dict[str, dict[str, list[str]]] = {}

    def visit(node: dict[str, Any]) -> None:
        for label, payload in node.items():
            if _is_legacy_marker_definition(payload):
                tier_map = _normalize_marker_tiers(payload)
                if any(tier_map.values()):
                    normalized[_humanize_marker_label(str(label))] = tier_map
                continue
            if isinstance(payload, dict):
                visit(payload)

    visit(raw_pack)
    return normalized


def _load_raw_marker_pack(pack_path: str) -> Any:
    """Load a marker pack from JSON or YAML."""
    path = Path(pack_path)
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(handle)
        return json.load(handle)


def _normalize_label_key(label: str) -> str:
    """Normalize labels for loose prior matching."""
    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def _safe_float(value: Any) -> float | None:
    """Convert numbers to finite floats for metadata serialization."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(numeric) or np.isinf(numeric):
        return None
    return numeric


def _confidence_bucket(confidence: float) -> str:
    """Convert a numeric confidence score to a legacy-style bucket."""
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _load_marker_pack(
    inline_pack: dict[str, Any] | None,
    pack_path: str | None,
    *,
    tissue_context: str = "",
) -> dict[str, dict[str, list[str]]] | None:
    """Load a marker pack from an inline payload or a JSON/YAML file."""
    raw_pack = inline_pack
    if raw_pack is None and pack_path:
        raw_pack = _load_raw_marker_pack(pack_path)

    if not raw_pack:
        return None

    if (
        isinstance(raw_pack, dict)
        and "markers" in raw_pack
        and isinstance(raw_pack["markers"], dict)
    ):
        raw_pack = raw_pack["markers"]

    if not isinstance(raw_pack, dict):
        return None

    normalized: dict[str, dict[str, list[str]]] = {}
    for label, payload in raw_pack.items():
        if isinstance(payload, dict):
            tiers = _normalize_marker_tiers(payload)
        elif isinstance(payload, list):
            tiers = {tier: [] for tier in _MARKER_WEIGHTS}
            tiers["all"] = _normalize_gene_list(payload)
        else:
            continue

        if any(tiers.values()):
            normalized[str(label)] = tiers

    if normalized:
        return normalized

    flattened = _flatten_legacy_marker_pack(raw_pack)
    if flattened:
        return flattened

    return _extract_legacy_zerna_marker_pack(raw_pack, tissue_context=tissue_context)


def _score_cluster_with_marker_pack(
    deg_genes: list[str],
    marker_pack: dict[str, dict[str, list[str]]] | None,
    min_overlap: int,
) -> dict[str, Any] | None:
    """Score cluster DE genes against a marker pack using weighted overlap."""
    if not marker_pack or not deg_genes:
        return None

    deg_set = set(_normalize_gene_list(deg_genes))
    candidates: list[dict[str, Any]] = []
    supporting_markers: dict[str, list[str]] = {}

    for label, tier_map in marker_pack.items():
        overlap_count = 0
        weighted_score = 0.0
        support: set[str] = set()

        for tier, weight in _MARKER_WEIGHTS.items():
            tier_markers = set(_normalize_gene_list(tier_map.get(tier, [])))
            overlap = deg_set & tier_markers
            overlap_count += len(overlap)
            weighted_score += len(overlap) * weight
            support.update(overlap)

        for tier, penalty in _NEGATIVE_MARKER_WEIGHTS.items():
            tier_markers = set(_normalize_gene_list(tier_map.get(tier, [])))
            overlap = deg_set & tier_markers
            weighted_score -= len(overlap) * penalty

        if overlap_count >= min_overlap and weighted_score > 0:
            candidates.append(
                {
                    "cell_type": str(label),
                    "score": round(weighted_score, 4),
                    "n_markers": int(overlap_count),
                }
            )
            supporting_markers[str(label)] = sorted(support)

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item["score"], -item["n_markers"], item["cell_type"]))
    candidates = candidates[:5]
    best = candidates[0]
    confidence = _confidence_bucket(
        min(
            1.0,
            0.12 * float(best["n_markers"]) + 0.05 * float(best["score"]),
        )
    )

    return {
        "summary": (
            f"{best['cell_type']} "
            f"({best['n_markers']} markers, score={best['score']:.1f}, confidence={confidence})"
        ),
        "top_cell_types": candidates,
        "cancer_programs": {},
        "enriched_pathways": {},
        "confidence": confidence,
        "supporting_markers": supporting_markers,
        "mode": "marker_pack",
        "retrieval_tiebreak_applied": False,
    }


def _score_cluster_from_consensus(
    cluster_id: str,
    labels: pd.Series,
    conf_scores: pd.Series,
    cluster_markers: list[str],
) -> dict[str, Any]:
    """Build a cluster-level summary from consensus per-cell annotations."""
    label_counts = labels.astype(str).value_counts()
    total = int(label_counts.sum())
    if total == 0:
        return {
            "summary": "Unknown (no cells assigned to cluster)",
            "top_cell_types": [{"cell_type": "Unknown", "score": 0.0, "n_markers": 0}],
            "cancer_programs": {},
            "enriched_pathways": {},
            "confidence": "low",
            "supporting_markers": {"Unknown": list(cluster_markers[:10])},
            "mode": "celltypist_consensus",
            "retrieval_tiebreak_applied": False,
        }

    top_cell_types: list[dict[str, Any]] = []
    supporting_markers: dict[str, list[str]] = {}
    for label, count in label_counts.head(5).items():
        mask = labels.astype(str) == str(label)
        mean_conf = float(conf_scores.loc[mask].mean()) if mask.any() else 0.0
        fraction = count / total
        top_cell_types.append(
            {
                "cell_type": str(label),
                "score": round(fraction * mean_conf, 4),
                "n_markers": int(count),
                "cluster_fraction": round(fraction, 4),
                "mean_confidence": round(mean_conf, 4),
            }
        )
        supporting_markers[str(label)] = list(cluster_markers[:10])

    top_cell_types.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item.get("cluster_fraction", 0.0)),
            item["cell_type"],
        )
    )
    best = top_cell_types[0]
    confidence = _confidence_bucket(
        0.6 * float(best.get("cluster_fraction", 0.0))
        + 0.4 * float(best.get("mean_confidence", 0.0))
    )

    return {
        "summary": (
            f"{best['cell_type']} "
            f"({best.get('cluster_fraction', 0.0):.0%} of cluster {cluster_id}, confidence={confidence})"
        ),
        "top_cell_types": top_cell_types,
        "cancer_programs": {},
        "enriched_pathways": {},
        "confidence": confidence,
        "supporting_markers": supporting_markers,
        "mode": "celltypist_consensus",
        "retrieval_tiebreak_applied": False,
    }


def _apply_retrieval_tiebreaker(summary: dict[str, Any], prior: dict[str, float]) -> dict[str, Any]:
    """Use retrieval priors to break close ties between candidate labels."""
    if summary.get("mode") != "marker_pack":
        return summary
    top_cell_types = list(summary.get("top_cell_types", []))
    if len(top_cell_types) < 2 or not prior:
        return summary

    score_gap = abs(float(top_cell_types[0]["score"]) - float(top_cell_types[1]["score"]))
    if score_gap >= 1.0:
        return summary

    reweighted: list[dict[str, Any]] = []
    for item in top_cell_types:
        candidate = dict(item)
        boost = 0.0
        candidate_key = _normalize_label_key(candidate["cell_type"])
        for prior_label, prior_score in prior.items():
            prior_key = _normalize_label_key(prior_label)
            if (
                candidate_key == prior_key
                or candidate_key in prior_key
                or prior_key in candidate_key
            ):
                boost += 0.5 * float(prior_score)
        candidate["adjusted_score"] = round(float(candidate["score"]) + boost, 4)
        reweighted.append(candidate)

    reweighted.sort(
        key=lambda item: (
            -float(item.get("adjusted_score", item["score"])),
            -float(item["score"]),
            item["cell_type"],
        )
    )
    summary["top_cell_types"] = reweighted
    summary["retrieval_tiebreak_applied"] = True
    best = reweighted[0]
    summary["summary"] = (
        f"{best['cell_type']} "
        f"({best['n_markers']} markers, score={best['score']:.1f}, confidence={summary['confidence']})"
    )
    return summary


def _export_cluster_markers(marker_rows: list[dict[str, Any]], export_path: str) -> str:
    """Export cluster marker rows to CSV for downstream artifact handling."""
    path = Path(export_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["cluster", "gene", "score", "logfoldchange", "pval_adj"]
    table = pd.DataFrame(marker_rows, columns=columns)
    if table.empty:
        table = pd.DataFrame(columns=columns)
    table.to_csv(path, index=False)
    return str(path)


def _populate_legacy_cluster_outputs(
    adata: ad.AnnData,
    cluster_key: str | None,
    annotations: list[dict[str, object]],
    input: CellTypistInput,
) -> dict[str, Any]:
    """Populate legacy-style cluster annotations missing from the rebuilt pipeline."""
    if cluster_key is None or cluster_key not in adata.obs.columns:
        return {
            "n_clusters_annotated": 0,
            "cluster_annotation_mode": "celltypist_consensus",
            "retrieval_prior_used": False,
        }

    cluster_labels = adata.obs[cluster_key].astype(str)
    label_series = pd.Series(
        [str(annotation["cell_type"]) for annotation in annotations],
        index=adata.obs_names,
        dtype="object",
    )
    confidence_series = pd.Series(
        [float(annotation["confidence"]) for annotation in annotations],
        index=adata.obs_names,
        dtype="float64",
    )

    cluster_markers, marker_rows = _compute_cluster_markers(
        adata,
        cluster_key=cluster_key,
        top_n=input.cluster_marker_top_n,
    )
    adata.uns["cluster_markers"] = cluster_markers
    if input.cluster_markers_export_path:
        adata.uns["cluster_markers_path"] = _export_cluster_markers(
            marker_rows,
            input.cluster_markers_export_path,
        )

    marker_pack = _load_marker_pack(
        input.marker_pack,
        input.marker_pack_path,
        tissue_context=input.tissue_context,
    )
    retrieval_index = None
    retrieval_prior_used = False
    if input.cluster_prior_path and load_index_from_jsonl is not None:
        try:
            retrieval_index = load_index_from_jsonl(input.cluster_prior_path)
            retrieval_prior_used = bool(retrieval_index.profiles)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to load cluster prior index '%s': %s", input.cluster_prior_path, exc
            )

    cluster_annotations: dict[str, dict[str, Any]] = {}
    retrieval_evidence: dict[str, dict[str, Any]] = {}
    cluster_to_label: dict[str, str] = {}
    cluster_to_confidence_bucket: dict[str, str] = {}
    cluster_annotation_mode = "celltypist_consensus"

    for cluster_id in sorted(cluster_labels.unique(), key=str):
        cluster_id = str(cluster_id)
        cluster_mask = cluster_labels == cluster_id
        deg_genes = cluster_markers.get(cluster_id, [])

        summary = _score_cluster_with_marker_pack(
            deg_genes=deg_genes,
            marker_pack=marker_pack,
            min_overlap=input.min_marker_overlap,
        )
        if summary is None:
            summary = _score_cluster_from_consensus(
                cluster_id=cluster_id,
                labels=label_series.loc[cluster_mask],
                conf_scores=confidence_series.loc[cluster_mask],
                cluster_markers=deg_genes,
            )
        else:
            cluster_annotation_mode = "marker_pack"

        prior: dict[str, float] = {}
        evidence: list[dict[str, Any]] = []
        if retrieval_index is not None and deg_genes:
            prior, evidence = retrieval_index.get_prior_and_evidence(
                deg_genes,
                tissue=input.tissue_context,
                cancer=input.cancer_type or "",
            )
            summary = _apply_retrieval_tiebreaker(summary, prior)

        best_label = (
            summary["top_cell_types"][0]["cell_type"] if summary["top_cell_types"] else "Unknown"
        )
        normalized_label = normalize_label(str(best_label))
        zerna_entry = lookup_zerna(normalized_label)
        summary["normalized_label"] = normalized_label
        summary["ontology_id"] = zerna_entry.ontology_id if zerna_entry else ""
        summary["hierarchy_path"] = (
            zerna_entry.hierarchy_path if zerna_entry else [normalized_label]
        )
        summary["cluster_markers"] = list(deg_genes)

        retrieval_evidence[cluster_id] = {
            "prior": prior,
            "evidence": evidence,
        }
        cluster_annotations[cluster_id] = summary
        cluster_to_label[cluster_id] = normalized_label
        cluster_to_confidence_bucket[cluster_id] = str(summary["confidence"])

    adata.uns["zerna_cluster_annotations"] = cluster_annotations
    adata.uns["cluster_retrieval_evidence"] = retrieval_evidence
    adata.obs["annotation_label"] = (
        cluster_labels.map(cluster_to_label).fillna("Unknown").astype(str)
    )
    adata.obs["annotation_confidence"] = (
        cluster_labels.map(cluster_to_confidence_bucket).fillna("low").astype(str)
    )

    return {
        "n_clusters_annotated": int(len(cluster_annotations)),
        "cluster_annotation_mode": cluster_annotation_mode,
        "retrieval_prior_used": retrieval_prior_used,
    }


def _run_celltypist_reference_predictions(
    adata: ad.AnnData,
    *,
    effective_input: CellTypistInput,
    cluster_key: str | None,
    resolved_species: str,
    strict: bool,
) -> tuple[Any, np.ndarray, np.ndarray, str, np.ndarray | None, pd.DataFrame]:
    """Execute CellTypist and return raw labels, confidences, and probability matrix."""
    requested_model = str(effective_input.model_name or "").strip()
    if not requested_model or requested_model.lower() == "auto":
        model_used = DEFAULT_CELLTYPIST_MODEL_BY_SPECIES.get(
            resolved_species,
            DEFAULT_CELLTYPIST_MODEL_BY_SPECIES["human"],
        )
    else:
        model_used = requested_model

    try:
        model = _resolve_celltypist_model(model_used)
        predictions = _predict_celltypist_in_chunks(
            adata,
            model,
            cluster_key=cluster_key,
            majority_voting=effective_input.majority_voting and cluster_key is not None,
        )
        cell_types = np.asarray(
            predictions.predicted_labels["predicted_labels"].values,
            dtype=object,
        )
        conf_scores = predictions.probability_matrix.max(axis=1).to_numpy(dtype=np.float32)
        if effective_input.min_prob > 0.0:
            low_conf_mask = conf_scores < effective_input.min_prob
            cell_types = cell_types.copy()
            cell_types[low_conf_mask] = "Unknown"

        mv_labels = None
        if effective_input.majority_voting and cluster_key is not None:
            mv_labels = (
                predictions.majority_voting
                if predictions.majority_voting is not None
                else predictions.predicted_labels.get("majority_voting", cell_types)
            )

        return (
            predictions,
            cell_types,
            conf_scores,
            model_used,
            np.asarray(mv_labels, dtype=object) if mv_labels is not None else None,
            predictions.probability_matrix,
        )
    except Exception:
        if strict:
            raise
        logger.warning(
            "CellTypist backbone unavailable for conservative annotation; falling back to marker evidence only.",
            exc_info=True,
        )
        fallback_labels = np.asarray(["Unknown"] * adata.n_obs, dtype=object)
        fallback_scores = np.zeros(adata.n_obs, dtype=np.float32)
        probability_matrix = _build_probability_frame(adata, fallback_labels, fallback_scores)
        return None, fallback_labels, fallback_scores, model_used, None, probability_matrix


def _legacy_cluster_summary_from_conservative_call(call: dict[str, Any]) -> dict[str, Any]:
    """Project a conservative audit call into the legacy cluster-summary shape."""
    candidates = list(call.get("candidates", []))
    top_cell_types = [
        {
            "cell_type": str(
                candidate.get("normalized_label") or candidate.get("label") or "Unknown"
            ),
            "score": _safe_float(candidate.get("composite_score")) or 0.0,
            "marker_score": _safe_float(candidate.get("marker_score")) or 0.0,
            "n_markers": int(candidate.get("marker_overlap") or 0),
            "consensus_fraction": _safe_float(candidate.get("consensus_fraction")) or 0.0,
        }
        for candidate in candidates[:5]
    ]
    if not top_cell_types:
        top_cell_types = [{"cell_type": "Unknown", "score": 0.0, "n_markers": 0}]

    supporting_markers = {
        str(candidate.get("normalized_label") or candidate.get("label") or "Unknown"): list(
            candidate.get("positive_markers", [])
        )
        for candidate in candidates[:5]
    }
    final_label = str(call.get("final_label") or "Unknown")
    zerna_entry = lookup_zerna(final_label)
    return {
        "summary": (
            f"{final_label} "
            f"(status={call.get('status', 'abstained')}, confidence={call.get('confidence_bucket', 'low')})"
        ),
        "top_cell_types": top_cell_types,
        "cancer_programs": {},
        "enriched_pathways": {},
        "confidence": str(call.get("confidence_bucket", "low")),
        "supporting_markers": supporting_markers,
        "mode": "conservative",
        "status": str(call.get("status", "abstained")),
        "final_level": str(call.get("final_level", "unknown")),
        "reason": str(call.get("reason", "insufficient_support")),
        "lineage_scores": dict(call.get("lineage_scores", {})),
        "consensus_summary": dict(call.get("consensus_summary", {})),
        "prior_summary": dict(call.get("prior_summary", {})),
        "normalized_label": normalize_label(final_label),
        "ontology_id": zerna_entry.ontology_id if zerna_entry else "",
        "hierarchy_path": zerna_entry.hierarchy_path if zerna_entry else [final_label],
        "cluster_markers": list(call.get("cluster_markers", [])),
        "confidence_score": _safe_float(call.get("confidence")) or 0.0,
    }


def _apply_conservative_cluster_annotation(
    adata: ad.AnnData,
    *,
    cluster_key: str | None,
    input: CellTypistInput,
    reference_labels: np.ndarray,
    reference_confidences: np.ndarray,
    marker_pack: dict[str, dict[str, list[str]]] | None,
) -> dict[str, Any]:
    """Run conservative cluster annotation and write audit outputs to ``adata``."""
    if cluster_key is None or cluster_key not in adata.obs.columns:
        raise ValueError(
            "Conservative annotation requires an available cluster column in adata.obs"
        )
    normalized_marker_pack = _load_marker_pack(
        marker_pack,
        input.marker_pack_path,
        tissue_context=input.tissue_context,
    )

    cluster_markers, marker_rows = _compute_cluster_markers(
        adata,
        cluster_key=cluster_key,
        top_n=input.cluster_marker_top_n,
    )
    adata.uns["cluster_markers"] = cluster_markers
    if input.cluster_markers_export_path:
        adata.uns["cluster_markers_path"] = _export_cluster_markers(
            marker_rows,
            input.cluster_markers_export_path,
        )

    retrieval_index = None
    retrieval_prior_used = False
    if input.cluster_prior_path and load_index_from_jsonl is not None:
        try:
            retrieval_index = load_index_from_jsonl(input.cluster_prior_path)
            retrieval_prior_used = bool(retrieval_index.profiles)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to load cluster prior index '%s': %s",
                input.cluster_prior_path,
                exc,
            )

    cluster_series = adata.obs[cluster_key].astype(str)
    retrieval_priors: dict[str, dict[str, float]] = {}
    retrieval_evidence: dict[str, dict[str, Any]] = {}
    for cluster_id in sorted(cluster_series.unique(), key=str):
        cluster_id = str(cluster_id)
        prior: dict[str, float] = {}
        evidence: list[dict[str, Any]] = []
        deg_genes = cluster_markers.get(cluster_id, [])
        if retrieval_index is not None and deg_genes:
            prior, evidence = retrieval_index.get_prior_and_evidence(
                deg_genes,
                tissue=input.tissue_context,
                cancer=input.cancer_type or "",
            )
        retrieval_priors[cluster_id] = prior
        retrieval_evidence[cluster_id] = {"prior": prior, "evidence": evidence}

    thresholds = ConservativeThresholds(min_marker_overlap=input.min_marker_overlap)
    cluster_calls = annotate_clusters_conservatively(
        cluster_assignments={
            str(cell_id): str(cluster_id) for cell_id, cluster_id in cluster_series.items()
        },
        cluster_markers=cluster_markers,
        marker_pack=normalized_marker_pack,
        reference_labels={
            str(cell_id): str(reference_labels[idx]) for idx, cell_id in enumerate(adata.obs_names)
        },
        reference_confidences={
            str(cell_id): float(reference_confidences[idx])
            for idx, cell_id in enumerate(adata.obs_names)
        },
        retrieval_priors=retrieval_priors,
        thresholds=thresholds,
    )

    audit_payload = {cluster_id: call.model_dump() for cluster_id, call in cluster_calls.items()}
    adata.uns["conservative_annotation_audit"] = audit_payload
    adata.uns["cluster_retrieval_evidence"] = retrieval_evidence
    adata.uns["zerna_cluster_annotations"] = {
        cluster_id: _legacy_cluster_summary_from_conservative_call(call_payload)
        for cluster_id, call_payload in audit_payload.items()
    }

    cluster_to_label = {cluster_id: call.final_label for cluster_id, call in cluster_calls.items()}
    cluster_to_bucket = {
        cluster_id: call.confidence_bucket for cluster_id, call in cluster_calls.items()
    }
    cluster_to_confidence = {
        cluster_id: float(call.confidence) for cluster_id, call in cluster_calls.items()
    }
    cluster_to_status = {cluster_id: call.status for cluster_id, call in cluster_calls.items()}
    cluster_to_level = {cluster_id: call.final_level for cluster_id, call in cluster_calls.items()}
    cluster_to_reason = {cluster_id: call.reason for cluster_id, call in cluster_calls.items()}

    adata.obs["annotation_label"] = (
        cluster_series.map(cluster_to_label).fillna("Unknown").astype(str)
    )
    adata.obs["annotation_confidence"] = (
        cluster_series.map(cluster_to_bucket).fillna("low").astype(str)
    )
    adata.obs["annotation_status"] = (
        cluster_series.map(cluster_to_status).fillna("abstained").astype(str)
    )
    adata.obs["annotation_resolution"] = (
        cluster_series.map(cluster_to_level).fillna("unknown").astype(str)
    )
    adata.obs["annotation_uncertainty"] = 1.0 - cluster_series.map(cluster_to_confidence).fillna(
        0.0
    ).astype(np.float32)
    adata.obs["annotation_reason"] = (
        cluster_series.map(cluster_to_reason).fillna("insufficient_support").astype(str)
    )

    final_labels = adata.obs["annotation_label"].to_numpy(dtype=object)
    final_conf_scores = (
        cluster_series.map(cluster_to_confidence).fillna(0.0).to_numpy(dtype=np.float32)
    )
    source_by_status = {
        "accepted": "conservative_cluster_call",
        "lineage_only": "conservative_lineage_call",
        "ambiguous": "conservative_ambiguous",
        "abstained": "conservative_abstained",
    }
    final_sources = [
        source_by_status.get(
            cluster_to_status.get(str(cluster_id), "abstained"), "conservative_abstained"
        )
        for cluster_id in cluster_series
    ]
    return {
        "labels": final_labels,
        "conf_scores": final_conf_scores,
        "sources": final_sources,
        "n_clusters_annotated": int(len(cluster_calls)),
        "n_clusters_abstained": int(
            sum(call.status == "abstained" for call in cluster_calls.values())
        ),
        "n_lineage_only_clusters": int(
            sum(call.status == "lineage_only" for call in cluster_calls.values())
        ),
        "cluster_annotation_mode": "conservative",
        "retrieval_prior_used": retrieval_prior_used,
    }


def _maybe_benchmark_annotations(
    adata: ad.AnnData,
    *,
    predicted_labels: list[str],
    reference_key: str | None,
) -> AnnotationBenchmarkReport | None:
    """Benchmark final labels against a reference obs column when provided."""
    if not reference_key:
        return None
    if reference_key not in adata.obs.columns:
        logger.warning("Benchmark reference key '%s' not present in adata.obs", reference_key)
        return None

    reference_labels: dict[str, str] = {}
    for cell_id, raw_value in adata.obs[reference_key].items():
        cleaned = str(raw_value).strip()
        if not cleaned or cleaned.lower() == "nan":
            continue
        reference_labels[str(cell_id)] = cleaned

    if not reference_labels:
        return None

    report = benchmark_predictions(
        predicted_labels={
            str(cell_id): str(predicted_labels[idx]) for idx, cell_id in enumerate(adata.obs_names)
        },
        reference_labels=reference_labels,
        reference_key=reference_key,
    )
    adata.uns["annotation_benchmark"] = report.model_dump()
    return report


def _ensure_log_normalised_applied(adata: ad.AnnData) -> bool:
    """If ``adata.X`` looks like raw counts, normalize+log1p in place. Returns whether we did."""
    import scanpy as sc

    X = adata.X
    preview = X[: min(1024, adata.n_obs)]
    if sp.issparse(preview):
        preview_max = float(preview.data.max()) if preview.nnz else 0.0
    else:
        preview_max = float(np.asarray(preview).max()) if preview.size else 0.0

    if preview_max > 20:
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        return True
    return False


@contextmanager
def _annotation_expression_phase(adata: ad.AnnData):
    """Prefer ``layers['log1p']`` for scoring; restore ``adata.X`` after the block when swapped."""
    if "log1p" in getattr(adata, "layers", {}):
        orig_x = adata.X
        lyr = adata.layers["log1p"]
        adata.X = lyr.copy() if hasattr(lyr, "copy") else np.asarray(lyr)
        try:
            yield {
                "expression_source_used": "layers_log1p",
                "log_normalization_applied": False,
            }
        finally:
            adata.X = orig_x
        return
    applied = _ensure_log_normalised_applied(adata)
    yield {
        "expression_source_used": (
            "adata_X_after_normalize_total_log1p" if applied else "adata_X_presumed_log_normalized"
        ),
        "log_normalization_applied": applied,
    }


def _write_zerna_annotation_provenance(
    adata: ad.AnnData,
    *,
    annotation_method_requested: str,
    annotation_method_executed: str,
    cluster_key_meta: dict[str, Any],
    expression_meta: dict[str, Any],
    active_representation_at_annotation: str | None,
    annotation_input_is_main_adata: bool,
    warnings: list[str],
) -> None:
    adata.uns["zerna_annotation"] = {
        "annotation_method_requested": annotation_method_requested,
        "annotation_method_executed": annotation_method_executed,
        "cluster_key_requested": cluster_key_meta.get("cluster_key_requested"),
        "cluster_key_resolved": cluster_key_meta.get("cluster_key_resolved"),
        "clustering_method_detected": cluster_key_meta.get("clustering_method_detected"),
        "active_representation_at_annotation": active_representation_at_annotation,
        "expression_source_used": expression_meta.get("expression_source_used"),
        "log_normalization_applied": expression_meta.get("log_normalization_applied"),
        "annotation_input_mode": "main_adata"
        if annotation_input_is_main_adata
        else "slim_log_input",
        "engine_fallback_warnings": list(warnings),
        "annotation_dashboard_canonical_obs": list(ANNOTATION_DASHBOARD_CANONICAL_OBS),
    }


class CellTypistMethod(MethodDefinition):
    """Cell type annotation using CellTypist with hierarchical labels.

    Stores per-cell predictions and confidence scores in adata.obs with
    provenance fields (method, model, knowledge_pack_version).

    Hierarchical labels (tissue → lineage → cell_type) are stored as:
      - obs["celltypist_cell_type"]: finest-grained label
      - obs["celltypist_conf_score"]: confidence score in [0, 1]
      - obs["celltypist_majority_voting"]: majority-voted label (if enabled)
      - obs["celltypist_provenance"]: JSON string with method/model/kp_version
    """

    name = "celltypist_annotation"
    version = "1.0.0"
    compute_preference = ComputePreference.CPU_ONLY

    def input_schema(self):
        return CellTypistInput

    def output_schema(self):
        return CellTypistOutput

    def execute(self, input: CellTypistInput, compute) -> CellTypistOutput:
        adata = input.adata
        preserve_annotation_columns_before_rewrite(adata)
        api_annotation_method_requested = str(input.annotation_method)
        requested_annotation_method = _resolve_annotation_method(input.annotation_method)
        legacy_annotation_method = (
            requested_annotation_method
            if requested_annotation_method.startswith("legacy_pan_prostate")
            else None
        )
        input = _normalize_legacy_annotation_inputs(input, requested_annotation_method)
        annotation_method = _resolve_annotation_method(input.annotation_method)
        marker_pack, marker_pack_path = _resolve_marker_pack_inputs(
            input,
            annotation_method=annotation_method,
        )
        resolved_species = resolve_species(input.species, adata.var_names)
        effective_input = input.model_copy(
            update={
                "marker_pack": marker_pack,
                "marker_pack_path": marker_pack_path,
                "species": resolved_species,
            }
        )

        cluster_key, cluster_key_meta = resolve_annotation_cluster_key(
            adata,
            effective_input.cluster_key,
            pipeline_cluster_key_hint=effective_input.pipeline_cluster_key_hint,
        )

        active_rep = adata.uns.get("zerna_active_representation")
        active_rep_str = str(active_rep) if isinstance(active_rep, str) else None

        ann_warnings: list[str] = []
        if legacy_annotation_method and legacy_annotation_method != annotation_method:
            ann_warnings.append(
                f"legacy normalization remapped requested method to {annotation_method!r}."
            )

        ctx = _annotation_expression_phase(adata)
        expr_meta = ctx.__enter__()
        try:
            predictions = None
            mv_labels: np.ndarray | None = None
            model_used = ""
            probability_matrix = pd.DataFrame(index=adata.obs_names)
            cell_types = np.asarray(["Unknown"] * adata.n_obs, dtype=object)
            conf_scores = np.zeros(adata.n_obs, dtype=np.float32)
            annotation_labels = cell_types.copy()
            annotation_conf_scores = conf_scores.copy()
            annotation_sources: list[str] | None = None
            cluster_meta: dict[str, Any]
            benchmark_report: AnnotationBenchmarkReport | None = None

            if annotation_method in {"celltypist", "hybrid", "conservative"}:
                (
                    predictions,
                    cell_types,
                    conf_scores,
                    model_used,
                    mv_labels,
                    probability_matrix,
                ) = _run_celltypist_reference_predictions(
                    adata,
                    effective_input=effective_input,
                    cluster_key=cluster_key,
                    resolved_species=resolved_species,
                    strict=annotation_method in {"celltypist", "hybrid"},
                )
                adata.obs["celltypist_cell_type"] = cell_types
                adata.obs["celltypist_conf_score"] = conf_scores.astype(np.float32)
                adata.obs["celltypist_majority_voting"] = (
                    np.asarray(mv_labels, dtype=object)
                    if mv_labels is not None
                    else np.asarray(cell_types, dtype=object)
                )
                adata.obsm["celltypist_prob_matrix"] = probability_matrix.values.astype(np.float32)

                if annotation_method == "conservative":
                    if marker_pack is None and marker_pack_path is None:
                        raise ValueError(
                            "Conservative annotation requires either the bundled Zerna marker database "
                            "or an explicit marker pack path."
                        )
                    conservative_result = _apply_conservative_cluster_annotation(
                        adata,
                        cluster_key=cluster_key,
                        input=effective_input,
                        reference_labels=cell_types,
                        reference_confidences=conf_scores,
                        marker_pack=marker_pack,
                    )
                    annotation_labels = np.asarray(conservative_result["labels"], dtype=object)
                    annotation_conf_scores = np.asarray(
                        conservative_result["conf_scores"],
                        dtype=np.float32,
                    )
                    annotation_sources = list(conservative_result["sources"])
                    cluster_meta = {
                        "n_clusters_annotated": conservative_result["n_clusters_annotated"],
                        "n_clusters_abstained": conservative_result["n_clusters_abstained"],
                        "n_lineage_only_clusters": conservative_result["n_lineage_only_clusters"],
                        "cluster_annotation_mode": conservative_result["cluster_annotation_mode"],
                        "retrieval_prior_used": conservative_result["retrieval_prior_used"],
                    }
                else:
                    hierarchy_labels = (
                        np.asarray(mv_labels, dtype=object)
                        if effective_input.majority_voting
                        and cluster_key is not None
                        and mv_labels is not None
                        else np.asarray(cell_types, dtype=object)
                    )
                    annotation_labels = hierarchy_labels
                    annotation_conf_scores = np.asarray(conf_scores, dtype=np.float32)
            else:
                if cluster_key is None:
                    raise ValueError(
                        "Marker-pack annotation requires an available cluster column in adata.obs"
                    )
                if marker_pack is None and marker_pack_path is None:
                    raise ValueError(
                        "Marker-pack annotation requires either the bundled Zerna marker database "
                        "or an explicit marker pack path."
                    )
                cell_types, conf_scores, probability_matrix, cluster_meta = (
                    _build_marker_pack_predictions(
                        adata,
                        cluster_key=cluster_key,
                        input=effective_input,
                    )
                )
                model_used = "Zerna marker pack"
                adata.obs["celltypist_cell_type"] = cell_types
                adata.obs["celltypist_conf_score"] = conf_scores.astype(np.float32)
                adata.obs["celltypist_majority_voting"] = cell_types
                mv_labels = np.asarray(cell_types, dtype=object)
                probability_matrix = probability_matrix
                adata.obsm["celltypist_prob_matrix"] = probability_matrix.values.astype(np.float32)
                annotation_labels = np.asarray(cell_types, dtype=object)
                annotation_conf_scores = np.asarray(conf_scores, dtype=np.float32)

            tissue_values = _derive_tissue_values(adata)
            annotations = [
                build_hierarchical_annotation(
                    str(label),
                    tissue=tissue_values[idx],
                    confidence=float(annotation_conf_scores[idx]),
                )
                for idx, label in enumerate(annotation_labels)
            ]
            if annotation_sources is not None:
                for idx, source in enumerate(annotation_sources):
                    annotations[idx]["source"] = str(source)

            if annotation_method == "conservative":
                n_stromal_resolved = 0
            else:
                n_stromal_resolved = _resolve_stromal_annotations(adata, annotations)

            adata.obs["annotation_tissue"] = [str(ann["tissue"]) for ann in annotations]
            adata.obs["annotation_lineage"] = [str(ann["lineage"]) for ann in annotations]
            adata.obs["annotation_broad"] = [str(ann["lineage"]) for ann in annotations]
            adata.obs["annotation_cell_type"] = [str(ann["cell_type"]) for ann in annotations]
            adata.obs["annotation_ontology_id"] = [str(ann["ontology_id"]) for ann in annotations]
            adata.obs["annotation_hierarchy_path"] = [
                json.dumps(ann["hierarchy_path"]) for ann in annotations
            ]
            adata.obs["annotation_confidence"] = np.asarray(
                [float(ann["confidence"]) for ann in annotations],
                dtype=np.float32,
            )
            adata.obs["annotation_source"] = [str(ann["source"]) for ann in annotations]

            adata.obs["annotation_label"] = [str(ann["cell_type"]) for ann in annotations]
            if "annotation_confidence" not in adata.obs.columns:
                _ab_conf = pd.to_numeric(
                    pd.Series(
                        [float(ann["confidence"]) for ann in annotations],
                        index=adata.obs.index,
                    ),
                    errors="coerce",
                ).fillna(0.0)
                adata.obs["annotation_confidence"] = np.where(
                    _ab_conf >= 0.65,
                    "high",
                    np.where(_ab_conf >= 0.35, "medium", "low"),
                ).astype(object)

            canonical_level1 = [_canonical_level1(str(ann["lineage"])) for ann in annotations]
            canonical_level2 = [_canonical_level2(ann) for ann in annotations]
            canonical_level3 = [_canonical_level3(ann) for ann in annotations]
            canonical_display = [
                _canonical_display(level1, level2, level3)
                for level1, level2, level3 in zip(
                    canonical_level1,
                    canonical_level2,
                    canonical_level3,
                    strict=False,
                )
            ]

            adata.obs["celltype_level1"] = canonical_level1
            adata.obs["celltype_level2"] = canonical_level2
            adata.obs["celltype_level3"] = canonical_level3
            adata.obs["celltype_display"] = canonical_display
            adata.obs["zr_level1"] = canonical_level1
            adata.obs["zr_level2"] = canonical_level2
            adata.obs["zr_level3"] = canonical_level3
            adata.obs["zr_display"] = canonical_display

            if annotation_method == "marker_pack":
                cluster_meta = {
                    "n_clusters_annotated": int(
                        len(adata.uns.get("zerna_cluster_annotations", {}) or {})
                    ),
                    "n_clusters_abstained": 0,
                    "n_lineage_only_clusters": 0,
                    "cluster_annotation_mode": "marker_pack",
                    "retrieval_prior_used": bool(
                        any(
                            (adata.uns.get("cluster_retrieval_evidence", {}) or {})
                            .get(cluster_id, {})
                            .get("prior")
                            for cluster_id in (
                                adata.uns.get("cluster_retrieval_evidence", {}) or {}
                            )
                        )
                    ),
                }
            elif annotation_method != "conservative":
                cluster_meta = _populate_legacy_cluster_outputs(
                    adata=adata,
                    cluster_key=cluster_key,
                    annotations=annotations,
                    input=effective_input,
                )
                cluster_meta.setdefault("n_clusters_abstained", 0)
                cluster_meta.setdefault("n_lineage_only_clusters", 0)
                if (
                    annotation_method == "hybrid"
                    and cluster_meta["cluster_annotation_mode"] == "marker_pack"
                ):
                    cluster_meta["cluster_annotation_mode"] = "hybrid_marker_pack"

            benchmark_report = _maybe_benchmark_annotations(
                adata,
                predicted_labels=[str(ann["cell_type"]) for ann in annotations],
                reference_key=effective_input.benchmark_reference_key,
            )

            # Store provenance as a JSON string per cell (same value for all cells in this run)
            provenance = json.dumps(
                {
                    "method": self.name,
                    "version": self.version,
                    "annotation_method": legacy_annotation_method or annotation_method,
                    "model": model_used,
                    "marker_database": effective_input.marker_database,
                    "knowledge_pack_version": effective_input.knowledge_pack_version,
                    "hierarchical_output": True,
                    "decision_engine": (
                        "conservative_cluster_audit"
                        if annotation_method == "conservative"
                        else "legacy"
                    ),
                }
            )
            adata.obs["celltypist_provenance"] = provenance

            _finalize_independent_annotation_columns(adata)

            unique_types = np.unique(annotation_labels)
            harmonized_labels = [str(ann["cell_type"]) for ann in annotations]
            metrics = CellTypistMetrics(
                n_cells_annotated=int(adata.n_obs),
                n_cell_types_predicted=int(len(unique_types)),
                mean_confidence=float(np.mean(annotation_conf_scores)),
                model_used=model_used,
                annotation_method_used=legacy_annotation_method or annotation_method,
                knowledge_pack_version=effective_input.knowledge_pack_version,
                n_harmonized_labels=int(
                    sum(
                        normalize_label(str(raw_label)) != harmonized_labels[idx]
                        for idx, raw_label in enumerate(annotation_labels)
                    )
                ),
                n_unknown_labels=int(sum(label == "Unknown" for label in harmonized_labels)),
                n_stromal_resolved=n_stromal_resolved,
                n_clusters_annotated=cluster_meta["n_clusters_annotated"],
                n_clusters_abstained=cluster_meta["n_clusters_abstained"],
                n_lineage_only_clusters=cluster_meta["n_lineage_only_clusters"],
                cluster_annotation_mode=cluster_meta["cluster_annotation_mode"],
                retrieval_prior_used=cluster_meta["retrieval_prior_used"],
                benchmark_reference_key=(
                    benchmark_report.reference_key if benchmark_report is not None else None
                ),
                benchmark_coverage=(
                    float(benchmark_report.coverage) if benchmark_report is not None else None
                ),
                benchmark_accuracy_on_covered=(
                    float(benchmark_report.accuracy_on_covered)
                    if benchmark_report is not None
                    else None
                ),
                benchmark_lineage_consistent_accuracy=(
                    float(benchmark_report.lineage_consistent_accuracy)
                    if benchmark_report is not None
                    else None
                ),
                benchmark_macro_f1=(
                    float(benchmark_report.macro_f1) if benchmark_report is not None else None
                ),
                annotation_method_requested=api_annotation_method_requested,
                cluster_key_resolved=cluster_key,
                clustering_method_detected=cluster_key_meta.get("clustering_method_detected"),
                expression_source_used=expr_meta.get("expression_source_used"),
                log_normalization_applied=expr_meta.get("log_normalization_applied"),
                annotation_input_is_main_adata=effective_input.annotation_input_is_main_adata,
            )

            _write_zerna_annotation_provenance(
                adata,
                annotation_method_requested=api_annotation_method_requested,
                annotation_method_executed=str(legacy_annotation_method or annotation_method),
                cluster_key_meta=cluster_key_meta,
                expression_meta=expr_meta,
                active_representation_at_annotation=active_rep_str,
                annotation_input_is_main_adata=effective_input.annotation_input_is_main_adata,
                warnings=ann_warnings,
            )

            return CellTypistOutput(adata=adata, metrics=metrics)
        finally:
            ctx.__exit__(None, None, None)
