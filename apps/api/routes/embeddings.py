"""Embedding data API — serves UMAP/t-SNE coordinates.

Tries to load a pre-computed embedding.json from MinIO first (fast, ~5MB).
Falls back to downloading the full h5ad and extracting on the fly.
"""

import json
import os
import tempfile
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from zerna_contracts.enums import ArtifactType
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings, resolve_s3_endpoint_url
from apps.api.dependencies import get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.models.pipeline import Artifact, Run
from apps.api.routes.runs import get_user_org_id
from apps.api.services.run_explorer_service import (
    RunExplorerService,
    resolve_explorer_source_column,
)

router = APIRouter(prefix="/v1/runs", tags=["runs"])


class EmbeddingCell(BaseModel):
    id: str
    x: float
    y: float


class CellMeta(BaseModel):
    cellId: str
    cluster: str | None = None
    cellType: str | None = None
    lineage: str | None = None
    level2: str | None = None
    level3: str | None = None
    displayLabel: str | None = None


class EmbeddingResponse(BaseModel):
    embedding_key: str
    cells: list[EmbeddingCell]
    metadata: list[CellMeta]
    cluster_labels: dict[str, str] = {}
    bounds: dict[str, float]
    available_fields: list[str]
    total_cells: int
    sampled: bool = False


class ExplorerEmbeddingResponse(BaseModel):
    cells: list[EmbeddingCell]
    bounds: dict[str, float]


class ExplorerCountResponse(BaseModel):
    label: str
    count: int


class ExplorerOverviewResponse(BaseModel):
    n_cells: int
    n_genes: int
    n_clusters: int | None = None
    n_cell_types: int | None = None
    n_samples: int | None = None
    n_conditions: int | None = None
    top_cell_types: list[ExplorerCountResponse]
    top_conditions: list[ExplorerCountResponse]
    artifact_total_cells: int | None = None


class ExplorerClusterCandidateResponse(BaseModel):
    cell_type: str
    score: float
    n_markers: int


class ExplorerRunnerUpLabelResponse(BaseModel):
    cell_type: str
    score: float
    n_markers: int


class ExplorerEvidenceHitResponse(BaseModel):
    cluster_id: str | None = None
    label: str
    lineage: str | None = None
    score: float


class ExplorerClusterSummaryResponse(BaseModel):
    cluster_id: str
    n_cells: int
    label: str
    confidence: str
    summary: str
    top_markers: list[str]
    evidence_count: int
    evidence_hits: list[ExplorerEvidenceHitResponse]
    top_cell_types: list[ExplorerClusterCandidateResponse]
    annotation_mode: str | None = None
    annotation_support_markers: list[str] = Field(default_factory=list)
    annotation_support_source_label: str | None = None
    annotation_support_aligned_with_primary_headline: bool = True
    annotation_support_partition_de_overlap: bool = False
    retrieval_tiebreak_applied: bool = False
    conservative_status: str | None = None
    conservative_reason: str | None = None
    runner_up_labels: list[ExplorerRunnerUpLabelResponse] = Field(default_factory=list)


class ExplorerViewOptionResponse(BaseModel):
    id: str
    label: str
    lineage_label: str | None = None
    obsm_key: str | None = None
    n_cells: int = 0
    embedding_ready: bool = False


class RunExplorerResponse(BaseModel):
    run_id: str
    embedding_key: str
    embedding: ExplorerEmbeddingResponse
    metadata: list[dict[str, Any]]
    available_fields: list[str]
    categorical_fields: list[str]
    continuous_fields: list[str]
    field_ranges: dict[str, dict[str, float]]
    filter_fields: list[str]
    filter_values: dict[str, list[str]]
    overview: ExplorerOverviewResponse
    cluster_summaries: list[ExplorerClusterSummaryResponse]
    total_cells: int
    sampled: bool = False
    explorer_view: str = "global"
    explorer_view_label: str = "Global"
    available_views: list[ExplorerViewOptionResponse] = Field(default_factory=list)
    lineage_embedding_fallback: bool = False
    lineage_view_unavailable_reason: str | None = None


class RunGeneOverlayResponse(BaseModel):
    run_id: str
    gene: str
    values: dict[str, float]
    min: float
    max: float
    total_cells: int
    sampled: bool = False


def _get_s3_client() -> Any:
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=resolve_s3_endpoint_url(settings),
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def _choose_embedding_key(obsm_keys: list[str]) -> str | None:
    for key in ("X_umap", "X_tsne"):
        if key in obsm_keys:
            return key
    return None


def _choose_cluster_column(obs_columns: list[str]) -> str | None:
    for key in ("leiden", "cluster", "louvain"):
        if key in obs_columns:
            return key
    return None


