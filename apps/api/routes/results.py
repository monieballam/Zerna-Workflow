"""Run results API routes — lightweight summary from artifact metadata."""

import logging
import os
import tempfile
from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID

import anndata as ad
import pandas as pd
from zerna_contracts.enums import ArtifactType
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings, resolve_s3_endpoint_url
from apps.api.dependencies import get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.models.pipeline import Artifact, Run
from apps.api.routes.runs import get_user_org_id

router = APIRouter(prefix="/v1/runs", tags=["runs"])

logger = logging.getLogger(__name__)

CLUSTER_KEY_FIELDS = ("leiden", "louvain", "cluster", "cluster_id")
CLUSTER_LABEL_FIELDS = (
    "annotation_label",
    "annotation_cell_type",
    "zr_display",
    "celltype_display",
    "celltypist_majority_voting",
    "celltypist_cell_type",
    "cell_type",
)


class RunResultsResponse(BaseModel):
    run_id: str
    status: str
    step_metrics: dict[str, Any]
    software_versions: dict[str, str]
    artifact_id: str | None = None
    artifact_size_bytes: int | None = None
    download_url: str | None = None


class ArtifactPreviewResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int | None = None
    truncated: bool = False
    metadata: dict[str, Any]


def _resolve_s3_location(s3_path: str) -> tuple[str, str]:
    """Resolve artifact bucket/key from stored artifact path."""
    artifacts_bucket = os.getenv("S3_ARTIFACTS_BUCKET", "zerna-artifacts-dev")
    if s3_path.startswith("s3://"):
        parts = s3_path[5:].split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (artifacts_bucket, s3_path)
    return artifacts_bucket, s3_path


def _get_s3_client() -> Any:
    import boto3

    settings = get_settings()
    resolved = resolve_s3_endpoint_url(settings)
    config = BotoConfig(
        signature_version="s3v4",
        s3={"addressing_style": "path"} if resolved else {},
    )
    return boto3.client(
        "s3",
        endpoint_url=resolved,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=config,
    )


def _preview_error_detail(
    *,
    code: str,
    message: str,
    endpoint: str | None = None,
) -> dict[str, str]:
    detail: dict[str, str] = {"code": code, "message": message}
    if endpoint:
        detail["endpoint"] = endpoint
    return detail


def _storage_unreachable_http_exception(
    operation: str, bucket: str, key: str, exc: Exception
) -> HTTPException:
    """Build a 503 when S3/MinIO cannot be reached (wrong endpoint, service down)."""
    settings = get_settings()
    endpoint = resolve_s3_endpoint_url(settings)
    logger.warning(
        "S3 %s failed (connectivity): endpoint=%s bucket=%s key=%s",
        operation,
        endpoint,
        bucket,
        key,
        exc_info=True,
    )
    msg = (
        "Could not reach object storage. Confirm MinIO is running and S3_ENDPOINT_URL matches "
        "how the API runs (host dev: http://localhost:19000 by default; Docker network: http://minio:9000)."
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_preview_error_detail(code="storage_unreachable", message=msg, endpoint=endpoint),
    )


def _ensure_local_artifact(artifact: Artifact, s3_client: Any) -> str:
    cache_root = os.getenv(
        "ZERNA_EXPLORER_CACHE_DIR",
        os.path.join(tempfile.gettempdir(), "zerna_explorer_cache"),
    )
    os.makedirs(cache_root, exist_ok=True)

    suffix = os.path.splitext(artifact.s3_path)[1] or ".bin"
    local_path = os.path.join(cache_root, f"{artifact.id}{suffix}")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    bucket, key = _resolve_s3_location(artifact.s3_path)
    tmp_path = f"{local_path}.part-{os.getpid()}"
    s3_client.download_file(bucket, key, tmp_path)
    os.replace(tmp_path, local_path)
    return local_path


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, str):
        try:
            return value.tolist()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _coerce_mapping(value: Any) -> dict[str, Any]:
    normalized = _json_ready(value)
    return normalized if isinstance(normalized, dict) else {}


def _sort_cluster_id(cluster_id: str) -> tuple[int, int | str]:
    text = str(cluster_id)
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _most_common_cluster_label(
    cluster_series: pd.Series,
    label_series: pd.Series | None,
    cluster_id: str,
) -> str | None:
    if label_series is None:
        return None
    values = label_series[cluster_series == cluster_id].dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return None
    counts = values.value_counts()
    if counts.empty:
        return None
    return str(counts.index[0])


