"""Upload service for multipart file upload and S3 URI registration.

Accepts h5ad, 10x mtx, 10x h5, csv, tsv formats via multipart upload
and s3:// URI registration without browser upload.
"""

import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from apps.api.services.file_validation_service import FileValidationService
from apps.api.services.s3_service import S3Service

# Supported file extensions for upload
SUPPORTED_EXTENSIONS: set[str] = {"h5ad", "mtx", "h5", "csv", "tsv", "txt", "tab"}

# Map file extensions to validation format identifiers
EXTENSION_TO_FORMAT: dict[str, str] = {
    "h5ad": "h5ad",
    "mtx": "10x_mtx",
    "h5": "10x_h5",
    "csv": "csv",
    "tsv": "tsv",
    "txt": "tsv",
    "tab": "tsv",
}


class UploadMetadata(BaseModel):
    """Metadata provided with an upload request."""

    dataset_id: UUID
    organization_id: UUID
    uploaded_by: UUID
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class UploadResult(BaseModel):
    """Result of a successful file upload or URI registration."""

    id: UUID
    dataset_id: UUID
    version_number: int
    checksum: str
    file_refs: list[str]
    source_type: Literal["upload", "s3_uri"]
    schema_summary: dict[str, Any]
    uploaded_by: UUID
    created_at: datetime


def _extract_extension(filename: str) -> str:
    """Extract the file extension from a filename, lowercased.

    Args:
        filename: The original filename.

    Returns:
        Lowercase extension without the dot.
    """
    name = Path(filename).name.lower()
    stripped = name
    for suffix in (".gz", ".bz2"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break

    for ext in ("h5ad", "mtx", "h5", "csv", "tsv", "txt", "tab"):
        if stripped.endswith(f".{ext}"):
            return ext

    if "." not in stripped:
        return ""
    return stripped.rsplit(".", 1)[-1].lower()


def _compute_checksum(file_path: Path) -> str:
    """Compute SHA-256 checksum of a file.

    Args:
        file_path: Path to the file.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class UploadService:
    """Service for uploading files and registering S3 URIs as dataset versions."""

    def __init__(
        self,
        s3_service: S3Service,
        file_validation_service: FileValidationService | None = None,
    ) -> None:
        """Initialize UploadService.

        Args:
            s3_service: S3 service for object storage operations.
            file_validation_service: Optional file validation service.
        """
        self.s3_service = s3_service
        self.file_validation_service = file_validation_service or FileValidationService()

    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        metadata: UploadMetadata,
        version_number: int = 1,
    ) -> UploadResult:
        """Upload a file via multipart upload, validate, and persist to S3.

        Args:
            file_content: Raw bytes of the uploaded file.
            filename: Original filename (used for extension detection).
            metadata: Upload metadata including dataset_id, org_id, user.
            version_number: Version number for this upload.

        Returns:
            UploadResult with file reference and checksum.

        Raises:
            ValueError: If the file extension is not supported or validation fails.
        """
        tmp_dir = tempfile.mkdtemp(prefix="zerna_upload_")
        tmp_path = Path(tmp_dir) / Path(filename).name
        try:
            tmp_path.write_bytes(file_content)
            return await self.upload_path(
                local_path=tmp_path,
                filename=filename,
                metadata=metadata,
                version_number=version_number,
            )
        finally:
            # Clean up temp files
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def upload_path(
        self,
        local_path: str | Path,
        filename: str,
        metadata: UploadMetadata,
        version_number: int = 1,
    ) -> UploadResult:
        """Validate and upload an existing local file path to S3."""
        ext = _extract_extension(filename)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format: '.{ext}'. "
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        source_path = Path(local_path)
        if not source_path.exists():
            raise ValueError(f"File not found: {source_path}")

        # Validate file
        fmt = EXTENSION_TO_FORMAT[ext]
        validation = await self.file_validation_service.validate_file(source_path, fmt)
        if not validation.is_valid:
            raise ValueError(f"File validation failed for '{filename}': {validation.error_message}")

        # Compute checksum
        checksum = _compute_checksum(source_path)

        # Upload to S3
        safe_filename = Path(filename).name
        s3_key = self.s3_service.generate_dataset_path(
            metadata.organization_id, metadata.dataset_id, safe_filename
        )
        self.s3_service.upload_file(
            source_path,
            self.s3_service.datasets_bucket,
            s3_key,
        )

        # Build schema summary from validation metadata
        schema_summary: dict[str, Any] = {}
        if validation.metadata:
            schema_summary = {
                "cell_count": validation.metadata.cell_count,
                "gene_count": validation.metadata.gene_count,
                "format": validation.metadata.format,
                **validation.metadata.additional_metadata,
            }

        return UploadResult(
            id=uuid4(),
            dataset_id=metadata.dataset_id,
            version_number=version_number,
            checksum=checksum,
            file_refs=[s3_key],
            source_type="upload",
            schema_summary=schema_summary,
            uploaded_by=metadata.uploaded_by,
            created_at=datetime.now(UTC),
        )

    async def register_uri(
        self,
        uri: str,
        metadata: UploadMetadata,
        version_number: int = 1,
    ) -> UploadResult:
        """Register an S3 URI as a dataset version without browser upload.

        The file already exists in S3; this method validates the URI format
        and registers it as a dataset version reference.

        Args:
            uri: S3 URI (must start with ``s3://``).
            metadata: Upload metadata including dataset_id, org_id, user.
            version_number: Version number for this registration.

        Returns:
            UploadResult with the S3 URI as file reference.

        Raises:
            ValueError: If the URI is not a valid ``s3://`` path.
        """
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: '{uri}'. URI must start with 's3://'.")

        # Parse bucket and key from URI
        path_part = uri[len("s3://") :]
        if "/" not in path_part or not path_part.split("/", 1)[1]:
            raise ValueError(f"Invalid S3 URI: '{uri}'. URI must include a bucket and object key.")

        # Validate extension from the URI key
        key = path_part.split("/", 1)[1]
        ext = _extract_extension(key)
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format in URI: '.{ext}'. "
                f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        # Use a deterministic checksum placeholder for URI registrations
        checksum = hashlib.sha256(uri.encode()).hexdigest()

        return UploadResult(
            id=uuid4(),
            dataset_id=metadata.dataset_id,
            version_number=version_number,
            checksum=checksum,
            file_refs=[uri],
            source_type="s3_uri",
            schema_summary={"uri": uri, "format": ext},
            uploaded_by=metadata.uploaded_by,
            created_at=datetime.now(UTC),
        )