def _coerce_cluster_annotation_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _build_cluster_labels(
    *,
    clusters: list[str] | None,
    cell_types: list[str] | None,
    cluster_annotations: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not clusters:
        return {}

    labels: dict[str, str] = {}
    if cluster_annotations:
        for cluster_id, annotation in cluster_annotations.items():
            if not isinstance(annotation, dict):
                continue
            label = annotation.get("normalized_label") or annotation.get("cell_type")
            if isinstance(label, str) and label.strip():
                labels[str(cluster_id)] = label.strip()

    if cell_types:
        cluster_series = np.asarray(clusters, dtype=object)
        label_series = np.asarray(cell_types, dtype=object)
        for cluster_id in sorted(set(clusters)):
            if cluster_id in labels:
                continue
            mask = cluster_series == cluster_id
            values = [
                str(value).strip()
                for value in label_series[mask].tolist()
                if value is not None and str(value).strip() != ""
            ]
            if not values:
                continue
            counts: dict[str, int] = {}
            for value in values:
                counts[value] = counts.get(value, 0) + 1
            labels[cluster_id] = max(
                counts.items(),
                key=lambda item: (item[1], item[0]),
            )[0]

    return labels


def _try_cached_embedding(
    s3: Any, bucket: str, run_id: str, max_cells: int
) -> EmbeddingResponse | None:
    """Try to load pre-computed embedding.json from MinIO."""
    key = f"runs/{run_id}/embedding.json"
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(resp["Body"].read())

        cells_raw = data["cells"]
        meta_raw = data["metadata"]
        n_total = data["total_cells"]

        # Downsample if needed
        sampled = False
        if n_total > max_cells:
            rng = np.random.default_rng(42)
            indices = sorted(rng.choice(n_total, size=max_cells, replace=False))
            sampled = True
        else:
            indices = list(range(n_total))

        cells = [
            EmbeddingCell(id=cells_raw[i]["id"], x=cells_raw[i]["x"], y=cells_raw[i]["y"])
            for i in indices
        ]
        cached_cluster_labels = data.get("cluster_labels", {})
        if not isinstance(cached_cluster_labels, dict):
            cached_cluster_labels = {}
        if not cached_cluster_labels:
            paired_cluster_values = [
                (str(item.get("cluster")), str(item.get("cellType")))
                for item in meta_raw
                if item.get("cluster") is not None and item.get("cellType") is not None
            ]
            cached_cluster_labels = _build_cluster_labels(
                clusters=[cluster for cluster, _ in paired_cluster_values] or None,
                cell_types=[cell_type for _, cell_type in paired_cluster_values] or None,
            )
        metadata = [
            CellMeta(
                cellId=meta_raw[i]["cellId"],
                cluster=meta_raw[i].get("cluster"),
                cellType=meta_raw[i].get("cellType"),
            )
            for i in indices
        ]

        # Recompute bounds from sampled data
        xs = [c.x for c in cells]
        ys = [c.y for c in cells]
        bounds = {"minX": min(xs), "maxX": max(xs), "minY": min(ys), "maxY": max(ys)}

        return EmbeddingResponse(
            embedding_key=data.get("embedding_key", "X_umap"),
            cells=cells,
            metadata=metadata,
            cluster_labels=cached_cluster_labels,
            bounds=bounds,
            available_fields=data.get("available_fields", ["cluster"]),
            total_cells=n_total,
            sampled=sampled,
        )
    except Exception:
        return None


async def get_run_explorer_service(db: AsyncSession = Depends(get_db)) -> RunExplorerService:
    return RunExplorerService(db=db)


@router.get(
    "/{run_id}/embedding",
    response_model=EmbeddingResponse,
    summary="Get embedding data",
    description="Returns UMAP or t-SNE coordinates and cell metadata. Uses cached embedding.json when available.",
)
async def get_embedding(
    run_id: UUID,
    max_cells: int = Query(default=50000, ge=100, le=200000),
    _: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    db: AsyncSession = Depends(get_db),
) -> EmbeddingResponse:
    # Verify run
    run_stmt = select(Run).where(Run.id == run_id, Run.organization_id == org_id)
    run_result = await db.execute(run_stmt)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status.value != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed")

    s3 = _get_s3_client()
    artifacts_bucket = os.getenv("S3_ARTIFACTS_BUCKET", "zerna-artifacts-dev")

    # --- Fast path: try cached embedding.json ---
    cached = _try_cached_embedding(s3, artifacts_bucket, str(run_id), max_cells)
    if cached is not None:
        return cached

    # --- Slow path: download h5ad and extract ---
    artifact_stmt = (
        select(Artifact)
        .where(Artifact.run_id == run_id, Artifact.artifact_type == ArtifactType.H5AD)
        .order_by(Artifact.created_at.desc())
    )
    artifact_result = await db.execute(artifact_stmt)
    artifact = artifact_result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="No H5AD artifact found for this run")

    s3_path = artifact.s3_path
    if s3_path.startswith("s3://"):
        parts = s3_path[5:].split("/", 1)
        bucket, key = parts if len(parts) == 2 else (artifacts_bucket, s3_path)
    else:
        bucket, key = artifacts_bucket, s3_path

    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        s3.download_file(bucket, key, tmp_path)

        import anndata as ad

        adata = ad.read_h5ad(tmp_path, backed="r")

        embedding_key = _choose_embedding_key(list(adata.obsm.keys()))
        if embedding_key is None:
            raise HTTPException(
                status_code=404, detail="No UMAP or t-SNE embedding found in artifact"
            )

        embedding = np.array(adata.obsm[embedding_key])
        n_total = embedding.shape[0]
        obs_names = list(adata.obs_names)
        obs_cols = list(adata.obs.columns)

        cluster_column = _choose_cluster_column(obs_cols)
        clusters = list(adata.obs[cluster_column].astype(str)) if cluster_column else None
        cell_type_column = resolve_explorer_source_column(obs_cols, "cellType")
        cell_types = list(adata.obs[cell_type_column].astype(str)) if cell_type_column else None
        lineage_col = resolve_explorer_source_column(obs_cols, "lineage")
        level2_col = resolve_explorer_source_column(obs_cols, "level2")
        level3_col = resolve_explorer_source_column(obs_cols, "level3")
        display_label_col = resolve_explorer_source_column(obs_cols, "displayLabel")
        obs_df = adata.obs

        def _obs_meta_str(col: str | None, row_idx: int) -> str | None:
            if not col:
                return None
            v = obs_df[col].iloc[row_idx]
            if v is None or pd.isna(v):
                return None
            out = str(v).strip()
            if not out or out.lower() in ("nan", "none"):
                return None
            return out

        cluster_labels = _build_cluster_labels(
            clusters=clusters,
            cell_types=cell_types,
            cluster_annotations=_coerce_cluster_annotation_mapping(
                adata.uns.get("zerna_cluster_annotations")
            ),
        )
        adata.file.close()

        sampled = False
        if n_total > max_cells:
            rng = np.random.default_rng(42)
            indices = sorted(rng.choice(n_total, size=max_cells, replace=False))
            sampled = True
        else:
            indices = list(range(n_total))

        cells = [
            EmbeddingCell(id=obs_names[i], x=float(embedding[i, 0]), y=float(embedding[i, 1]))
            for i in indices
        ]
        metadata = [
            CellMeta(
                cellId=obs_names[i],
                cluster=clusters[i] if clusters else None,
                cellType=_obs_meta_str(cell_type_column, i) if cell_type_column else None,
                lineage=_obs_meta_str(lineage_col, i),
                level2=_obs_meta_str(level2_col, i),
                level3=_obs_meta_str(level3_col, i),
                displayLabel=_obs_meta_str(display_label_col, i),
            )
            for i in indices
        ]

        xs = embedding[indices, 0]
        ys = embedding[indices, 1]
        bounds = {
            "minX": float(xs.min()),
            "maxX": float(xs.max()),
            "minY": float(ys.min()),
            "maxY": float(ys.max()),
        }

        available_fields: list[str] = []
        if clusters:
            available_fields.append("cluster")
        for key in ("cellType", "lineage", "level2", "level3", "displayLabel"):
            if resolve_explorer_source_column(obs_cols, key):
                available_fields.append(key)
        available_fields = list(dict.fromkeys(available_fields))

        return EmbeddingResponse(
            embedding_key=embedding_key,
            cells=cells,
            metadata=metadata,
            cluster_labels=cluster_labels,
            bounds=bounds,
            available_fields=available_fields,
            total_cells=n_total,
            sampled=sampled,
        )
    finally:
        import os as _os

        _os.unlink(tmp_path)