def _extract_cluster_metrics_from_h5ad(
    artifact: Artifact,
    *,
    preferred_cluster_key: str | None = None,
) -> dict[str, Any] | None:
    s3_client = _get_s3_client()
    local_path = _ensure_local_artifact(artifact, s3_client)
    adata = ad.read_h5ad(local_path, backed="r")
    try:
        cluster_key = None
        if preferred_cluster_key and preferred_cluster_key in adata.obs.columns:
            cluster_key = preferred_cluster_key
        else:
            for candidate in CLUSTER_KEY_FIELDS:
                if candidate in adata.obs.columns:
                    cluster_key = candidate
                    break
        if cluster_key is None:
            return None

        cluster_series = adata.obs[cluster_key].astype(str)
        counts = cluster_series.dropna().value_counts()
        if counts.empty:
            return None

        cluster_annotations = _coerce_mapping(adata.uns.get("zerna_cluster_annotations"))
        label_series = None
        for candidate in CLUSTER_LABEL_FIELDS:
            if candidate in adata.obs.columns:
                label_series = adata.obs[candidate].astype(str)
                break

        clusters: list[dict[str, Any]] = []
        for cluster_id in sorted((str(idx) for idx in counts.index), key=_sort_cluster_id):
            annotation = cluster_annotations.get(cluster_id, {})
            label = None
            if isinstance(annotation, dict):
                label = annotation.get("normalized_label") or annotation.get("cell_type")
            if not isinstance(label, str) or not label.strip():
                label = _most_common_cluster_label(cluster_series, label_series, cluster_id)
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "label": str(label).strip() if isinstance(label, str) and label.strip() else "",
                    "n_cells": int(cast(Any, counts.loc[cluster_id])),
                }
            )

        return {
            "cluster_key": cluster_key,
            "clusters": clusters,
            "cluster_sizes": [cluster["n_cells"] for cluster in clusters],
            "n_clusters": int(len(clusters)),
        }
    finally:
        if getattr(adata, "file", None) is not None:
            adata.file.close()


@router.get(
    "/{run_id}/results",
    response_model=RunResultsResponse,
    summary="Get run results summary",
    description="Returns pipeline step metrics extracted from the run artifact metadata.",
)
async def get_run_results(
    run_id: UUID,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    db: AsyncSession = Depends(get_db),
) -> RunResultsResponse:
    # Verify run exists and belongs to org
    run_stmt = select(Run).where(Run.id == run_id, Run.organization_id == org_id)
    run_result = await db.execute(run_stmt)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Get the h5ad artifact (primary output)
    artifact_stmt = (
        select(Artifact)
        .where(Artifact.run_id == run_id, Artifact.artifact_type == ArtifactType.H5AD)
        .order_by(Artifact.created_at.desc())
    )
    artifact_result = await db.execute(artifact_stmt)
    artifact = artifact_result.scalars().first()

    if artifact is None:
        fallback_artifact_stmt = (
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at.desc())
        )
        fallback_artifact_result = await db.execute(fallback_artifact_stmt)
        artifact = fallback_artifact_result.scalars().first()

    step_metrics: dict[str, Any] = {}
    software_versions: dict[str, str] = run.software_versions or {}
    artifact_id = None
    artifact_size = None
    download_url = None

    if artifact:
        artifact_id = str(artifact.id)
        artifact_size = artifact.size_bytes
        meta = artifact.extra_metadata or {}
        step_metrics = meta.get("step_metrics", {})
        if not software_versions:
            software_versions = meta.get("software_versions", {})

        # Generate download URL through API proxy (avoids MinIO CORS issues)
        try:
            download_url = f"/v1/runs/{run_id}/artifacts/{artifact_id}/download"
        except Exception:
            pass

        cluster_metrics = step_metrics.get("cluster")
        if isinstance(cluster_metrics, dict) and not cluster_metrics.get("clusters"):
            preferred_cluster_key = None
            for step_key in ("differential_expression", "ligand_receptor_analysis"):
                candidate = step_metrics.get(step_key)
                if isinstance(candidate, dict) and isinstance(candidate.get("cluster_key"), str):
                    preferred_cluster_key = str(candidate["cluster_key"])
                    break
            if preferred_cluster_key is None and isinstance(run.parameters, dict):
                cluster_key_param = run.parameters.get("cluster_key")
                if isinstance(cluster_key_param, str) and cluster_key_param.strip():
                    preferred_cluster_key = cluster_key_param.strip()

            try:
                enriched_cluster_metrics = _extract_cluster_metrics_from_h5ad(
                    artifact,
                    preferred_cluster_key=preferred_cluster_key,
                )
            except Exception:
                enriched_cluster_metrics = None

            if enriched_cluster_metrics:
                step_metrics = dict(step_metrics)
                step_metrics["cluster"] = {**cluster_metrics, **enriched_cluster_metrics}
                meta = dict(meta)
                meta["step_metrics"] = step_metrics
                artifact.extra_metadata = meta
                await db.commit()

    return RunResultsResponse(
        run_id=str(run_id),
        status=run.status.value,
        step_metrics=step_metrics,
        software_versions=software_versions,
        artifact_id=artifact_id,
        artifact_size_bytes=artifact_size,
        download_url=download_url,
    )


