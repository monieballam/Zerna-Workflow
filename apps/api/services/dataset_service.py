"""Dataset service for CRUD operations with file validation and versioning."""

import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from zerna_contracts.dataset_files import (
    detect_10x_bundle_member,
    looks_like_metadata_filename,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.services.audit_service import AuditService
from apps.api.services.cache_service import CacheService
from apps.api.services.file_validation_service import (
    FileValidationService,
    ValidationResult,
)
from apps.api.services.quota_service import QuotaService
from apps.api.services.s3_service import S3Service

CLUSTER_COLUMN_PRIORITY = (
    "leiden",
    "louvain",
    "cluster",
    "Cluster",
    "seurat_clusters",
    "annotation_cell_type",
    "annotation_broad",
    "annotation_label",
    "celltype_level3",
    "zr_display",
    "CellType",
    "cell_type",
    "celltype_display",
)

BATCH_COLUMN_PRIORITY = (
    "orig.ident",
    "orig_ident",
    "batch",
    "Batch",
    "batch_id",
    "sample",
    "Sample",
    "sample_name",
    "sample_id",
    "donor",
    "Donor",
    "patient",
    "Patient",
    "library",
    "library_id",
    "replicate",
    "condition",
    "HashAssignment",
)

PRIMARY_DATA_FILE_FORMATS = {"h5ad", "10x_h5", "10x_mtx", "csv", "tsv"}
_COMPRESSED_SUFFIXES = (".gz", ".bz2")


@dataclass
class _UploadValidationGroup:
    """Represents a set of uploaded files validated as one logical dataset input."""

    upload_files: list[tuple[str, str]]
    validation_path: str
    validation_format: str
    contributes_dataset_shape: bool
    normalized_upload_formats: list[str]


class VersionMetadata(BaseModel):
    """Metadata for creating an immutable dataset version."""

    source_type: Literal["upload", "s3_uri", "merge"] = "upload"
    parent_version_ids: list[UUID] = Field(default_factory=list)
    schema_summary: dict[str, Any] = Field(default_factory=dict)
    uploaded_by: UUID
    checksum: str | None = None  # If None, computed from file_refs


class DatasetFilters(BaseModel):
    """Filters for listing datasets."""

    name: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    min_cell_count: int | None = None
    max_cell_count: int | None = None
    file_format: str | None = None


class Page(BaseModel):
    """Paginated response."""

    items: list
    total: int
    page: int
    page_size: int
    total_pages: int


def _normalize_upload_files(
    files: Sequence[tuple[str, str] | tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Coerce upload tuples to (local_path, ext, s3_object_suffix).

    Legacy callers pass (path, ext) only; suffix defaults to the path basename. New uploads include
    an explicit suffix (often a nested relative key such as ``GSM123/matrix.mtx.gz``).
    """
    out: list[tuple[str, str, str]] = []
    for item in files:
        if len(item) == 2:
            fp, ext = item
            out.append((fp, ext, Path(fp).name.replace("\\", "/")))
        else:
            fp, ext, suf = item
            out.append((fp, ext, str(suf).replace("\\", "/")))
    return out


def _ordered_unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _candidate_columns(columns: list[str], preferred: tuple[str, ...]) -> list[str]:
    column_lookup = {column.lower(): column for column in columns}
    ordered = [column_lookup[key.lower()] for key in preferred if key.lower() in column_lookup]
    return _ordered_unique_strings(ordered)


def _normalize_uploaded_file_format(path: str, file_format: str) -> str:
    """Normalize per-file formats so dataset metadata reflects the logical input type."""
    role, _, _ = detect_10x_bundle_member(path)
    if role is not None:
        return "10x_mtx"

    name = Path(path).name.lower()
    stripped = name
    while True:
        matched = False
        for suffix in _COMPRESSED_SUFFIXES:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                matched = True
                break
        if not matched:
            break

    if stripped.endswith(".h5ad"):
        return "h5ad"
    if stripped.endswith(".h5"):
        return "10x_h5"
    if stripped.endswith(".mtx"):
        return "10x_mtx"
    if stripped.endswith(".csv"):
        return "csv"
    if stripped.endswith((".tsv", ".tab")):
        return "tsv"
    if stripped.endswith(".txt"):
        return "txt"

    normalized = file_format.lower().strip()
    if normalized == "mtx":
        return "10x_mtx"
    if normalized == "h5":
        return "10x_h5"
    if normalized == "tab":
        return "tsv"
    return normalized


def _contributes_dataset_shape(path: str, normalized_format: str) -> bool:
    """Return whether a file should contribute dataset-level cell/gene counts."""
    return normalized_format in PRIMARY_DATA_FILE_FORMATS and not looks_like_metadata_filename(path)


def _validation_format_for_upload(path: str, normalized_format: str) -> str:
    """Return the parser format to use for upload validation.

    Sidecar metadata files such as ``meta.txt`` should keep their recorded upload
    format (for dataset metadata) while still being validated as tabular text.
    """
    if normalized_format == "txt" and looks_like_metadata_filename(path):
        return "tsv"
    return normalized_format


class DatasetService:
    """Service for dataset CRUD operations with file validation and versioning."""

    def __init__(
        self,
        db: AsyncSession,
        s3_service: S3Service | None = None,
        file_validation_service: FileValidationService | None = None,
        quota_service: QuotaService | None = None,
        cache_service: CacheService | None = None,
        audit_service: AuditService | None = None,
    ):
        """Initialize DatasetService.

        Args:
            db: Database session
            s3_service: S3 service for file storage (optional, created if not provided)
            file_validation_service: File validation service (optional, created if not provided)
            quota_service: Quota service for storage enforcement (optional, created if not provided)
            cache_service: Cache service for Redis caching (optional, no caching if not provided)
            audit_service: Audit service for compliance logging (optional, created if not provided)
        """
        self.db = db
        self.s3_service = s3_service or S3Service()
        self.file_validation_service = file_validation_service or FileValidationService()
        self.quota_service = quota_service or QuotaService(db)
        self.cache = cache_service
        self.audit = audit_service or AuditService(db)

    def _build_upload_validation_groups(
        self, files: list[tuple[str, str, str]]
    ) -> tuple[list[_UploadValidationGroup], list[str]]:
        """Group uploaded files into logical validation units."""
        groups: list[_UploadValidationGroup] = []
        cleanup_paths: list[str] = []
        tenx_candidates: dict[str, dict[str, tuple[tuple[str, str], str]]] = {}
        passthrough_files: list[tuple[str, str]] = []

        for file_path, file_format, _suffix in files:
            role, prefix, canonical_name = detect_10x_bundle_member(file_path)
            if role is None:
                passthrough_files.append((file_path, file_format))
                continue

            bundle_key = prefix or "__default__"
            bundle = tenx_candidates.setdefault(bundle_key, {})
            if role in bundle:
                raise ValueError(
                    f"Duplicate 10x bundle component '{role}' detected for prefix "
                    f"'{prefix or '<root>'}'."
                )
            bundle[role] = ((file_path, file_format), canonical_name)

        has_any_matrix = any("matrix" in bundle for bundle in tenx_candidates.values())
        if has_any_matrix:
            for prefix, bundle in tenx_candidates.items():
                missing = [role for role in ("matrix", "genes", "barcodes") if role not in bundle]
                if missing:
                    raise ValueError(
                        "Incomplete 10x MTX upload for prefix "
                        f"'{prefix if prefix != '__default__' else '<root>'}': missing "
                        f"{', '.join(missing)}"
                    )

                bundle_dir = tempfile.mkdtemp(prefix="zerna_10x_bundle_")
                cleanup_paths.append(bundle_dir)
                bundle_files: list[tuple[str, str]] = []

                for role in ("matrix", "genes", "barcodes"):
                    (member, canonical_name) = bundle[role]
                    shutil.copy2(member[0], Path(bundle_dir) / canonical_name)
                    bundle_files.append(member)

                groups.append(
                    _UploadValidationGroup(
                        upload_files=bundle_files,
                        validation_path=bundle_dir,
                        validation_format="10x_mtx",
                        contributes_dataset_shape=True,
                        normalized_upload_formats=["10x_mtx"] * len(bundle_files),
                    )
                )
        else:
            passthrough_files.extend(
                member for bundle in tenx_candidates.values() for member, _ in bundle.values()
            )

        for file_path, file_format in passthrough_files:
            normalized_format = _normalize_uploaded_file_format(file_path, file_format)
            validation_format = _validation_format_for_upload(file_path, normalized_format)
            groups.append(
                _UploadValidationGroup(
                    upload_files=[(file_path, file_format)],
                    validation_path=file_path,
                    validation_format=validation_format,
                    contributes_dataset_shape=_contributes_dataset_shape(
                        file_path, normalized_format
                    ),
                    normalized_upload_formats=[normalized_format],
                )
            )

        return groups, cleanup_paths

    async def _validate_upload_groups(
        self, files: list[tuple[str, str, str]]
    ) -> list[tuple[_UploadValidationGroup, ValidationResult]]:
        """Validate uploaded files after grouping bundle inputs."""
        groups, cleanup_paths = self._build_upload_validation_groups(files)
        try:
            validation_results: list[tuple[_UploadValidationGroup, ValidationResult]] = []
            for group in groups:
                result = await self.file_validation_service.validate_file(
                    group.validation_path,
                    group.validation_format,
                )
                if not result.is_valid:
                    source = ", ".join(
                        Path(file_path).name for file_path, _fmt in group.upload_files
                    )
                    raise ValueError(f"File validation failed for {source}: {result.error_message}")
                validation_results.append((group, result))
            return validation_results
        finally:
            for cleanup_path in cleanup_paths:
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(cleanup_path, ignore_errors=True)

    async def create_dataset(
        self,
        org_id: UUID,
        name: str,
        description: str | None,
        metadata: dict,
        files: Sequence[tuple[str, str] | tuple[str, str, str]],
        user_id: UUID | None = None,
    ) -> Dataset:
        """Create a new dataset with file validation and initial version.

        Args:
            org_id: Organization ID
            name: Dataset name
            description: Dataset description
            metadata: Additional metadata
            files: List of tuples (file_path, file_format) to validate and upload

        Returns:
            Created Dataset with initial version

        Raises:
            ValueError: If file validation fails
            RuntimeError: If S3 upload fails
        """
        normalized_files = _normalize_upload_files(files)
        # Validate all files first
        validation_results = await self._validate_upload_groups(normalized_files)

        # Estimate total upload size and check storage quota
        import os

        total_upload_bytes = sum(
            os.path.getsize(fp) for fp, _, _s in normalized_files if os.path.exists(fp)
        )
        await self.quota_service.check_storage_quota(org_id, additional_bytes=total_upload_bytes)

        # Create dataset
        dataset = Dataset(
            id=uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            extra_metadata=metadata,
            created_at=datetime.utcnow(),
        )

        self.db.add(dataset)
        await self.db.flush()  # Get dataset ID without committing

        # Create initial version (v1) only if files are provided
        if normalized_files:
            version = await self._create_version_internal(
                dataset.id, "v1", normalized_files, validation_results
            )

        await self.db.commit()
        await self.db.refresh(dataset, attribute_names=["versions"])
        if normalized_files:
            await self.db.refresh(version)

        # Audit: dataset created
        await self.audit.audit_log(
            org_id=org_id,
            user_id=user_id or org_id,  # fallback when caller doesn't supply user_id
            action_type="dataset.create",
            resource_type="dataset",
            resource_id=dataset.id,
            after_state={"name": dataset.name, "description": dataset.description},
        )
        await self.db.commit()

        # Invalidate dataset list cache for this org
        if self.cache:
            await self.cache.invalidate_dataset(str(org_id), str(dataset.id))

        return dataset

    async def _create_version_internal(
        self,
        dataset_id: UUID,
        version_name: str,
        files: list[tuple[str, str, str]],
        validation_results: list[tuple[_UploadValidationGroup, ValidationResult]],
    ) -> DatasetVersion:
        """Internal method to create a dataset version.

        Args:
            dataset_id: Dataset ID
            version_name: Version name (e.g., "v1", "v2")
            files: List of tuples (file_path, file_format)
            validation_results: Logical validation results for the uploaded files

        Returns:
            Created DatasetVersion

        Raises:
            RuntimeError: If S3 upload fails
        """
        # Get dataset to access organization_id
        stmt = select(Dataset).where(Dataset.id == dataset_id)
        result = await self.db.execute(stmt)
        dataset = result.scalar_one()

        # Generate S3 paths and upload files
        s3_paths = []
        total_cell_count = 0
        total_gene_count = 0
        normalized_file_formats: list[str] = []

        for file_path, _, object_suffix in files:
            s3_path = self.s3_service.generate_dataset_path(
                dataset.organization_id, dataset_id, object_suffix
            )

            # Upload to S3
            from pathlib import Path

            self.s3_service.upload_file(
                Path(file_path),
                self.s3_service.datasets_bucket,
                s3_path,
            )

            s3_paths.append(s3_path)

        def _common_s3_prefix(paths: list[str]) -> str | None:
            """Return common directory prefix (ending in '/'), if any."""
            if not paths:
                return None
            # Use dirname so we don't mix on filenames.
            dirs = [p.rsplit("/", 1)[0] + "/" if "/" in p else "" for p in paths]
            prefix = os.path.commonprefix(dirs)
            if not prefix:
                return None
            # Ensure we cut back to a directory boundary.
            if not prefix.endswith("/"):
                prefix = prefix.rsplit("/", 1)[0] + "/"
            return prefix

        for validation_group, validation_result in validation_results:
            normalized_file_formats.extend(validation_group.normalized_upload_formats)
            if validation_group.contributes_dataset_shape and validation_result.metadata:
                total_cell_count += validation_result.metadata.cell_count
                total_gene_count = max(total_gene_count, validation_result.metadata.gene_count)

        primary_file_formats = _ordered_unique_strings(
            [
                normalized_format
                for validation_group, _ in validation_results
                if validation_group.contributes_dataset_shape
                for normalized_format in validation_group.normalized_upload_formats
            ]
        )
        if len(primary_file_formats) == 1:
            version_file_format = primary_file_formats[0]
        elif len(primary_file_formats) > 1:
            version_file_format = "mixed"
        else:
            unique_formats = _ordered_unique_strings(normalized_file_formats)
            version_file_format = unique_formats[0] if len(unique_formats) == 1 else "mixed"

        # Create version
        # NOTE: `dataset_versions.s3_path` is bounded (VARCHAR(1024)). For multi-file uploads
        # (e.g. 10x MTX), store the *primary* object path here and keep the full list in metadata.
        primary_s3_path = s3_paths[0] if s3_paths else ""
        if len(primary_s3_path) > 1024:
            raise ValueError("Generated dataset s3_path exceeds 1024 characters.")

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset_id,
            version=version_name,
            s3_path=primary_s3_path,
            cell_count=total_cell_count if total_cell_count > 0 else None,
            gene_count=total_gene_count if total_gene_count > 0 else None,
            file_format=version_file_format,
            extra_metadata={
                "file_count": len(files),
                "s3_paths": s3_paths,
                "s3_prefix": _common_s3_prefix(s3_paths),
                "file_formats": normalized_file_formats,
            },
            created_at=datetime.utcnow(),
        )

        self.db.add(version)
        return version

    async def get_dataset(
        self, dataset_id: UUID, org_id: UUID, include_versions: bool = True
    ) -> Dataset | None:
        """Get a dataset by ID with organization scoping.

        Caches the result for CacheTTL.DATASET_SUMMARY seconds.

        Args:
            dataset_id: Dataset ID
            org_id: Organization ID for scoping
            include_versions: Whether to load versions relationship

        Returns:
            Dataset if found and belongs to organization, None otherwise
        """
        stmt = select(Dataset).where(
            and_(Dataset.id == dataset_id, Dataset.organization_id == org_id)
        )

        if include_versions:
            # joinedload is more efficient for single-row fetches
            stmt = stmt.options(joinedload(Dataset.versions).joinedload(DatasetVersion.runs))

        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_dataset_version_columns(
        self,
        dataset_version_id: UUID,
        org_id: UUID,
    ) -> dict[str, Any]:
        """Return dataset-version obs columns for parameter pickers.

        Column metadata is cached on the dataset-version record after the first lookup.
        """
        stmt = (
            select(DatasetVersion)
            .join(DatasetVersion.dataset)
            .where(
                and_(
                    DatasetVersion.id == dataset_version_id,
                    DatasetVersion.dataset.has(organization_id=org_id),
                )
            )
        )
        result = await self.db.execute(stmt)
        version = result.scalar_one_or_none()
        if version is None:
            raise ValueError(
                f"Dataset version {dataset_version_id} not found or does not belong to organization {org_id}"
            )

        metadata = dict(version.extra_metadata or {})
        cached_obs_columns = metadata.get("obs_columns")
        cached_batch_candidates = metadata.get("batch_candidates")
        cached_cluster_candidates = metadata.get("cluster_candidates")
        cached_source = metadata.get("column_metadata_source")
        if (
            isinstance(cached_obs_columns, list)
            and isinstance(cached_batch_candidates, list)
            and isinstance(cached_cluster_candidates, list)
            and isinstance(cached_source, str)
            and (
                cached_source != "generated_only"
                or bool(cached_obs_columns)
                or bool(cached_batch_candidates)
            )
        ):
            return {
                "dataset_version_id": version.id,
                "obs_columns": [str(column) for column in cached_obs_columns],
                "batch_candidates": [str(column) for column in cached_batch_candidates],
                "cluster_candidates": [str(column) for column in cached_cluster_candidates],
                "source": cached_source,
            }

        obs_columns, source = self._inspect_dataset_version_obs_columns(version)
        batch_candidates = _candidate_columns(obs_columns, BATCH_COLUMN_PRIORITY)
        cluster_candidates = _ordered_unique_strings(
            [*_candidate_columns(obs_columns, CLUSTER_COLUMN_PRIORITY), "leiden", "louvain"]
        )

        metadata.update(
            {
                "obs_columns": obs_columns,
                "batch_candidates": batch_candidates,
                "cluster_candidates": cluster_candidates,
                "column_metadata_source": source,
            }
        )
        version.extra_metadata = metadata
        await self.db.commit()

        return {
            "dataset_version_id": version.id,
            "obs_columns": obs_columns,
            "batch_candidates": batch_candidates,
            "cluster_candidates": cluster_candidates,
            "source": source,
        }

    def _inspect_dataset_version_obs_columns(
        self, version: DatasetVersion
    ) -> tuple[list[str], str]:
        """Inspect dataset-version files to discover available obs columns."""
        s3_paths = version.extra_metadata.get("s3_paths")
        if not isinstance(s3_paths, list) or not s3_paths:
            s3_paths = [path.strip() for path in str(version.s3_path).split(",") if path.strip()]

        if not s3_paths:
            return [], "unavailable"

        metadata_path = next(
            (path for path in s3_paths if looks_like_metadata_filename(path)),
            None,
        )
        if metadata_path is not None:
            local_path: str | None = None
            try:
                local_path = self._download_dataset_path(metadata_path)
                return self._read_metadata_columns(local_path), "metadata_file"
            except Exception:
                pass
            finally:
                if local_path is not None:
                    with contextlib.suppress(FileNotFoundError):
                        Path(local_path).unlink()

        h5ad_path = next((path for path in s3_paths if path.lower().endswith(".h5ad")), None)
        if h5ad_path is not None:
            local_path = None
            try:
                local_path = self._download_dataset_path(h5ad_path)
                return self._read_h5ad_obs_columns(local_path), "h5ad_obs"
            except Exception:
                pass
            finally:
                if local_path is not None:
                    with contextlib.suppress(FileNotFoundError):
                        Path(local_path).unlink()

        return [], "generated_only"

    def _download_dataset_path(self, s3_path: str) -> str:
        """Download a dataset object to a temporary local file and return its path."""
        target = Path(tempfile.mkdtemp(prefix="zerna_dataset_columns_")) / os.path.basename(s3_path)
        self.s3_service.s3_client.download_file(
            self.s3_service.datasets_bucket,
            s3_path,
            str(target),
        )
        return str(target)

    @staticmethod
    def _read_metadata_columns(local_path: str) -> list[str]:
        """Read metadata columns from a TSV/CSV metadata file."""
        import pandas as pd

        path = Path(local_path)
        name = path.name.lower()
        sep = (
            "\t"
            if name.endswith(".txt") or name.endswith(".tsv") or name.endswith(".tsv.gz")
            else ","
        )
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                frame = pd.read_csv(path, sep=sep, index_col=0, encoding=encoding)
                return _ordered_unique_strings([str(column) for column in frame.columns])
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise ValueError(f"Could not read metadata file: {path}")

    @staticmethod
    def _read_h5ad_obs_columns(local_path: str) -> list[str]:
        """Read obs columns from an H5AD file without loading the full matrix eagerly."""
        import anndata as ad

        adata = ad.read_h5ad(local_path, backed="r")
        try:
            return _ordered_unique_strings([str(column) for column in adata.obs.columns])
        finally:
            if getattr(adata, "file", None) is not None:
                adata.file.close()

    async def list_datasets(
        self,
        org_id: UUID,
        filters: DatasetFilters | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Page:
        """List datasets with pagination and filtering.

        Args:
            org_id: Organization ID for scoping
            filters: Optional filters to apply
            page: Page number (1-indexed)
            page_size: Number of items per page
            sort_by: Field to sort by (created_at, name)
            sort_order: Sort order (asc, desc)

        Returns:
            Paginated list of datasets
        """
        # Base query with organization scoping
        stmt = select(Dataset).where(Dataset.organization_id == org_id)

        # Apply filters
        if filters:
            if filters.name:
                stmt = stmt.where(Dataset.name.ilike(f"%{filters.name}%"))

            if filters.created_after:
                stmt = stmt.where(Dataset.created_at >= filters.created_after)

            if filters.created_before:
                stmt = stmt.where(Dataset.created_at <= filters.created_before)

            # For cell count and file format filters, we need to join with versions
            if filters.min_cell_count or filters.max_cell_count or filters.file_format:
                stmt = stmt.join(DatasetVersion)

                if filters.min_cell_count:
                    stmt = stmt.where(DatasetVersion.cell_count >= filters.min_cell_count)

                if filters.max_cell_count:
                    stmt = stmt.where(DatasetVersion.cell_count <= filters.max_cell_count)

                if filters.file_format:
                    stmt = stmt.where(DatasetVersion.file_format == filters.file_format)

                # Ensure distinct datasets
                stmt = stmt.distinct()

        # Count total items
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar() or 0)

        # Apply sorting
        if sort_by == "name":
            sort_column: Any = Dataset.name
        else:  # default to created_at
            sort_column = Dataset.created_at

        if sort_order.lower() == "asc":
            stmt = stmt.order_by(sort_column.asc())
        else:
            stmt = stmt.order_by(sort_column.desc())

        # Apply pagination
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        # Load versions relationship
        stmt = stmt.options(selectinload(Dataset.versions))

        # Execute query
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size

        return Page(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def create_version(
        self,
        dataset_id: UUID,
        org_id: UUID,
        files: Sequence[tuple[str, str] | tuple[str, str, str]],
    ) -> DatasetVersion:
        """Create a new version for an existing dataset.

        Args:
            dataset_id: Dataset ID
            org_id: Organization ID for scoping
            files: List of tuples (file_path, file_format) to validate and upload

        Returns:
            Created DatasetVersion

        Raises:
            ValueError: If dataset not found, file validation fails, or org mismatch
            RuntimeError: If S3 upload fails
        """
        normalized_files = _normalize_upload_files(files)
        # Get dataset with organization scoping
        dataset = await self.get_dataset(dataset_id, org_id, include_versions=True)
        if dataset is None:
            raise ValueError(
                f"Dataset {dataset_id} not found or does not belong to organization {org_id}"
            )

        # Validate all files first
        validation_results = await self._validate_upload_groups(normalized_files)

        # Estimate total upload size and check storage quota
        import os

        total_upload_bytes = sum(
            os.path.getsize(fp) for fp, _, _s in normalized_files if os.path.exists(fp)
        )
        await self.quota_service.check_storage_quota(
            dataset.organization_id, additional_bytes=total_upload_bytes
        )

        # Determine next version number by querying database directly
        # (don't rely on relationship which may be stale)
        stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        result = await self.db.execute(stmt)
        existing_versions = result.scalars().all()

        version_numbers = []
        for v in existing_versions:
            # Extract number from version string (e.g., "v1" -> 1)
            try:
                num = int(v.version.lstrip("v"))
                version_numbers.append(num)
            except ValueError:
                pass

        next_version_num = max(version_numbers, default=0) + 1
        version_name = f"v{next_version_num}"

        # Create version
        version = await self._create_version_internal(
            dataset_id, version_name, normalized_files, validation_results
        )

        await self.db.commit()
        await self.db.refresh(version)

        # Invalidate cached dataset entry
        if self.cache:
            await self.cache.invalidate_dataset(str(dataset.organization_id), str(dataset_id))

        return version

    async def create_immutable_version(
        self,
        dataset_id: UUID,
        file_refs: list[str],
        metadata: "VersionMetadata",
        org_id: UUID | None = None,
    ) -> DatasetVersion:
        """Create an immutable dataset version with checksum, lineage, and schema summary.

        This is the primary interface for the DatasetVersionService described in the
        design document.  Every version produced is immutable — once created, its
        checksum, lineage, and schema summary cannot be changed.

        Args:
            dataset_id: ID of the parent dataset.
            file_refs: S3 keys (or URIs) that make up this version.
            metadata: ``VersionMetadata`` with source_type, parent_version_ids,
                schema_summary, uploaded_by, and optional pre-computed checksum.
            org_id: Organization ID for scoping (optional — looked up from dataset
                if not provided).

        Returns:
            The newly created ``DatasetVersion`` row.

        Raises:
            ValueError: If the dataset does not exist, or if a merge version has
                empty ``parent_version_ids``.
        """
        # Validate merge lineage
        if metadata.source_type == "merge" and not metadata.parent_version_ids:
            raise ValueError("Merge-sourced versions must have non-empty parent_version_ids")

        # Look up the dataset (and its org_id if not supplied)
        stmt = select(Dataset).where(Dataset.id == dataset_id)
        if org_id is not None:
            stmt = stmt.where(Dataset.organization_id == org_id)
        result = await self.db.execute(stmt)
        dataset = result.scalar_one_or_none()
        if dataset is None:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Determine next version number
        ver_stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        ver_result = await self.db.execute(ver_stmt)
        existing = ver_result.scalars().all()

        version_numbers: list[int] = []
        for v in existing:
            try:
                version_numbers.append(int(v.version.lstrip("v")))
            except ValueError:
                pass
        next_num = max(version_numbers, default=0) + 1

        # Compute checksum if not provided
        checksum = metadata.checksum
        if checksum is None:
            # Deterministic checksum from the sorted file refs
            digest = hashlib.sha256()
            for ref in sorted(file_refs):
                digest.update(ref.encode())
            checksum = digest.hexdigest()

        now = datetime.now(UTC)

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset_id,
            version=f"v{next_num}",
            s3_path=file_refs[0] if file_refs else "",
            file_format=None,
            extra_metadata={
                "file_refs": file_refs,
            },
            created_at=now,
            # Lineage fields
            checksum=checksum,
            source_type=metadata.source_type,
            parent_version_ids=[str(pid) for pid in metadata.parent_version_ids],
            schema_summary=metadata.schema_summary,
            uploaded_by=metadata.uploaded_by,
        )

        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)

        # Invalidate cache
        if self.cache:
            await self.cache.invalidate_dataset(str(dataset.organization_id), str(dataset_id))

        return version

    async def delete_dataset(
        self, dataset_id: UUID, org_id: UUID, user_id: UUID | None = None
    ) -> bool:
        """Delete a dataset and all its versions.

        Args:
            dataset_id: Dataset ID
            org_id: Organization ID for scoping

        Returns:
            True if deleted, False if not found

        Note:
            Dataset versions and their source files are deleted here. Runs are
            preserved by the API layer unless explicitly deleted first.
        """
        # Get dataset with organization scoping
        dataset = await self.get_dataset(dataset_id, org_id, include_versions=True)
        if dataset is None:
            return False

        before_state = {"name": dataset.name, "description": dataset.description}

        # Delete S3 files for all versions
        for version in dataset.versions:
            s3_paths = version.extra_metadata.get("s3_paths", [version.s3_path])
            for s3_path in s3_paths:
                try:
                    self.s3_service.delete_file(self.s3_service.datasets_bucket, s3_path)
                except Exception:
                    # Log error but continue deletion
                    pass

        # Delete dataset (cascade will delete versions)
        await self.db.delete(dataset)
        await self.db.commit()

        # Audit: dataset deleted
        await self.audit.audit_log(
            org_id=org_id,
            user_id=user_id or org_id,
            action_type="dataset.delete",
            resource_type="dataset",
            resource_id=dataset_id,
            before_state=before_state,
        )
        await self.db.commit()

        # Invalidate cache
        if self.cache:
            await self.cache.invalidate_dataset(str(org_id), str(dataset_id))

        return True

    async def update_dataset_metadata(
        self,
        dataset_id: UUID,
        org_id: UUID,
        name: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
        user_id: UUID | None = None,
    ) -> Dataset | None:
        """Update dataset metadata.

        Args:
            dataset_id: Dataset ID
            org_id: Organization ID for scoping
            name: New name (optional)
            description: New description (optional)
            metadata: New metadata (optional, will be merged with existing)

        Returns:
            Updated Dataset if found, None otherwise
        """
        dataset = await self.get_dataset(dataset_id, org_id, include_versions=False)
        if dataset is None:
            return None

        before_state = {"name": dataset.name, "description": dataset.description}

        if name is not None:
            dataset.name = name

        if description is not None:
            dataset.description = description

        if metadata is not None:
            # Merge with existing metadata
            dataset.extra_metadata = {**dataset.extra_metadata, **metadata}

        await self.db.commit()
        await self.db.refresh(dataset, attribute_names=["versions"])

        # Audit: dataset updated
        await self.audit.audit_log(
            org_id=org_id,
            user_id=user_id or org_id,
            action_type="dataset.update",
            resource_type="dataset",
            resource_id=dataset.id,
            before_state=before_state,
            after_state={"name": dataset.name, "description": dataset.description},
        )
        await self.db.commit()

        # Invalidate cache
        if self.cache:
            await self.cache.invalidate_dataset(str(org_id), str(dataset_id))

        return dataset
