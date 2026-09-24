"""Build post-run explorer payloads from persisted H5AD artifacts."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import anndata as ad
import numpy as np
import pandas as pd
from zerna_contracts.enums import ArtifactType, RunStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.pipeline import Artifact, Run
from apps.api.services.s3_service import S3Service
from methods.annotation.hierarchy_columns import (
    AUTO_LEVEL1_COL,
    AUTO_LEVEL2_COL,
    AUTO_LEVEL3_COL,
    EXPLORER_PARTITION_INSPECTOR_UNS_KEY,
    FINAL_DISPLAY_COL,
    GLOBAL_CLUSTER_COL,
    OBSM_UMAP_FINE_B_CELLS,
    OBSM_UMAP_FINE_FIBROBLASTS,
    OBSM_UMAP_FINE_MYELOID,
    OBSM_UMAP_FINE_SMOOTH_MUSCLE,
    OBSM_UMAP_FINE_T_CELLS,
    level3_non_informative,
    normalize_level1,
    normalize_level2,
    normalize_level3,
)
from methods.annotation.label_contract import FINAL_LEVEL3_COL
from methods.annotation.explorer_annotation_evidence import (
    normalize_top_cell_types_entry,
    pick_support_markers_for_display_headline,
)


def _explorer_normalized_level1(obs: pd.DataFrame) -> pd.Series:
    """Normalized auto_level1 per row without row-wise DataFrame.apply overhead."""
    if AUTO_LEVEL1_COL not in obs.columns:
        return pd.Series([""] * len(obs), index=obs.index, dtype=object)
    values = [normalize_level1(value) for value in obs[AUTO_LEVEL1_COL].tolist()]
    return pd.Series(values, index=obs.index, dtype=object)


def _explorer_normalized_level2(obs: pd.DataFrame) -> pd.Series:
    """Match P3 subsetting: normalized auto_level2 per row without DataFrame.apply(axis=1)."""
    if AUTO_LEVEL1_COL not in obs.columns or AUTO_LEVEL2_COL not in obs.columns:
        return pd.Series([""] * len(obs), index=obs.index, dtype=object)
    l1_series = _explorer_normalized_level1(obs)
    values = [
        normalize_level2(l1, raw)
        for l1, raw in zip(l1_series.tolist(), obs[AUTO_LEVEL2_COL].tolist())
    ]
    return pd.Series(values, index=obs.index, dtype=object)


def _artifact_has_modern_canonical_hierarchy(obs: pd.DataFrame) -> bool:
    """True when the artifact carries Zerna auto hierarchy columns (strict explorer L3 contract)."""
    return (
        AUTO_LEVEL1_COL in obs.columns
        and AUTO_LEVEL2_COL in obs.columns
        and AUTO_LEVEL3_COL in obs.columns
    )


def _structural_level3_modern_cell(obs: pd.DataFrame, idx: Any, l2n: str) -> str | None:
    """
    Canonical structural L3 for modern artifacts: ``auto_level3`` then ``level3_final_safe``,
    both passed through :func:`normalize_level3` for the row's normalized L2.
    No ``final_display`` parsing, zr/celltype, or raw ``annotation_label``.
    """
    l2 = (l2n or "").strip()
    if not l2:
        return None
    if AUTO_LEVEL3_COL in obs.columns:
        a3 = _clean_obs_text(obs.at[idx, AUTO_LEVEL3_COL])
        if a3 is not None:
            n = normalize_level3(l2, a3)
            if n and not level3_non_informative(n):
                return n
    if FINAL_LEVEL3_COL in obs.columns:
        fb = _clean_obs_text(obs.at[idx, FINAL_LEVEL3_COL])
        if fb:
            n2 = normalize_level3(l2, fb)
            if n2 and not level3_non_informative(n2):
                return n2
    return None


def _structural_level3_modern_series(obs: pd.DataFrame) -> pd.Series:
    l2_series = _explorer_normalized_level2(obs)
    values: list[str | None] = []
    for idx in obs.index:
        l2n = str(l2_series.loc[idx] or "").strip()
        values.append(_structural_level3_modern_cell(obs, idx, l2n))
    return pd.Series(values, index=obs.index, dtype=object)


def _derived_level3_series_legacy(obs: pd.DataFrame) -> pd.Series:
    """
    Pre-auto-hierarchy artifacts: prefer normalized auto columns when present, then
    ``level3_final_safe``, ``final_display`` terminal segment, zr/celltype, ``annotation_label``.
    """
    l2_series = (
        _explorer_normalized_level2(obs)
        if AUTO_LEVEL1_COL in obs.columns and AUTO_LEVEL2_COL in obs.columns
        else pd.Series([""] * len(obs), index=obs.index, dtype=object)
    )
    values: list[str | None] = []
    for idx in obs.index:
        lineage = (
            _clean_obs_text(obs.at[idx, AUTO_LEVEL1_COL])
            if AUTO_LEVEL1_COL in obs.columns
            else None
        )
        level2 = (
            _clean_obs_text(obs.at[idx, AUTO_LEVEL2_COL])
            if AUTO_LEVEL2_COL in obs.columns
            else None
        )
        l2n = str(l2_series.loc[idx] or "").strip()
        candidates: list[str | None] = []
        if AUTO_LEVEL3_COL in obs.columns:
            a3 = _clean_obs_text(obs.at[idx, AUTO_LEVEL3_COL])
            if a3 and l2n:
                candidates.append(normalize_level3(l2n, a3) or None)
            elif a3:
                candidates.append(a3)
        if FINAL_LEVEL3_COL in obs.columns:
            fb = _clean_obs_text(obs.at[idx, FINAL_LEVEL3_COL])
            if fb and l2n:
                candidates.append(normalize_level3(l2n, fb) or None)
            elif fb:
                candidates.append(fb)
        fd = (
            _extract_level3_from_final_display(obs.at[idx, FINAL_DISPLAY_COL])
            if FINAL_DISPLAY_COL in obs.columns
            else None
        )
        if fd:
            candidates.append(fd)
        if "celltype_level3" in obs.columns:
            candidates.append(_clean_obs_text(obs.at[idx, "celltype_level3"]))
        if "zr_level3" in obs.columns:
            candidates.append(_clean_obs_text(obs.at[idx, "zr_level3"]))
        candidates.append(
            _clean_obs_text(obs.at[idx, "annotation_label"])
            if "annotation_label" in obs.columns
            else None
        )

        coarse_fallback: str | None = None
        chosen: str | None = None
        for candidate in candidates:
            if not candidate:
                continue
            if level3_non_informative(candidate):
                continue
            normalized = candidate.casefold()
            if level2 and normalized == level2.casefold():
                coarse_fallback = coarse_fallback or candidate
                continue
            if lineage and normalized == lineage.casefold():
                coarse_fallback = coarse_fallback or candidate
                continue
            chosen = candidate
            break
        values.append(chosen or coarse_fallback)
    return pd.Series(values, index=obs.index, dtype=object)


def _cohort_categorical_fields_omitted_from_filter_values(obs: pd.DataFrame) -> frozenset[str]:
    """
    Fields excluded from ``filter_values`` (no multi-value cohort chips).

    Structural ``level3`` (normalized auto_level3 / level3_final_safe) is exposed for
    canonical modern artifacts only — never derived from rawAnnotationLabel / legacy fallbacks
    for filter bucketing (see :func:`_derived_level3_series`).
    """
    if _artifact_has_modern_canonical_hierarchy(obs):
        return frozenset()
    return frozenset({"level3"})


# Primary cohort filters: broad lineage + study facets (see explorer-field-metadata).
_EXPLORER_PRIMARY_FILTER_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "lineage",
        "sample",
        "condition",
        "batch",
        "patient",
        "tissue",
        "confidenceBucket",
    }
)


def _build_hierarchy_filter_axes(obs: pd.DataFrame) -> dict[str, Any]:
    """
    Co-occurrence axes for hierarchical filter UI: L2 options per L1, L3 per ``L1|L2``.

    Built from the full artifact ``obs`` so filter choices stay stable across embedding views.
    """
    if AUTO_LEVEL1_COL not in obs.columns or AUTO_LEVEL2_COL not in obs.columns:
        return {}
    l1n = _explorer_normalized_level1(obs)
    l2n = _explorer_normalized_level2(obs)
    level2_by_l1: dict[str, set[str]] = defaultdict(set)
    level3_by_pair: dict[str, set[str]] = defaultdict(set)
    for idx in obs.index:
        a1 = str(l1n.loc[idx] or "").strip()
        a2 = str(l2n.loc[idx] or "").strip()
        if not a1 or a1 == "Unknown":
            continue
        if a2:
            level2_by_l1[a1].add(a2)
            if _artifact_has_modern_canonical_hierarchy(obs):
                cell_l3 = _structural_level3_modern_cell(obs, idx, a2)
            else:
                raw3 = obs.at[idx, AUTO_LEVEL3_COL] if AUTO_LEVEL3_COL in obs.columns else ""
                cell_l3 = normalize_level3(a2, raw3)
            if cell_l3 and not level3_non_informative(cell_l3):
                level3_by_pair[f"{a1}|{a2}"].add(cell_l3)
    return {
        "level2_by_lineage": {k: sorted(v) for k, v in sorted(level2_by_l1.items())},
        "level3_by_lineage_major": {k: sorted(v) for k, v in sorted(level3_by_pair.items())},
    }


# (view_id, auto_level1 label, obsm key for P2 lineage UMAP)
EXPLORER_LINEAGE_VIEWS: tuple[tuple[str, str, str], ...] = (
    ("immune", "Immune", "X_umap_lineage_immune"),
    ("stromal", "Stromal", "X_umap_lineage_stromal"),
    ("epithelial", "Epithelial", "X_umap_lineage_epithelial"),
    ("endothelial", "Endothelial", "X_umap_lineage_endothelial"),
)

# (view_id, canonical auto_level2 label, obsm key for P3 fine UMAP)
EXPLORER_FINE_VIEWS: tuple[tuple[str, str, str], ...] = (
    ("fine_t_cells", "T cells", OBSM_UMAP_FINE_T_CELLS),
    ("fine_b_cells", "B cells", OBSM_UMAP_FINE_B_CELLS),
    ("fine_myeloid", "Myeloid", OBSM_UMAP_FINE_MYELOID),
    ("fine_fibroblasts", "Fibroblasts", OBSM_UMAP_FINE_FIBROBLASTS),
    ("fine_smooth_muscle", "Smooth muscle", OBSM_UMAP_FINE_SMOOTH_MUSCLE),
)


def _explorer_partition_kind(explorer_view_id: str) -> str | None:
    """``lineage_subcluster`` / ``fine_subcluster`` when the UI is in a partition embedding."""
    vid = str(explorer_view_id or "").strip().lower()
    if vid == "global":
        return None
    if any(x[0] == vid for x in EXPLORER_LINEAGE_VIEWS):
        return "lineage_subcluster"
    if any(x[0] == vid for x in EXPLORER_FINE_VIEWS):
        return "fine_subcluster"
    return None


FIELD_DEFINITIONS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("cluster", ("leiden", "cluster", "cluster_id"), "categorical"),
    (
        "cellType",
        (
            "final_display",
            "celltype_display",
            "zr_display",
            "annotation_cell_type",
            "celltypist_majority_voting",
            "celltypist_cell_type",
            "CellType",
            "cell_type",
            # Last resort: raw engine string — prefer ``rawAnnotationLabel`` / inspector for explicit legacy view.
            "annotation_label",
        ),
        "categorical",
    ),
    (
        "lineage",
        (
            "auto_level1",
            "annotation_lineage",
            "annotation_broad",
            "zr_level1",
            "celltype_level1",
            "lineage",
        ),
        "categorical",
    ),
    ("level2", ("auto_level2", "zr_level2", "celltype_level2"), "categorical"),
    (
        "level3",
        ("auto_level3", "level3_final_safe"),
        "categorical",
    ),
    ("lineageSubcluster", ("lineage_subcluster",), "categorical"),
    ("fineSubcluster", ("fine_subcluster",), "categorical"),
    (
        "globalCluster",
        ("global_cluster",),
        "categorical",
    ),
    ("displayLabel", ("final_display", "celltype_display", "zr_display"), "categorical"),
    ("tissue", ("annotation_tissue", "tissue", "organ", "site", "sample_tissue"), "categorical"),
    ("confidenceBucket", ("annotation_confidence",), "categorical"),
    ("confidence", ("annotation_confidence", "celltypist_conf_score", "confidence"), "continuous"),
    ("sample", ("sample", "sample_id"), "categorical"),
    ("condition", ("condition", "disease_state", "disease", "state"), "categorical"),
    ("batch", ("batch", "batch_id"), "categorical"),
    ("patient", ("patient", "patient_id", "donor", "donor_id"), "categorical"),
    # Raw / engine label when ``final_display`` is the canonical cellType source (advanced coloring).
    ("rawAnnotationLabel", ("annotation_label",), "categorical"),
)


def _clean_obs_text(value: object) -> str | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    return text


def _extract_level3_from_final_display(value: object) -> str | None:
    text = _clean_obs_text(value)
    if not text:
        return None
    parts = [segment.strip() for segment in text.split("|") if segment.strip()]
    if len(parts) < 3:
        return None
    return parts[-1] or None


def _derived_display_label_series(obs: pd.DataFrame) -> pd.Series:
    """
    Conservative readable summary: on modern canonical artifacts use ``final_display`` only
    so display never aliases raw engine strings as the summary when ``final_display`` exists.
    """
    if _artifact_has_modern_canonical_hierarchy(obs) and FINAL_DISPLAY_COL in obs.columns:
        return pd.Series(
            [_clean_obs_text(obs.at[idx, FINAL_DISPLAY_COL]) for idx in obs.index],
            index=obs.index,
            dtype=object,
        )
    preferred_columns = (
        FINAL_DISPLAY_COL,
        "celltype_display",
        "zr_display",
    )
    values: list[str | None] = []
    for idx in obs.index:
        chosen: str | None = None
        for column in preferred_columns:
            if column not in obs.columns:
                continue
            candidate = _clean_obs_text(obs.at[idx, column])
            if candidate:
                chosen = candidate
                break
        values.append(chosen)
    return pd.Series(values, index=obs.index, dtype=object)


def _derived_level3_series(obs: pd.DataFrame) -> pd.Series:
    if _artifact_has_modern_canonical_hierarchy(obs):
        return _structural_level3_modern_series(obs)
    return _derived_level3_series_legacy(obs)


def resolve_explorer_source_column(obs_columns: Iterable[str], response_key: str) -> str | None:
    """First obs column matching ``response_key`` in :data:`FIELD_DEFINITIONS` (single source of truth)."""
    colset = set(obs_columns)
    for rk, candidates, _kind in FIELD_DEFINITIONS:
        if rk != response_key:
            continue
        for candidate in candidates:
            if candidate in colset:
                return candidate
    return None


def _cluster_deg_markers_for_key(
    cluster_key: str,
    annotation: dict[str, Any],
    cluster_markers_uns: dict[str, Any],
) -> list[str]:
    """Resolve saved DE / cluster marker gene list for ``cluster_key`` (str-normalized)."""
    markers = RunExplorerService._coerce_list(annotation.get("cluster_markers"))
    if markers:
        return [str(m) for m in markers]
    for alt in (cluster_key, str(int(cluster_key)) if cluster_key.isdigit() else None):
        if alt is None:
            continue
        markers = RunExplorerService._coerce_list(cluster_markers_uns.get(alt))
        if markers:
            return [str(m) for m in markers]
    return []


def _runner_up_labels(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    """Next-best annotation candidates (for exclusion / runner-up explanations)."""
    top = annotation.get("top_cell_types") or []
    out: list[dict[str, Any]] = []
    for entry in top[1:3]:
        norm = normalize_top_cell_types_entry(entry)
        if norm is None:
            continue
        out.append(
            {
                "cell_type": str(norm.get("cell_type", "")),
                "score": float(norm.get("score", 0.0)),
                "n_markers": int(norm.get("n_markers", 0) or 0),
            }
        )
    return out


class RunExplorerService:
    """Service for restoring explorer-ready state from completed run artifacts."""

    def __init__(
        self,
        db: AsyncSession,
        s3_service: S3Service | None = None,
    ):
        self.db = db
        self.s3_service = s3_service or S3Service()

    async def get_run_explorer(
        self,
        run_id: UUID,
        org_id: UUID,
        max_cells: int = 50_000,
        explorer_view: str = "global",
    ) -> dict[str, Any]:
        """Return overview + embedding explorer payload for a completed run."""
        artifact = await self._get_h5ad_artifact(run_id=run_id, org_id=org_id)
        local_path = self._ensure_local_h5ad(artifact)
        adata = ad.read_h5ad(local_path, backed="r")
        try:
            return self._build_payload(
                run_id=run_id,
                adata=adata,
                max_cells=max_cells,
                explorer_view=explorer_view,
            )
        finally:
            if getattr(adata, "file", None) is not None:
                adata.file.close()

    async def get_primary_h5ad_local_path(self, *, run_id: UUID, org_id: UUID) -> Path:
        """Download (or reuse cache) the latest H5AD artifact for a completed run; return local path."""
        artifact = await self._get_h5ad_artifact(run_id=run_id, org_id=org_id)
        return self._ensure_local_h5ad(artifact)

    async def get_gene_overlay(
        self,
        run_id: UUID,
        org_id: UUID,
        gene: str,
        max_cells: int = 50_000,
    ) -> dict[str, Any]:
        """Return expression values for one gene over the sampled explorer cells."""
        artifact = await self._get_h5ad_artifact(run_id=run_id, org_id=org_id)
        local_path = self._ensure_local_h5ad(artifact)
        adata = ad.read_h5ad(local_path, backed="r")
        try:
            return self._build_gene_overlay(
                run_id=run_id,
                adata=adata,
                gene=gene,
                max_cells=max_cells,
            )
        finally:
            if getattr(adata, "file", None) is not None:
                adata.file.close()

    def _build_payload(
        self,
        *,
        run_id: UUID,
        adata: ad.AnnData,
        max_cells: int,
        explorer_view: str = "global",
    ) -> dict[str, Any]:
        artifact_total_cells = int(adata.n_obs)
        if artifact_total_cells == 0:
            raise ValueError("Run artifact embedding has no cells")

        view_norm = str(explorer_view or "global").strip().lower()
        available_views = self._catalog_explorer_views(adata)

        global_key = (
            "X_umap" if "X_umap" in adata.obsm else ("X_tsne" if "X_tsne" in adata.obsm else None)
        )
        if global_key is None:
            raise ValueError("Run artifact does not contain a supported embedding")

        global_coords = np.asarray(adata.obsm[global_key])
        if global_coords.ndim != 2 or global_coords.shape[1] < 2:
            raise ValueError("Run artifact embedding is malformed")
        if global_coords.shape[0] != artifact_total_cells:
            raise ValueError("Run artifact embedding row count mismatch")

        lineage_cfg = next((x for x in EXPLORER_LINEAGE_VIEWS if x[0] == view_norm), None)
        fine_cfg = next((x for x in EXPLORER_FINE_VIEWS if x[0] == view_norm), None)
        lineage_embedding_fallback = False
        lineage_view_unavailable_reason: str | None = None
        cluster_source_columns: tuple[str, ...] | None = None
        explorer_view_id = "global"
        explorer_view_label = "Global"
        view_cohort_n = artifact_total_cells
        cohort_indices_for_overview: list[int] | None = None

        if view_norm == "global":
            sampled_indices = self._sample_indices(
                total_cells=artifact_total_cells, max_cells=max_cells
            )
            embedding_key = global_key
            coords = global_coords
        elif lineage_cfg is not None:
            _, lineage_label, lineage_obsm_key = lineage_cfg
            explorer_view_id = lineage_cfg[0]
            explorer_view_label = f"{lineage_label} (lineage)"
            cluster_source_columns = (
                "lineage_subcluster",
                "leiden",
                "cluster",
                "cluster_id",
            )

            if "auto_level1" not in adata.obs.columns:
                lineage_view_unavailable_reason = "Lineage views need auto_level1 on this artifact; showing the full run in global coordinates."
                sampled_indices = self._sample_indices(
                    total_cells=artifact_total_cells, max_cells=max_cells
                )
                embedding_key = global_key
                coords = global_coords
                lineage_embedding_fallback = True
                cluster_source_columns = None
                view_cohort_n = artifact_total_cells
                cohort_indices_for_overview = None
            else:
                a1 = adata.obs["auto_level1"].astype(str).str.strip()
                lineage_mask = (a1 == lineage_label).to_numpy()
                pool_all = np.flatnonzero(lineage_mask).tolist()
                if not pool_all:
                    lineage_view_unavailable_reason = (
                        f"No cells with auto_level1={lineage_label} in this artifact."
                    )
                    sampled_indices = []
                    embedding_key = global_key
                    coords = global_coords
                    view_cohort_n = 0
                    cohort_indices_for_overview = []
                else:
                    coords_candidate: np.ndarray | None = None
                    if lineage_obsm_key in adata.obsm:
                        arr = np.asarray(adata.obsm[lineage_obsm_key])
                        if (
                            arr.ndim == 2
                            and arr.shape[0] == artifact_total_cells
                            and arr.shape[1] >= 2
                        ):
                            coords_candidate = arr
                    if coords_candidate is not None:
                        fin = np.isfinite(coords_candidate[:, 0]) & np.isfinite(
                            coords_candidate[:, 1]
                        )
                        pool_fin = np.flatnonzero(lineage_mask & fin).tolist()
                        if pool_fin:
                            embedding_key = lineage_obsm_key
                            coords = coords_candidate
                            pool = pool_fin
                        else:
                            embedding_key = global_key
                            coords = global_coords
                            pool = pool_all
                            lineage_embedding_fallback = True
                    else:
                        embedding_key = global_key
                        coords = global_coords
                        pool = pool_all
                        lineage_embedding_fallback = True
                    sampled_indices = self._sample_indices_from_pool(pool, max_cells)
                    view_cohort_n = len(pool)
                    cohort_indices_for_overview = pool
        elif fine_cfg is not None:
            _, l2_label, fine_obsm_key = fine_cfg
            explorer_view_id = fine_cfg[0]
            explorer_view_label = f"{l2_label} (fine)"
            cluster_source_columns = (
                "fine_subcluster",
                "leiden",
                "cluster",
                "cluster_id",
            )

            if AUTO_LEVEL1_COL not in adata.obs.columns or AUTO_LEVEL2_COL not in adata.obs.columns:
                lineage_view_unavailable_reason = "Fine views need auto_level1 and auto_level2 on this artifact; showing global coordinates."
                sampled_indices = self._sample_indices(
                    total_cells=artifact_total_cells, max_cells=max_cells
                )
                embedding_key = global_key
                coords = global_coords
                lineage_embedding_fallback = True
                cluster_source_columns = None
                view_cohort_n = artifact_total_cells
                cohort_indices_for_overview = None
            else:
                l2n = _explorer_normalized_level2(adata.obs)
                fine_mask = (l2n.astype(str) == l2_label).to_numpy()
                pool_all = np.flatnonzero(fine_mask).tolist()
                if not pool_all:
                    lineage_view_unavailable_reason = (
                        f"No cells with normalized auto_level2={l2_label!r} in this artifact."
                    )
                    sampled_indices = []
                    embedding_key = global_key
                    coords = global_coords
                    view_cohort_n = 0
                    cohort_indices_for_overview = []
                else:
                    fine_coords_candidate: np.ndarray | None = None
                    if fine_obsm_key in adata.obsm:
                        arr = np.asarray(adata.obsm[fine_obsm_key])
                        if (
                            arr.ndim == 2
                            and arr.shape[0] == artifact_total_cells
                            and arr.shape[1] >= 2
                        ):
                            fine_coords_candidate = arr
                    if fine_coords_candidate is not None:
                        fin = np.isfinite(fine_coords_candidate[:, 0]) & np.isfinite(
                            fine_coords_candidate[:, 1]
                        )
                        pool_fin = np.flatnonzero(fine_mask & fin).tolist()
                        if pool_fin:
                            embedding_key = fine_obsm_key
                            coords = fine_coords_candidate
                            pool = pool_fin
                        else:
                            embedding_key = global_key
                            coords = global_coords
                            pool = pool_all
                            lineage_embedding_fallback = True
                    else:
                        embedding_key = global_key
                        coords = global_coords
                        pool = pool_all
                        lineage_embedding_fallback = True
                    sampled_indices = self._sample_indices_from_pool(pool, max_cells)
                    view_cohort_n = len(pool)
                    cohort_indices_for_overview = pool
        else:
            sampled_indices = self._sample_indices(
                total_cells=artifact_total_cells, max_cells=max_cells
            )
            embedding_key = global_key
            coords = global_coords

        extracted_fields = self._extract_fields(
            adata, cluster_source_columns=cluster_source_columns
        )

        obs_names = list(map(str, adata.obs_names))
        metadata: list[dict[str, Any]] = []
        embedding_cells: list[dict[str, Any]] = []
        sampled_xs: list[float] = []
        sampled_ys: list[float] = []

        for idx in sampled_indices:
            x = float(coords[idx, 0])
            y = float(coords[idx, 1])
            sampled_xs.append(x)
            sampled_ys.append(y)
            embedding_cells.append({"id": obs_names[idx], "x": x, "y": y})

            row: dict[str, Any] = {"cellId": obs_names[idx]}
            for field_name, field_info in extracted_fields.items():
                value = field_info["sampled_values"][idx]
                if value is not None:
                    row[field_name] = value
            metadata.append(row)

        if not sampled_xs:
            sampled_xs = [0.0, 1.0]
            sampled_ys = [0.0, 1.0]

        available_fields = list(extracted_fields.keys())
        continuous_fields = [
            field_name
            for field_name, field_info in extracted_fields.items()
            if field_info["kind"] == "continuous"
        ]
        categorical_fields = [
            field_name
            for field_name, field_info in extracted_fields.items()
            if field_info["kind"] == "categorical"
        ]
        field_ranges = {
            field_name: field_info["range"]
            for field_name, field_info in extracted_fields.items()
            if field_info["kind"] == "continuous" and field_info.get("range") is not None
        }
        _omit_from_filter_values = _cohort_categorical_fields_omitted_from_filter_values(adata.obs)
        filter_values = {
            field_name: field_info["filter_values"]
            for field_name, field_info in extracted_fields.items()
            if field_info.get("filter_values") and field_name not in _omit_from_filter_values
        }
        categorical_with_filters = [
            field_name for field_name in categorical_fields if field_name in filter_values
        ]
        filter_fields = [
            f for f in categorical_with_filters if f in _EXPLORER_PRIMARY_FILTER_FIELD_KEYS
        ]
        advanced_filter_fields = [
            f for f in categorical_with_filters if f not in _EXPLORER_PRIMARY_FILTER_FIELD_KEYS
        ]

        hierarchy_filter_axes = _build_hierarchy_filter_axes(adata.obs)

        cluster_series = self._field_series(extracted_fields, "cluster")
        cell_type_series = self._field_series(extracted_fields, "cellType")
        condition_series = self._field_series(extracted_fields, "condition")
        sample_series = self._field_series(extracted_fields, "sample")

        cluster_ov = self._restrict_series_to_cohort(cluster_series, cohort_indices_for_overview)
        lineage_ov = self._restrict_series_to_cohort(
            self._field_series(extracted_fields, "lineage"), cohort_indices_for_overview
        )
        level2_ov = self._restrict_series_to_cohort(
            self._field_series(extracted_fields, "level2"), cohort_indices_for_overview
        )
        level3_ov = self._restrict_series_to_cohort(
            self._field_series(extracted_fields, "level3"), cohort_indices_for_overview
        )
        cell_type_ov = self._restrict_series_to_cohort(
            cell_type_series, cohort_indices_for_overview
        )
        raw_zerna_full = self._field_series(extracted_fields, "rawAnnotationLabel")
        raw_zerna_ov = self._restrict_series_to_cohort(
            raw_zerna_full, cohort_indices_for_overview
        )
        condition_ov = self._restrict_series_to_cohort(
            condition_series, cohort_indices_for_overview
        )
        sample_ov = self._restrict_series_to_cohort(sample_series, cohort_indices_for_overview)
        conf_ov = self._restrict_series_to_cohort(
            self._field_series(extracted_fields, "confidenceBucket"),
            cohort_indices_for_overview,
        )

        overview = {
            "n_cells": view_cohort_n,
            "n_genes": int(adata.n_vars),
            "n_clusters": self._unique_count(cluster_ov),
            "n_cell_types": self._unique_count(cell_type_ov),
            "n_samples": self._unique_count(sample_ov),
            "n_conditions": self._unique_count(condition_ov),
            "top_cell_types": self._top_counts(cell_type_ov),
            "top_conditions": self._top_counts(
                condition_ov if condition_ov is not None else sample_ov
            ),
            "artifact_total_cells": artifact_total_cells,
        }

        partition_kind = (
            _explorer_partition_kind(explorer_view_id) if cluster_source_columns else None
        )
        global_cluster_ov: pd.Series | None = None
        if partition_kind and GLOBAL_CLUSTER_COL in adata.obs.columns:
            gcs = adata.obs[GLOBAL_CLUSTER_COL].astype(str)
            if cohort_indices_for_overview is not None:
                if cohort_indices_for_overview:
                    global_cluster_ov = gcs.iloc[cohort_indices_for_overview]
                else:
                    global_cluster_ov = pd.Series(dtype=object)
            else:
                global_cluster_ov = gcs

        cluster_summaries = (
            self._build_cluster_summaries(
                adata=adata,
                cluster_series=cluster_ov,
                cell_type_series=cell_type_ov,
                confidence_bucket_series=conf_ov,
                partition_kind=partition_kind,
                global_cluster_series=global_cluster_ov,
                lineage_series=lineage_ov,
                level2_series=level2_ov,
                level3_series=level3_ov,
                raw_annotation_label_series=raw_zerna_ov,
            )
            if cluster_ov is not None and not cluster_ov.empty
            else []
        )

        sampled = (
            explorer_view_id == "global" and len(sampled_indices) < artifact_total_cells
        ) or (
            explorer_view_id != "global"
            and view_cohort_n > 0
            and len(sampled_indices) < view_cohort_n
        )

        return {
            "run_id": str(run_id),
            "embedding_key": embedding_key,
            "embedding": {
                "cells": embedding_cells,
                "bounds": {
                    "minX": float(min(sampled_xs)),
                    "maxX": float(max(sampled_xs)),
                    "minY": float(min(sampled_ys)),
                    "maxY": float(max(sampled_ys)),
                },
            },
            "metadata": metadata,
            "available_fields": available_fields,
            "categorical_fields": categorical_fields,
            "continuous_fields": continuous_fields,
            "field_ranges": field_ranges,
            "filter_fields": filter_fields,
            "advanced_filter_fields": advanced_filter_fields,
            "filter_values": filter_values,
            "hierarchy_filter_axes": hierarchy_filter_axes,
            "overview": overview,
            "cluster_summaries": cluster_summaries,
            "total_cells": view_cohort_n,
            "sampled": sampled,
            "explorer_view": explorer_view_id,
            "explorer_view_label": explorer_view_label,
            "available_views": available_views,
            "lineage_embedding_fallback": lineage_embedding_fallback,
            "lineage_view_unavailable_reason": lineage_view_unavailable_reason,
        }

    def _build_gene_overlay(
        self,
        *,
        run_id: UUID,
        adata: ad.AnnData,
        gene: str,
        max_cells: int,
    ) -> dict[str, Any]:
        total_cells = int(adata.n_obs)
        if total_cells == 0:
            raise ValueError("Run artifact has no cells")

        gene_name = self._resolve_gene_name(adata, gene)
        sampled_indices = self._sample_indices(total_cells=total_cells, max_cells=max_cells)
        obs_names = list(map(str, adata.obs_names))
        values = self._extract_gene_values(
            adata=adata,
            gene_name=gene_name,
            sampled_indices=sampled_indices,
        )
        finite_values = values[np.isfinite(values)]

        return {
            "run_id": str(run_id),
            "gene": gene_name,
            "sampled": len(sampled_indices) < total_cells,
            "total_cells": total_cells,
            "min": float(finite_values.min()) if finite_values.size > 0 else 0.0,
            "max": float(finite_values.max()) if finite_values.size > 0 else 0.0,
            "values": {
                obs_names[idx]: float(values[pos]) for pos, idx in enumerate(sampled_indices)
            },
        }

    def _extract_fields(
        self,
        adata: ad.AnnData,
        *,
        cluster_source_columns: tuple[str, ...] | None = None,
    ) -> dict[str, dict[str, Any]]:
        obs = adata.obs
        extracted: dict[str, dict[str, Any]] = {}
        used_columns: set[str] = set()

        for response_key, candidates, kind in FIELD_DEFINITIONS:
            derived_series: pd.Series | None = None
            derived_source_column: str | None = None
            if kind == "categorical" and response_key == "level3":
                derived_series = _derived_level3_series(obs)
                derived_source_column = (
                    AUTO_LEVEL3_COL
                    if _artifact_has_modern_canonical_hierarchy(obs)
                    else (FINAL_DISPLAY_COL if FINAL_DISPLAY_COL in obs.columns else None)
                )
            elif kind == "categorical" and response_key == "displayLabel":
                derived_series = _derived_display_label_series(obs)
                derived_source_column = (
                    FINAL_DISPLAY_COL if FINAL_DISPLAY_COL in obs.columns else None
                )

            if derived_series is not None:
                cleaned = derived_series.map(self._clean_text_value)
                informative = cleaned.dropna()
                modern_strict_level3 = (
                    response_key == "level3" and _artifact_has_modern_canonical_hierarchy(obs)
                )
                if not informative.empty or modern_strict_level3:
                    if informative.empty and modern_strict_level3:
                        filter_values: list[str] = []
                    else:
                        values = informative.value_counts()
                        filter_values = values.index.astype(str).tolist()
                        if len(filter_values) <= 1 or len(filter_values) > 80:
                            filter_values = []
                    extracted[response_key] = {
                        "kind": "categorical",
                        "source_column": derived_source_column or "__derived__",
                        "sampled_values": cleaned.tolist(),
                        "series": cleaned,
                        "filter_values": filter_values,
                    }
                    continue

            if response_key == "cluster" and cluster_source_columns is not None:
                chosen = next(
                    (candidate for candidate in cluster_source_columns if candidate in obs.columns),
                    None,
                )
            else:
                chosen = next(
                    (candidate for candidate in candidates if candidate in obs.columns), None
                )
            if chosen is None:
                continue
            if chosen in used_columns:
                continue

            series = pd.Series(obs[chosen], index=obs.index)
            if kind == "continuous":
                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.notna().sum() == 0:
                    continue
                extracted[response_key] = {
                    "kind": "continuous",
                    "source_column": chosen,
                    "sampled_values": [
                        float(value) if pd.notna(value) else None for value in numeric.tolist()
                    ],
                    "range": {
                        "min": float(numeric.min()),
                        "max": float(numeric.max()),
                    },
                }
            else:
                cleaned = series.map(self._clean_text_value)
                informative = cleaned.dropna()
                if informative.empty:
                    continue
                values = informative.value_counts()
                filter_values = values.index.astype(str).tolist()
                if len(filter_values) <= 1 or len(filter_values) > 80:
                    filter_values = []
                extracted[response_key] = {
                    "kind": "categorical",
                    "source_column": chosen,
                    "sampled_values": cleaned.tolist(),
                    "series": cleaned,
                    "filter_values": filter_values,
                }
            used_columns.add(chosen)

        self._finalize_canonical_lineage_level2_in_extracted(extracted, obs)
        return extracted

    @staticmethod
    def _rebucket_categorical_filter_values(entry: dict[str, Any]) -> None:
        s = entry["series"]
        cleaned = s.map(RunExplorerService._clean_text_value)
        informative = cleaned.dropna()
        informative = informative[informative.astype(str).str.strip() != ""]
        if informative.empty:
            entry["filter_values"] = []
            return
        vc = informative.value_counts()
        filter_values = vc.index.astype(str).tolist()
        if len(filter_values) <= 1 or len(filter_values) > 80:
            filter_values = []
        entry["filter_values"] = filter_values

    @classmethod
    def _finalize_canonical_lineage_level2_in_extracted(
        cls, extracted: dict[str, dict[str, Any]], obs: pd.DataFrame
    ) -> None:
        """Normalize explorer lineage / level2 when sourced from auto columns (canonical contract)."""
        if "lineage" in extracted and extracted["lineage"].get("source_column") == AUTO_LEVEL1_COL:
            ns = _explorer_normalized_level1(obs).replace("", None)
            extracted["lineage"]["series"] = ns
            extracted["lineage"]["sampled_values"] = ns.tolist()
            cls._rebucket_categorical_filter_values(extracted["lineage"])

        if "level2" in extracted and extracted["level2"].get("source_column") == AUTO_LEVEL2_COL:
            if AUTO_LEVEL1_COL not in obs.columns:
                return
            ns2 = _explorer_normalized_level2(obs).replace("", None)
            extracted["level2"]["series"] = ns2
            extracted["level2"]["sampled_values"] = ns2.tolist()
            cls._rebucket_categorical_filter_values(extracted["level2"])

    def _build_cluster_summaries(
        self,
        *,
        adata: ad.AnnData,
        cluster_series: pd.Series | None,
        cell_type_series: pd.Series | None,
        confidence_bucket_series: pd.Series | None,
        partition_kind: str | None = None,
        global_cluster_series: pd.Series | None = None,
        lineage_series: pd.Series | None = None,
        level2_series: pd.Series | None = None,
        level3_series: pd.Series | None = None,
        raw_annotation_label_series: pd.Series | None = None,
    ) -> list[dict[str, Any]]:
        if cluster_series is None:
            return []

        cluster_annotations = self._json_ready_mapping(adata.uns.get("zerna_cluster_annotations"))
        cluster_markers = self._json_ready_mapping(adata.uns.get("cluster_markers"))
        retrieval_evidence = self._json_ready_mapping(adata.uns.get("cluster_retrieval_evidence"))
        inspector_root = self._json_ready(adata.uns.get(EXPLORER_PARTITION_INSPECTOR_UNS_KEY))
        layer_map: dict[str, Any] = {}
        if (
            partition_kind
            and isinstance(inspector_root, dict)
            and isinstance(inspector_root.get(partition_kind), dict)
        ):
            layer_map = self._json_ready_mapping(inspector_root.get(partition_kind))

        counts = cluster_series.dropna().value_counts()
        summaries: list[dict[str, Any]] = []
        raw_zerna_obs_series: pd.Series | None = raw_annotation_label_series
        if raw_zerna_obs_series is None and "annotation_label" in adata.obs.columns:
            raw_zerna_obs_series = adata.obs["annotation_label"].reindex(cluster_series.index)
        for cluster_id, count in counts.items():
            key = str(cluster_id)
            partition_support_pref: list[str] | None = None
            retrieval_key = key
            if partition_kind:
                raw_layer = layer_map.get(key)
                annotation = (
                    copy.deepcopy(raw_layer) if isinstance(raw_layer, dict) and raw_layer else {}
                )
                fallback_global_id: str | None = None
                if not annotation and global_cluster_series is not None:
                    mask = cluster_series == key
                    gsub = global_cluster_series.loc[mask].dropna().astype(str).str.strip()
                    gsub = gsub[gsub != ""]
                    if not gsub.empty:
                        fallback_global_id = str(gsub.mode().iloc[0])
                        fa = cluster_annotations.get(fallback_global_id, {})
                        annotation = copy.deepcopy(fa) if isinstance(fa, dict) else {}
                rk = annotation.pop("_retrieval_source_cluster", None)
                partition_support_pref = annotation.pop(
                    "partition_annotation_support_markers", None
                )
                if isinstance(partition_support_pref, list):
                    partition_support_pref = [str(x) for x in partition_support_pref]
                else:
                    partition_support_pref = None
                retrieval_key = str(rk or fallback_global_id or key)
            else:
                annotation = cluster_annotations.get(key, {})
                if not isinstance(annotation, dict):
                    annotation = {}

            marker_lookup_key = retrieval_key if partition_kind else key
            markers = _cluster_deg_markers_for_key(marker_lookup_key, annotation, cluster_markers)
            evidence_source = retrieval_evidence.get(retrieval_key, {})
            evidence = self._coerce_list(
                evidence_source.get("evidence") if isinstance(evidence_source, dict) else None
            )
            top_candidates = []
            for entry in self._coerce_list(annotation.get("top_cell_types"))[:3]:
                norm = normalize_top_cell_types_entry(entry)
                if norm is None:
                    continue
                top_candidates.append(
                    {
                        "cell_type": str(norm.get("cell_type", "")),
                        "score": self._safe_float(norm.get("score")),
                        "n_markers": self._safe_int(norm.get("n_markers")),
                    }
                )
            evidence_hits = []
            for entry in evidence[:3]:
                if not isinstance(entry, dict):
                    continue
                label = (
                    entry.get("level3_label")
                    or entry.get("label")
                    or entry.get("cell_type")
                    or entry.get("normalized_label")
                )
                evidence_hits.append(
                    {
                        "cluster_id": self._clean_text_value(entry.get("cluster_id")),
                        "label": str(label or "Unknown"),
                        "lineage": self._clean_text_value(
                            entry.get("level1_label") or entry.get("lineage")
                        ),
                        "score": self._safe_float(entry.get("score")),
                    }
                )

            hierarchy_bio = self._canonical_hierarchy_biology_label_for_cluster(
                partition_kind=partition_kind,
                cluster_id=key,
                cluster_series=cluster_series,
                lineage_s=lineage_series,
                level2_s=level2_series,
                level3_s=level3_series,
            )
            cell_type_mode = self._most_common_for_cluster(
                cluster_series=cluster_series,
                value_series=cell_type_series,
                cluster_id=key,
            )
            raw_annotation_label_mode = (
                self._most_common_non_empty_for_cluster_mask(
                    cluster_series=cluster_series,
                    value_series=raw_zerna_obs_series,
                    cluster_id=key,
                )
                if raw_zerna_obs_series is not None
                else None
            )
            if partition_kind:
                label = hierarchy_bio or annotation.get("normalized_label") or cell_type_mode
            elif level2_series is not None:
                # Global: match embedding View-by contract — structural L1|L2|L3 before Zerna headline.
                label = hierarchy_bio or annotation.get("normalized_label") or cell_type_mode
            else:
                # Legacy artifacts (no resolved level2 column): keep normalized_label / cellType first.
                label = annotation.get("normalized_label") or cell_type_mode or hierarchy_bio
            confidence = annotation.get("confidence") or self._most_common_for_cluster(
                cluster_series=cluster_series,
                value_series=confidence_bucket_series,
                cluster_id=key,
            )
            label_str = str(label or "Unknown")
            display_label_secondary: str | None = None
            if (
                cell_type_mode
                and str(cell_type_mode).strip()
                and str(cell_type_mode).strip() != str(label_str).strip()
            ):
                display_label_secondary = str(cell_type_mode).strip()
            support_partition_overlap = False
            pack_markers, pack_key, headline_aligned = pick_support_markers_for_display_headline(
                annotation, label_str
            )
            if partition_kind and partition_support_pref and len(partition_support_pref) >= 2:
                support_markers = partition_support_pref[:15]
                support_source = pack_key
                support_partition_overlap = True
                support_aligned = bool(pack_key and headline_aligned)
            else:
                support_markers = pack_markers
                support_source = pack_key
                support_aligned = headline_aligned

            if not support_markers:
                support_aligned = True
            runner_ups = _runner_up_labels(annotation)
            mode = annotation.get("mode")
            annotation_mode = str(mode) if isinstance(mode, str) and mode else None
            conservative_status = None
            conservative_reason = None
            if annotation_mode == "conservative":
                conservative_status = str(annotation.get("status", "") or "") or None
                conservative_reason = str(annotation.get("reason", "") or "") or None

            summaries.append(
                {
                    "cluster_id": key,
                    "n_cells": int(count),
                    "label": label_str,
                    "raw_annotation_label_mode": raw_annotation_label_mode,
                    "display_label_secondary": display_label_secondary,
                    "confidence": str(confidence or "unknown"),
                    "summary": str(annotation.get("summary", "")),
                    "top_markers": [str(marker) for marker in list(markers)[:50]],
                    "evidence_count": len(evidence),
                    "evidence_hits": evidence_hits,
                    "top_cell_types": top_candidates,
                    "annotation_mode": annotation_mode,
                    "annotation_support_markers": support_markers,
                    "annotation_support_source_label": support_source,
                    "annotation_support_aligned_with_primary_headline": support_aligned,
                    "annotation_support_partition_de_overlap": support_partition_overlap,
                    "retrieval_tiebreak_applied": bool(
                        annotation.get("retrieval_tiebreak_applied")
                    ),
                    "conservative_status": conservative_status,
                    "conservative_reason": conservative_reason,
                    "runner_up_labels": runner_ups,
                }
            )

        return sorted(summaries, key=lambda item: int(item["n_cells"]), reverse=True)

    async def _get_h5ad_artifact(self, *, run_id: UUID, org_id: UUID) -> Artifact:
        run_stmt = select(Run).where(
            Run.id == run_id,
            Run.organization_id == org_id,
        )
        run_result = await self.db.execute(run_stmt)
        run = run_result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.status != RunStatus.COMPLETED:
            raise ValueError(f"Run {run_id} must be completed before it can be explored")

        artifact_stmt = (
            select(Artifact)
            .where(
                Artifact.run_id == run_id,
                Artifact.artifact_type == ArtifactType.H5AD,
            )
            .order_by(Artifact.created_at.desc())
        )
        artifact_result = await self.db.execute(artifact_stmt)
        artifact = artifact_result.scalar_one_or_none()
        if artifact is None:
            raise ValueError(f"Run {run_id} has no H5AD artifact to explore")
        return artifact

    def _resolve_s3_location(self, s3_path: str) -> tuple[str, str]:
        if s3_path.startswith("s3://"):
            bucket, key = s3_path[5:].split("/", 1)
            return bucket, key
        return self.s3_service.artifacts_bucket, s3_path

    def _ensure_local_h5ad(self, artifact: Artifact) -> Path:
        cache_root = Path(
            os.getenv(
                "ZERNA_EXPLORER_CACHE_DIR",
                str(Path(tempfile.gettempdir()) / "zerna_explorer_cache"),
            )
        )
        cache_root.mkdir(parents=True, exist_ok=True)

        suffix = Path(artifact.s3_path).suffix or ".h5ad"
        local_path = cache_root / f"{artifact.id}{suffix}"

        if local_path.exists():
            if local_path.stat().st_size > 0:
                return local_path

        bucket, key = self._resolve_s3_location(artifact.s3_path)
        tmp_path = local_path.with_suffix(f"{local_path.suffix}.part-{os.getpid()}")
        self.s3_service.s3_client.download_file(bucket, key, str(tmp_path))
        os.replace(tmp_path, local_path)
        return local_path

    def _resolve_gene_name(self, adata: ad.AnnData, gene: str) -> str:
        requested = gene.strip()
        if not requested:
            raise ValueError("Gene name is required")

        var_names = pd.Index(map(str, adata.var_names))
        if requested in var_names:
            return requested

        upper = var_names.str.upper()
        matches = var_names[upper == requested.upper()]
        if len(matches) == 1:
            return str(matches[0])
        if len(matches) > 1:
            raise ValueError(f"Gene '{gene}' is ambiguous in this artifact")
        raise ValueError(f"Gene '{gene}' was not found in this run artifact")

    def _extract_gene_values(
        self,
        *,
        adata: ad.AnnData,
        gene_name: str,
        sampled_indices: list[int],
    ) -> np.ndarray:
        locator = adata.var_names.get_loc(gene_name)
        if isinstance(locator, slice):
            gene_index = locator.start
        elif isinstance(locator, np.ndarray):
            matches = np.flatnonzero(locator)
            if matches.size == 0:
                raise ValueError(f"Gene '{gene_name}' was not found in this run artifact")
            gene_index = int(matches[0])
        else:
            gene_index = int(locator)

        gene_slice = adata[sampled_indices, gene_index].X
        if hasattr(gene_slice, "toarray"):
            gene_slice = gene_slice.toarray()
        values = np.asarray(gene_slice, dtype=np.float32).reshape(-1)
        return values

    @staticmethod
    def _sample_indices(*, total_cells: int, max_cells: int) -> list[int]:
        if total_cells <= max_cells:
            return list(range(total_cells))
        rng = np.random.default_rng(42)
        sampled = rng.choice(total_cells, size=max_cells, replace=False)
        return sorted(int(idx) for idx in sampled.tolist())

    @staticmethod
    def _sample_indices_from_pool(pool: list[int], max_cells: int) -> list[int]:
        if not pool:
            return []
        if len(pool) <= max_cells:
            return sorted(int(i) for i in pool)
        rng = np.random.default_rng(42)
        pick = rng.choice(len(pool), size=max_cells, replace=False)
        return sorted(int(pool[int(i)]) for i in pick.tolist())

    def _catalog_explorer_views(self, adata: ad.AnnData) -> list[dict[str, Any]]:
        n_obs = int(adata.n_obs)
        obs = adata.obs
        global_ok = "X_umap" in adata.obsm or "X_tsne" in adata.obsm
        out: list[dict[str, Any]] = [
            {
                "id": "global",
                "label": "Global",
                "lineage_label": None,
                "obsm_key": None,
                "n_cells": n_obs,
                "embedding_ready": bool(global_ok),
            }
        ]
        if "auto_level1" not in obs.columns:
            for vid, lname, okey in EXPLORER_LINEAGE_VIEWS:
                out.append(
                    {
                        "id": vid,
                        "label": lname,
                        "lineage_label": lname,
                        "obsm_key": okey,
                        "n_cells": 0,
                        "embedding_ready": False,
                    }
                )
            for vid, l2name, okey in EXPLORER_FINE_VIEWS:
                out.append(
                    {
                        "id": vid,
                        "label": f"{l2name} (fine)",
                        "lineage_label": l2name,
                        "obsm_key": okey,
                        "n_cells": 0,
                        "embedding_ready": False,
                    }
                )
            return out
        a1 = obs["auto_level1"].astype(str).str.strip()
        for vid, lname, okey in EXPLORER_LINEAGE_VIEWS:
            mask = (a1 == lname).to_numpy()
            n_lin = int(mask.sum())
            ready = False
            if n_lin > 0 and okey in adata.obsm:
                arr = np.asarray(adata.obsm[okey])
                if arr.ndim == 2 and arr.shape[0] == n_obs and arr.shape[1] >= 2:
                    fin = np.isfinite(arr[:, 0]) & np.isfinite(arr[:, 1])
                    ready = bool((fin & mask).any())
            out.append(
                {
                    "id": vid,
                    "label": lname,
                    "lineage_label": lname,
                    "obsm_key": okey,
                    "n_cells": n_lin,
                    "embedding_ready": ready,
                }
            )

        l2n = _explorer_normalized_level2(obs) if AUTO_LEVEL2_COL in obs.columns else None
        for vid, l2name, okey in EXPLORER_FINE_VIEWS:
            if l2n is None:
                n_f = 0
                ready = False
            else:
                mask = (l2n.astype(str) == l2name).to_numpy()
                n_f = int(mask.sum())
                ready = False
                if n_f > 0 and okey in adata.obsm:
                    arr = np.asarray(adata.obsm[okey])
                    if arr.ndim == 2 and arr.shape[0] == n_obs and arr.shape[1] >= 2:
                        fin = np.isfinite(arr[:, 0]) & np.isfinite(arr[:, 1])
                        ready = bool((fin & mask).any())
            out.append(
                {
                    "id": vid,
                    "label": f"{l2name} (fine)",
                    "lineage_label": l2name,
                    "obsm_key": okey,
                    "n_cells": n_f,
                    "embedding_ready": ready,
                }
            )
        return out

    @staticmethod
    def _clean_text_value(value: object) -> str | None:
        if value is None:
            return None
        if pd.isna(value):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            return None
        return text

    @staticmethod
    def _field_series(
        extracted_fields: dict[str, dict[str, Any]],
        field_name: str,
    ) -> pd.Series | None:
        field_info = extracted_fields.get(field_name)
        if field_info is None:
            return None
        if field_info["kind"] == "categorical":
            return field_info.get("series")
        values = field_info.get("sampled_values")
        return pd.Series(values) if values is not None else None

    @staticmethod
    def _restrict_series_to_cohort(
        series: pd.Series | None,
        cohort_indices: list[int] | None,
    ) -> pd.Series | None:
        if series is None:
            return None
        if cohort_indices is None:
            return series
        if not cohort_indices:
            return pd.Series(dtype=object)
        return series.iloc[cohort_indices]

    @staticmethod
    def _unique_count(series: pd.Series | None) -> int | None:
        if series is None:
            return None
        cleaned = series.dropna()
        return int(cleaned.nunique()) if not cleaned.empty else 0

    @staticmethod
    def _top_counts(series: pd.Series | None, limit: int = 8) -> list[dict[str, Any]]:
        if series is None:
            return []
        counts = series.dropna().value_counts().head(limit)
        return [{"label": str(label), "count": int(count)} for label, count in counts.items()]

    @staticmethod
    def _most_common_for_cluster(
        *,
        cluster_series: pd.Series,
        value_series: pd.Series | None,
        cluster_id: str,
    ) -> str | None:
        if value_series is None:
            return None
        mask = cluster_series == cluster_id
        values = value_series.loc[mask].dropna()
        if values.empty:
            return None
        return str(values.value_counts().index[0])

    @staticmethod
    def _most_common_non_empty_for_cluster_mask(
        *,
        cluster_series: pd.Series,
        value_series: pd.Series | None,
        cluster_id: str,
    ) -> str | None:
        """Mode of ``value_series`` within cluster, skipping blank / nan-like strings."""
        if value_series is None:
            return None
        mask = cluster_series.astype(str) == str(cluster_id)
        if not bool(mask.any()):
            return None
        sub = value_series.loc[mask].dropna().astype(str)
        sub = sub[(sub.str.strip() != "") & (~sub.str.strip().str.lower().isin({"nan", "none"}))]
        if sub.empty:
            return None
        return str(sub.value_counts().index[0])

    def _canonical_hierarchy_biology_label_for_cluster(
        self,
        *,
        partition_kind: str | None,
        cluster_id: str,
        cluster_series: pd.Series,
        lineage_s: pd.Series | None,
        level2_s: pd.Series | None,
        level3_s: pd.Series | None,
    ) -> str | None:
        """
        Primary biology string from auto_level1/2/3 for explorer + cluster inspector.

        Global Leiden: ``lineage | level2 | level3`` with each segment omitted when missing.
        P2 lineage partition: dominant ``auto_level2``.
        P3 fine partition: dominant ``auto_level3``, else ``auto_level2``.
        """
        if partition_kind == "fine_subcluster":
            v = self._most_common_non_empty_for_cluster_mask(
                cluster_series=cluster_series,
                value_series=level3_s,
                cluster_id=cluster_id,
            )
            if v:
                return v
            return self._most_common_non_empty_for_cluster_mask(
                cluster_series=cluster_series,
                value_series=level2_s,
                cluster_id=cluster_id,
            )
        if partition_kind == "lineage_subcluster":
            return self._most_common_non_empty_for_cluster_mask(
                cluster_series=cluster_series,
                value_series=level2_s,
                cluster_id=cluster_id,
            )
        parts: list[str] = []
        a = self._most_common_non_empty_for_cluster_mask(
            cluster_series=cluster_series,
            value_series=lineage_s,
            cluster_id=cluster_id,
        )
        if a:
            parts.append(a)
        b = self._most_common_non_empty_for_cluster_mask(
            cluster_series=cluster_series,
            value_series=level2_s,
            cluster_id=cluster_id,
        )
        if b:
            parts.append(b)
        c = self._most_common_non_empty_for_cluster_mask(
            cluster_series=cluster_series,
            value_series=level3_s,
            cluster_id=cluster_id,
        )
        if c:
            parts.append(c)
        if parts:
            return " | ".join(parts)
        return None

    def _json_ready_mapping(self, value: object) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                value = parsed
        if not isinstance(value, dict):
            return {}
        return {str(key): self._json_ready(item) for key, item in value.items()}

    def _json_ready(self, value: object) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return self._json_ready(json.loads(text))
                except json.JSONDecodeError:
                    return value
            return value
        if isinstance(value, dict):
            return {str(key): self._json_ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_ready(item) for item in value]
        if isinstance(value, np.ndarray):
            return [self._json_ready(item) for item in value.tolist()]
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _coerce_list(value: object) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, np.ndarray):
            return cast(list[Any], value.tolist())
        return [value]

    @staticmethod
    def _safe_float(value: object) -> float:
        try:
            return float(cast(Any, value)) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(cast(Any, value)) if value is not None else 0
        except (TypeError, ValueError):
            return 0