@router.get(
    "/{run_id}/artifacts/{artifact_id}/download",
    summary="Download run artifact",
    description="Stream artifact file through the API (avoids direct MinIO/S3 CORS issues).",
)
async def download_artifact(
    run_id: UUID,
    artifact_id: UUID,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Verify run belongs to org
    run_stmt = select(Run).where(Run.id == run_id, Run.organization_id == org_id)
    run_result = await db.execute(run_stmt)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Get artifact
    artifact_stmt = select(Artifact).where(Artifact.id == artifact_id, Artifact.run_id == run_id)
    artifact_result = await db.execute(artifact_stmt)
    artifact = artifact_result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    s3 = _get_s3_client()

    s3_path = artifact.s3_path
    bucket, key = _resolve_s3_location(s3_path)

    try:
        s3_obj = s3.get_object(Bucket=bucket, Key=key)
    except EndpointConnectionError as exc:
        raise _storage_unreachable_http_exception("get_object", bucket, key, exc) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NoSuchBucket"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file not found in storage"
            ) from exc
        settings = get_settings()
        endpoint = resolve_s3_endpoint_url(settings)
        logger.warning(
            "S3 get_object ClientError: endpoint=%s bucket=%s key=%s code=%s",
            endpoint,
            bucket,
            key,
            code,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Artifact download failed: {code or 'S3 error'}",
        ) from exc

    filename = key.rsplit("/", 1)[-1] if "/" in key else key

    def stream() -> Iterator[bytes]:
        for chunk in s3_obj["Body"].iter_chunks(chunk_size=1024 * 1024):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(s3_obj["ContentLength"]),
        },
    )


@router.get(
    "/{run_id}/artifacts/{artifact_id}/preview",
    response_model=ArtifactPreviewResponse,
    summary="Preview run artifact",
    description="Return a lightweight preview for CSV-based run artifacts.",
)
async def preview_artifact(
    run_id: UUID,
    artifact_id: UUID,
    limit: int = 200,
    user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_user_org_id),
    db: AsyncSession = Depends(get_db),
) -> ArtifactPreviewResponse:
    del user
    run_stmt = select(Run).where(Run.id == run_id, Run.organization_id == org_id)
    run_result = await db.execute(run_stmt)
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    artifact_stmt = select(Artifact).where(Artifact.id == artifact_id, Artifact.run_id == run_id)
    artifact_result = await db.execute(artifact_stmt)
    artifact = artifact_result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    if artifact.artifact_type == ArtifactType.H5AD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="H5AD artifacts are previewed through the run explorer, not CSV preview.",
        )

    if artifact.artifact_type not in {
        ArtifactType.DE_RESULTS,
        ArtifactType.PATHWAY_SCORES,
        ArtifactType.LIANA_RESULTS,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This artifact type does not support in-app preview.",
        )

    s3 = _get_s3_client()

    bucket, key = _resolve_s3_location(artifact.s3_path)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name

    settings = get_settings()
    endpoint = resolve_s3_endpoint_url(settings)
    try:
        s3.download_file(bucket, key, tmp_path)
    except EndpointConnectionError as exc:
        raise _storage_unreachable_http_exception(
            "download_file (preview)", bucket, key, exc
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        logger.warning(
            "Artifact preview S3 ClientError: endpoint=%s bucket=%s key=%s code=%s",
            endpoint,
            bucket,
            key,
            code,
            exc_info=True,
        )
        if code in ("404", "NoSuchKey", "NoSuchBucket"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_preview_error_detail(
                    code="artifact_missing",
                    message="Artifact file not found in object storage.",
                    endpoint=endpoint,
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_preview_error_detail(
                code="storage_error",
                message=f"Object storage returned an error while loading the artifact ({code or 'S3 error'}).",
                endpoint=endpoint,
            ),
        ) from exc
    except OSError as exc:
        logger.warning(
            "Artifact preview download failed: endpoint=%s bucket=%s key=%s error=%s",
            endpoint,
            bucket,
            key,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_preview_error_detail(
                code="storage_unreachable",
                message="Could not download the artifact from object storage.",
                endpoint=endpoint,
            ),
        ) from exc

    try:
        df = pd.read_csv(tmp_path, nrows=limit)
    except Exception as exc:
        logger.warning(
            "Artifact preview CSV parse failed: endpoint=%s bucket=%s key=%s error=%s",
            endpoint,
            bucket,
            key,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_preview_error_detail(
                code="preview_parse_failed",
                message="The results file could not be parsed as a previewable table (CSV).",
                endpoint=endpoint,
            ),
        ) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    normalized = df.where(pd.notnull(df), None)
    rows = cast(list[dict[str, Any]], normalized.to_dict(orient="records"))
    metadata = artifact.extra_metadata or {}
    total_rows = metadata.get("n_rows")
    if not isinstance(total_rows, int):
        total_rows = metadata.get("n_cells")
    if not isinstance(total_rows, int):
        total_rows = None

    return ArtifactPreviewResponse(
        artifact_id=str(artifact.id),
        artifact_type=artifact.artifact_type.value,
        columns=[str(column) for column in normalized.columns],
        rows=rows,
        total_rows=total_rows,
        truncated=bool(total_rows is not None and total_rows > len(rows)),
        metadata=metadata,
    )
