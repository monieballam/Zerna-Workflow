"""Dataset API routes."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from zerna_contracts.dataset_files import sanitize_storage_relative_path
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_cache_service, get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.dataset import Dataset
from apps.api.models.organization import User
from apps.api.models.pipeline import Run
from apps.api.routes._upload_streaming import stream_upload_to_path
from apps.api.schemas.dataset import (
    BulkDeleteDatasetsRequest,
    BulkDeleteDatasetsResponse,
    CreateDatasetRequest,
    DatasetAssociatedRunResponse,
    DatasetResponse,
    DatasetVersionColumnsResponse,
    DatasetVersionResponse,
    DeleteDatasetRequest,
    DeleteDatasetResponse,
    ListDatasetAssociatedRunsResponse,
    ListDatasetsResponse,
    UpdateDatasetRequest,
)
from apps.api.services.cache_service import CacheService
from apps.api.services.dataset_service import DatasetFilters, DatasetService
from apps.api.services.run_service import RunService

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


async def _persist_multipart_files_to_temp_tuples(
    upload_files: list[UploadFile],
    relative_paths: list[str] | None = None,
) -> tuple[list[tuple[str, str, str]], str]:
    """Stream multipart files to disk; returns (path, ext, s3_object_suffix) tuples and temp_dir.

    Caller must ``shutil.rmtree(temp_dir)`` when done.

    When the client sends ``file_relative_paths`` (e.g. from ``webkitRelativePath``), files are
    written under those paths and ``s3_object_suffix`` matches so multi-sample 10x MTX bundles with
    identical basenames stay distinct. Otherwise each part is stored under ``{idx}/{basename}`` and
    the same suffix is used for the object key (avoids overwriting in object storage).
    """
    file_tuples: list[tuple[str, str, str]] = []
    temp_dir = tempfile.mkdtemp(prefix="zerna_upload_")
    try:
        for idx, upload_file in enumerate(upload_files):
            if not upload_file.filename:
                continue
            safe_filename = Path(upload_file.filename).name
            object_suffix: str
            if (
                relative_paths is not None
                and idx < len(relative_paths)
                and relative_paths[idx].strip()
            ):
                object_suffix = sanitize_storage_relative_path(relative_paths[idx])
                file_path = os.path.join(temp_dir, object_suffix.replace("/", os.sep))
                parent = os.path.dirname(file_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
            else:
                object_suffix = f"{idx}/{safe_filename}"
                unique_dir = os.path.join(temp_dir, str(idx))
                os.makedirs(unique_dir, exist_ok=True)
                file_path = os.path.join(unique_dir, safe_filename)
            await stream_upload_to_path(upload_file, file_path)
            ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else "unknown"
            file_tuples.append((file_path, ext, object_suffix))
        return file_tuples, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _parse_optional_file_relative_paths(raw: object) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_relative_paths must be valid JSON",
        ) from e
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_relative_paths must be a JSON array of strings",
        )
    return list(parsed)


async def get_dataset_service(
    db: AsyncSession = Depends(get_db),
    cache: CacheService = Depends(get_cache_service),
) -> DatasetService:
    """Get DatasetService dependency."""
    return DatasetService(db=db, cache_service=cache)


async def _get_user_org_id(dataset_service: DatasetService, user: User) -> UUID:
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )
    return UUID(str(org_id))


async def _delete_dataset_with_run_mode(
    *,
    dataset_id: UUID,
    request: DeleteDatasetRequest,
    org_id: UUID,
    user_id: UUID,
    dataset_service: DatasetService,
    run_service: RunService,
) -> DeleteDatasetResponse:
    dataset = await dataset_service.get_dataset(
        dataset_id=dataset_id, org_id=org_id, include_versions=False
    )
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    associated_total = int(
        (
            await dataset_service.db.execute(
                select(func.count(Run.id)).where(
                    Run.organization_id == org_id,
                    Run.dataset_id_snapshot == dataset_id,
                )
            )
        ).scalar_one()
    )

    if request.run_delete_mode == "selected":
        selected_run_ids = list(dict.fromkeys(request.run_ids))
        if not selected_run_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select at least one associated run or preserve all runs.",
            )
        result = await dataset_service.db.execute(
            select(Run.id).where(
                Run.organization_id == org_id,
                Run.dataset_id_snapshot == dataset_id,
                Run.id.in_(selected_run_ids),
            )
        )
        available_run_ids = set(result.scalars().all())
        missing = [run_id for run_id in selected_run_ids if run_id not in available_run_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more selected runs do not belong to this dataset.",
            )
        for run_id in selected_run_ids:
            await run_service.delete_run(run_id=run_id, org_id=org_id, user_id=user_id)
        deleted_runs = len(selected_run_ids)
    elif request.run_delete_mode == "all":
        deleted_summary = await run_service.bulk_delete_runs(
            org_id=org_id,
            scope="all",
            dataset_id=dataset_id,
            user_id=user_id,
        )
        deleted_runs = int(deleted_summary["deleted_runs"])
    else:
        deleted_runs = 0

    deleted = await dataset_service.delete_dataset(
        dataset_id=dataset_id,
        org_id=org_id,
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    return DeleteDatasetResponse(
        dataset_id=dataset_id,
        deleted_runs=deleted_runs,
        preserved_runs=max(associated_total - deleted_runs, 0),
    )


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create dataset",
    description=(
        "Create a new dataset. Use JSON (application/json) for metadata-only creation, "
        "or multipart/form-data with fields name, optional description, optional metadata "
        "(JSON string), and files[] to create the dataset and first version in one request."
    ),
)
async def create_dataset(
    request: Request,
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetResponse:
    """Create a new dataset (JSON or multipart with files).

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 403 if user not member of organization
    """
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    content_type = request.headers.get("content-type", "")

    try:
        if "multipart/form-data" in content_type.lower():
            form = await request.form()
            name_raw = form.get("name")
            if not name_raw or not isinstance(name_raw, str) or not name_raw.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="name is required",
                )
            name = name_raw.strip()
            desc_raw = form.get("description")
            description = (
                desc_raw.strip() if isinstance(desc_raw, str) and desc_raw.strip() else None
            )
            meta_raw = form.get("metadata")
            metadata: dict = {}
            if isinstance(meta_raw, str) and meta_raw.strip():
                try:
                    parsed = json.loads(meta_raw)
                    if not isinstance(parsed, dict):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="metadata must be a JSON object",
                        )
                    metadata = parsed
                except json.JSONDecodeError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid metadata JSON",
                    )

            raw_files = form.getlist("files")
            upload_files = [f for f in raw_files if isinstance(f, UploadFile)]
            rel_paths = _parse_optional_file_relative_paths(form.get("file_relative_paths"))
            if rel_paths is not None and len(rel_paths) != len(upload_files):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "file_relative_paths length must match the number of uploaded files "
                        f"({len(rel_paths)} vs {len(upload_files)})."
                    ),
                )

            temp_dir: str | None = None
            try:
                if upload_files:
                    file_tuples, temp_dir = await _persist_multipart_files_to_temp_tuples(
                        upload_files, relative_paths=rel_paths
                    )
                    if not file_tuples:
                        raise ValueError("No valid files provided")
                else:
                    file_tuples = []

                dataset = await dataset_service.create_dataset(
                    org_id=org_id,
                    name=name,
                    description=description,
                    metadata=metadata,
                    files=file_tuples,
                    user_id=user.id,
                )
                return DatasetResponse.model_validate(dataset)
            finally:
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON body",
            )
        try:
            request_model = CreateDatasetRequest.model_validate(body)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            )

        dataset = await dataset_service.create_dataset(
            org_id=org_id,
            name=request_model.name,
            description=request_model.description,
            metadata=request_model.metadata or {},
            files=[],
            user_id=user.id,
        )
        return DatasetResponse.model_validate(dataset)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset: {str(e)}",
        )


@router.get(
    "",
    response_model=ListDatasetsResponse,
    status_code=status.HTTP_200_OK,
    summary="List datasets",
    description="List datasets with pagination and filtering",
)
async def list_datasets(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort order (asc/desc)"),
    name: str | None = Query(None, description="Filter by name (partial match)"),
    created_after: str | None = Query(None, description="Filter by creation date (after)"),
    created_before: str | None = Query(None, description="Filter by creation date (before)"),
    min_cell_count: int | None = Query(None, ge=0, description="Minimum cell count"),
    max_cell_count: int | None = Query(None, ge=0, description="Maximum cell count"),
    file_format: str | None = Query(None, description="Filter by file format"),
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> ListDatasetsResponse:
    """List datasets with pagination and filtering.

    Args:
        page: Page number
        page_size: Items per page
        sort_by: Field to sort by
        sort_order: Sort order
        name: Filter by name
        created_after: Filter by creation date (after)
        created_before: Filter by creation date (before)
        min_cell_count: Minimum cell count
        max_cell_count: Maximum cell count
        file_format: Filter by file format
        user: Current authenticated user
        dataset_service: Dataset service

    Returns:
        Paginated list of datasets

    Raises:
        HTTPException: 403 if user not member of organization
    """
    # Get user's first organization
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    # Build filters
    from datetime import datetime as dt

    filters = DatasetFilters(
        name=name,
        created_after=dt.fromisoformat(created_after) if created_after else None,
        created_before=dt.fromisoformat(created_before) if created_before else None,
        min_cell_count=min_cell_count,
        max_cell_count=max_cell_count,
        file_format=file_format,
    )

    # List datasets
    result = await dataset_service.list_datasets(
        org_id=org_id,
        filters=filters,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return ListDatasetsResponse(
        items=[DatasetResponse.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/versions/{version_id}/columns",
    response_model=DatasetVersionColumnsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dataset version columns",
    description="Inspect a dataset version and return available obs columns for parameter pickers",
)
async def get_dataset_version_columns(
    version_id: UUID,
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetVersionColumnsResponse:
    """Get dataset-version column metadata for run-parameter dropdowns."""
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    try:
        columns = await dataset_service.get_dataset_version_columns(
            dataset_version_id=version_id,
            org_id=org_id,
        )
        return DatasetVersionColumnsResponse.model_validate(columns)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to inspect dataset columns: {str(e)}",
        )


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dataset details",
    description="Get dataset details including all versions",
)
async def get_dataset(
    dataset_id: UUID,
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetResponse:
    """Get dataset details.

    Args:
        dataset_id: Dataset ID
        user: Current authenticated user
        dataset_service: Dataset service

    Returns:
        Dataset details with versions

    Raises:
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if dataset not found
    """
    # Get user's first organization
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    # Get dataset
    dataset = await dataset_service.get_dataset(
        dataset_id=dataset_id, org_id=org_id, include_versions=True
    )

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    return DatasetResponse.model_validate(dataset)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new dataset version",
    description="Create a new version of an existing dataset with file upload",
)
async def create_dataset_version(
    dataset_id: UUID,
    files: list[UploadFile] = File(..., description="Files to upload"),
    file_relative_paths: str | None = Form(
        default=None,
        description='Optional JSON array of relative paths, same order as files (e.g. ["GSM1/matrix.mtx.gz"]).',
    ),
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetVersionResponse:
    """Create a new dataset version.

    Args:
        dataset_id: Dataset ID
        files: Uploaded files
        user: Current authenticated user
        dataset_service: Dataset service

    Returns:
        Created dataset version

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if dataset not found
    """
    # Get user's first organization
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    try:
        rel_paths = _parse_optional_file_relative_paths(file_relative_paths)
        if rel_paths is not None and len(rel_paths) != len(files):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "file_relative_paths length must match the number of uploaded files "
                    f"({len(rel_paths)} vs {len(files)})."
                ),
            )
        file_tuples, temp_dir = await _persist_multipart_files_to_temp_tuples(
            files, relative_paths=rel_paths
        )
        try:
            if not file_tuples:
                raise ValueError("No valid files provided")

            version = await dataset_service.create_version(
                dataset_id=dataset_id,
                org_id=org_id,
                files=file_tuples,
            )

            return DatasetVersionResponse.model_validate(version)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset version: {str(e)}",
        )


@router.put(
    "/{dataset_id}",
    response_model=DatasetResponse,
    status_code=status.HTTP_200_OK,
    summary="Update dataset metadata",
    description="Update dataset name, description, or metadata",
)
async def update_dataset(
    dataset_id: UUID,
    request: UpdateDatasetRequest,
    user: User = Depends(get_current_user),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DatasetResponse:
    """Update dataset metadata.

    Args:
        dataset_id: Dataset ID
        request: Update request
        user: Current authenticated user
        dataset_service: Dataset service

    Returns:
        Updated dataset

    Raises:
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if dataset not found
    """
    # Get user's first organization
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    # Update dataset
    dataset = await dataset_service.update_dataset_metadata(
        dataset_id=dataset_id,
        org_id=org_id,
        name=request.name,
        description=request.description,
        metadata=request.metadata,
        user_id=user.id,
    )

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    return DatasetResponse.model_validate(dataset)


@router.post(
    "/bulk-delete",
    response_model=BulkDeleteDatasetsResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk delete datasets",
    description="Delete selected datasets or all datasets, optionally deleting all associated runs first.",
)
async def bulk_delete_datasets(
    request: BulkDeleteDatasetsRequest,
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache_service),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> BulkDeleteDatasetsResponse:
    """Delete many datasets for the current organization."""
    org_id = await _get_user_org_id(dataset_service, user)

    run_service = RunService(db=dataset_service.db, cache_service=cache)

    if request.scope == "selected":
        dataset_ids = list(dict.fromkeys(request.dataset_ids))
        if not dataset_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select at least one dataset to delete.",
            )
        result = await dataset_service.db.execute(
            select(Dataset.id).where(
                Dataset.organization_id == org_id,
                Dataset.id.in_(dataset_ids),
            )
        )
        available_ids = set(result.scalars().all())
        missing = [dataset_id for dataset_id in dataset_ids if dataset_id not in available_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more selected datasets were not found or do not belong to this organization.",
            )
    else:
        result = await dataset_service.db.execute(
            select(Dataset.id)
            .where(Dataset.organization_id == org_id)
            .order_by(Dataset.created_at.desc())
        )
        dataset_ids = list(result.scalars().all())

    deleted_runs = 0
    preserved_runs = 0
    deleted_dataset_ids: list[UUID] = []

    for dataset_id in dataset_ids:
        deletion = await _delete_dataset_with_run_mode(
            dataset_id=dataset_id,
            request=DeleteDatasetRequest(run_delete_mode=request.run_delete_mode),
            org_id=org_id,
            user_id=user.id,
            dataset_service=dataset_service,
            run_service=run_service,
        )
        deleted_dataset_ids.append(deletion.dataset_id)
        deleted_runs += deletion.deleted_runs
        preserved_runs += deletion.preserved_runs

    return BulkDeleteDatasetsResponse(
        scope=request.scope,
        deleted_dataset_ids=deleted_dataset_ids,
        deleted_datasets=len(deleted_dataset_ids),
        deleted_runs=deleted_runs,
        preserved_runs=preserved_runs,
    )


@router.delete(
    "/{dataset_id}",
    response_model=DeleteDatasetResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete dataset",
    description="Delete a dataset, optionally deleting some or all runs associated with it first.",
)
async def delete_dataset(
    dataset_id: UUID,
    delete_options: DeleteDatasetRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache_service),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> DeleteDatasetResponse | Response:
    """Delete a dataset.

    Args:
        dataset_id: Dataset ID
        user: Current authenticated user
        dataset_service: Dataset service

    Raises:
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if dataset not found
    """
    org_id = await _get_user_org_id(dataset_service, user)
    run_service = RunService(db=dataset_service.db, cache_service=cache)
    deletion = await _delete_dataset_with_run_mode(
        dataset_id=dataset_id,
        request=delete_options or DeleteDatasetRequest(),
        org_id=org_id,
        user_id=user.id,
        dataset_service=dataset_service,
        run_service=run_service,
    )
    if delete_options is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return deletion


@router.get(
    "/{dataset_id}/runs",
    response_model=ListDatasetAssociatedRunsResponse,
    status_code=status.HTTP_200_OK,
    summary="List dataset-associated runs",
    description="List runs associated with one dataset for delete/cleanup flows.",
)
async def list_dataset_runs(
    dataset_id: UUID,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=100, ge=1, le=1000, description="Items per page"),
    user: User = Depends(get_current_user),
    cache: CacheService = Depends(get_cache_service),
    dataset_service: DatasetService = Depends(get_dataset_service),
) -> ListDatasetAssociatedRunsResponse:
    """List runs tied to one dataset."""
    user_orgs = await dataset_service.db.execute(
        text("SELECT organization_id FROM organization_users WHERE user_id = :user_id"),
        {"user_id": user.id},
    )
    org_id = user_orgs.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    dataset = await dataset_service.get_dataset(
        dataset_id=dataset_id, org_id=org_id, include_versions=False
    )
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found",
        )

    offset = (page - 1) * page_size
    run_service = RunService(db=dataset_service.db, cache_service=cache)
    runs, total = await run_service.list_runs(
        org_id=org_id,
        dataset_id=dataset_id,
        limit=page_size,
        offset=offset,
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return ListDatasetAssociatedRunsResponse(
        items=[DatasetAssociatedRunResponse.model_validate(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
