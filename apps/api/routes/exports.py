"""Export API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.routes.runs import get_user_org_id
from apps.api.schemas.export import (
    ExportDownloadResponse,
    ExportRequest,
    ExportResponse,
    ExportStatusResponse,
    ExportType,
)
from apps.api.services.export_service import ExportService
from apps.api.services.s3_service import S3Service

router = APIRouter(tags=["exports"])

# Maps export_type to (s3 filename, ExportService method name)
_EXPORT_TYPE_MAP: dict[ExportType, tuple[str, str]] = {
    "h5ad": ("export.h5ad", "export_h5ad"),
    "de_results": ("de_results.csv", "export_de_results_csv"),
    "embeddings": ("embeddings.csv", "export_embeddings_csv"),
    "report": ("reproducibility_report.html", "generate_reproducibility_report"),
}


async def get_export_service(db: AsyncSession = Depends(get_db)) -> ExportService:
    """Get ExportService dependency."""
    return ExportService(db=db)


async def get_s3_service() -> S3Service:
    """Get S3Service dependency."""
    return S3Service()


@router.post(
    "/v1/runs/{run_id}/export",
    response_model=ExportResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate export",
    description="Initiate an export for a run. Returns the S3 path of the generated export.",
)
async def initiate_export(
    run_id: UUID,
    request: ExportRequest,
    org_id: UUID = Depends(get_user_org_id),
    export_service: ExportService = Depends(get_export_service),
) -> ExportResponse:
    """Initiate an export for a run.

    Args:
        run_id: Run ID
        request: Export request with export_type
        org_id: Organization ID from authenticated user
        export_service: Export service

    Returns:
        Export response with S3 path and status

    Raises:
        HTTPException: 404 if run not found
        HTTPException: 400 for invalid export_type
    """
    if request.export_type not in _EXPORT_TYPE_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid export_type '{request.export_type}'. Must be one of: {list(_EXPORT_TYPE_MAP)}",
        )

    method_name = _EXPORT_TYPE_MAP[request.export_type][1]
    method = getattr(export_service, method_name)

    try:
        s3_path = await method(run_id=run_id, org_id=org_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {str(e)}",
        )

    return ExportResponse(
        run_id=run_id,
        export_type=request.export_type,
        s3_path=s3_path,
        status="completed",
    )


@router.get(
    "/v1/exports/{run_id}/status",
    response_model=ExportStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get export status",
    description="Check which exports have been generated for a run by listing S3 objects.",
)
async def get_export_status(
    run_id: UUID,
    org_id: UUID = Depends(get_user_org_id),
    export_service: ExportService = Depends(get_export_service),
    s3_service: S3Service = Depends(get_s3_service),
) -> ExportStatusResponse:
    """Get export status for a run.

    Args:
        run_id: Run ID
        org_id: Organization ID from authenticated user
        export_service: Export service (used to verify run exists)
        s3_service: S3 service for listing objects

    Returns:
        Export status with list of available export types

    Raises:
        HTTPException: 404 if run not found
    """
    # Verify run exists and belongs to org
    run = await export_service._get_run(run_id, org_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    prefix = f"{org_id}/exports/{run_id}/"
    try:
        objects = s3_service.list_files(bucket=s3_service.artifacts_bucket, prefix=prefix)
    except Exception:
        objects = []

    # Build a set of existing filenames
    existing_filenames = {obj["key"].split("/")[-1] for obj in objects}

    available: list[ExportType] = [
        export_type
        for export_type, (filename, _) in _EXPORT_TYPE_MAP.items()
        if filename in existing_filenames
    ]

    return ExportStatusResponse(run_id=run_id, available_exports=available)


@router.get(
    "/v1/exports/{run_id}/download",
    response_model=ExportDownloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Download export",
    description="Generate a pre-signed S3 download URL for a previously generated export.",
)
async def download_export(
    run_id: UUID,
    export_type: ExportType = Query(..., description="Export type to download"),
    org_id: UUID = Depends(get_user_org_id),
    export_service: ExportService = Depends(get_export_service),
    s3_service: S3Service = Depends(get_s3_service),
) -> ExportDownloadResponse:
    """Generate a pre-signed download URL for an export.

    Args:
        run_id: Run ID
        export_type: Type of export to download
        org_id: Organization ID from authenticated user
        export_service: Export service (used to verify run exists)
        s3_service: S3 service for generating pre-signed URL

    Returns:
        Download response with pre-signed URL

    Raises:
        HTTPException: 404 if run not found or export not yet generated
    """
    # Verify run exists and belongs to org
    run = await export_service._get_run(run_id, org_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    filename, _ = _EXPORT_TYPE_MAP[export_type]
    s3_path = f"{org_id}/exports/{run_id}/{filename}"

    # Verify the export exists in S3
    try:
        verification = s3_service.verify_upload(bucket=s3_service.artifacts_bucket, s3_path=s3_path)
        if not verification.get("exists", False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Export '{export_type}' not yet generated for run {run_id}",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export '{export_type}' not yet generated for run {run_id}",
        )

    try:
        download_url = s3_service.generate_presigned_download_url(
            bucket=s3_service.artifacts_bucket,
            s3_path=s3_path,
            expiration=3600,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate download URL: {str(e)}",
        )

    return ExportDownloadResponse(
        run_id=run_id,
        export_type=export_type,
        download_url=download_url,
        expires_in=3600,
    )