@router.get(
    "/{run_id}/explorer",
    response_model=RunExplorerResponse,
    summary="Get completed-run explorer data",
    description="Returns overview, embedding metadata, and cluster summaries from the completed run artifact.",
)
async def get_run_explorer(
    run_id: UUID,
    max_cells: int = Query(default=50_000, ge=100, le=200_000),
    explorer_view: str = Query(
        default="global",
        description="Embedding context: global, immune, stromal, epithelial, endothelial",
    ),
    _: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    svc: RunExplorerService = Depends(get_run_explorer_service),
) -> RunExplorerResponse:
    try:
        payload = await svc.get_run_explorer(
            run_id=run_id,
            org_id=org_id,
            max_cells=max_cells,
            explorer_view=explorer_view,
        )
        return RunExplorerResponse.model_validate(payload)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower() or "no h5ad artifact" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get(
    "/{run_id}/gene-overlay",
    response_model=RunGeneOverlayResponse,
    summary="Get one gene overlay for a completed run",
    description="Returns expression values for one gene over the sampled cells used by the completed-run explorer.",
)
async def get_run_gene_overlay(
    run_id: UUID,
    gene: str = Query(..., min_length=1, description="Gene symbol to load"),
    max_cells: int = Query(default=50_000, ge=100, le=200_000),
    _: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    svc: RunExplorerService = Depends(get_run_explorer_service),
) -> RunGeneOverlayResponse:
    try:
        payload = await svc.get_gene_overlay(
            run_id=run_id,
            org_id=org_id,
            gene=gene,
            max_cells=max_cells,
        )
        return RunGeneOverlayResponse.model_validate(payload)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail.lower() or "no h5ad artifact" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
