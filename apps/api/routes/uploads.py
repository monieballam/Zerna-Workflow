"""Upload API routes for multipart file upload and S3 URI registration."""

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from apps.api.routes._upload_streaming import stream_upload_to_path
from apps.api.services.s3_service import S3Service
from apps.api.services.upload_service import (
    SUPPORTED_EXTENSIONS,
    UploadMetadata,
    UploadResult,
    UploadService,
)

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])


class RegisterURIRequest(BaseModel):
    """Request body for S3 URI registration."""

    uri: str = Field(..., description="S3 URI (s3://bucket/key)")
    dataset_id: UUID = Field(..., description="Target dataset ID")
    organization_id: UUID = Field(..., description="Organization ID")
    uploaded_by: UUID = Field(..., description="User ID performing the registration")
    description: str | None = Field(None, description="Optional description")


def _get_upload_service() -> UploadService:
    """Dependency to create an UploadService instance."""
    s3_service = S3Service()
    return UploadService(s3_service=s3_service)


@router.post(
    "/file",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file via multipart upload",
    description=(
        f"Upload a single-cell data file. "
        f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="File to upload"),
    dataset_id: UUID = Form(..., description="Target dataset ID"),
    organization_id: UUID = Form(..., description="Organization ID"),
    uploaded_by: UUID = Form(..., description="User ID performing the upload"),
    description: str | None = Form(None, description="Optional description"),
    upload_service: UploadService = Depends(_get_upload_service),
) -> UploadResult:
    """Upload a single-cell data file via multipart form data.

    Validates the file format, persists to S3, and returns an UploadResult.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    meta = UploadMetadata(
        dataset_id=dataset_id,
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        description=description,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="zerna_upload_route_") as tmp_dir:
            safe_filename = Path(file.filename).name
            temp_path = Path(tmp_dir) / safe_filename
            await stream_upload_to_path(file, temp_path)
            result = await upload_service.upload_path(
                local_path=temp_path,
                filename=safe_filename,
                metadata=meta,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return result


@router.post(
    "/register-uri",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Register an S3 URI as a dataset version",
    description="Register an existing S3 object as a dataset version without browser upload.",
)
async def register_uri(
    body: RegisterURIRequest,
    upload_service: UploadService = Depends(_get_upload_service),
) -> UploadResult:
    """Register an S3 URI without uploading through the browser."""
    meta = UploadMetadata(
        dataset_id=body.dataset_id,
        organization_id=body.organization_id,
        uploaded_by=body.uploaded_by,
        description=body.description,
    )

    try:
        result = await upload_service.register_uri(
            uri=body.uri,
            metadata=meta,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return result
