"""Property-based tests for upload service file format acceptance.

# Feature: gap-analysis-and-verification, Property 1: File upload accepts all supported formats

**Validates: Requirements 1.1**
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.api.services.upload_service import (
    SUPPORTED_EXTENSIONS,
    UploadMetadata,
    UploadService,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

supported_extension = st.sampled_from(sorted(SUPPORTED_EXTENSIONS))

unsupported_extension = st.text(
    min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
).filter(lambda e: e not in SUPPORTED_EXTENSIONS)

valid_filename_with_ext = st.builds(
    lambda name, ext: f"{name}.{ext}",
    name=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-"),
    ext=supported_extension,
)

invalid_filename_with_ext = st.builds(
    lambda name, ext: f"{name}.{ext}",
    name=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-"),
    ext=unsupported_extension,
)


def _make_metadata() -> UploadMetadata:
    """Create a valid UploadMetadata for testing."""
    return UploadMetadata(
        dataset_id=uuid4(),
        organization_id=uuid4(),
        uploaded_by=uuid4(),
    )


def _mock_upload_service() -> UploadService:
    """Create an UploadService with mocked S3 and validation backends.

    The S3 service is mocked so no real uploads happen.
    The file validation service is mocked to return valid results for
    supported formats, letting us test the upload service's own
    format-gating logic in isolation.
    """
    mock_s3 = MagicMock()
    mock_s3.datasets_bucket = "test-bucket"
    mock_s3.generate_dataset_path = MagicMock(return_value="org/dataset/file.h5ad")
    mock_s3.upload_file = MagicMock(return_value={"etag": "abc", "size": 100, "checksum": "sha"})

    from apps.api.services.file_validation_service import FileMetadata, ValidationResult

    mock_validator = AsyncMock()
    mock_validator.validate_file = AsyncMock(
        return_value=ValidationResult(
            is_valid=True,
            metadata=FileMetadata(cell_count=100, gene_count=50, format="h5ad"),
        )
    )

    return UploadService(s3_service=mock_s3, file_validation_service=mock_validator)


class TestUploadFileFormatAcceptance:
    """Property 1: File upload accepts all supported formats.

    For any file with extension in {h5ad, mtx, h5, csv, tsv}, the upload
    service should accept the file and persist it to object storage,
    returning a valid file reference.

    For any file with an unsupported extension, the upload service should
    reject it with a validation error.
    """

    @pytest.mark.asyncio
    @given(filename=valid_filename_with_ext)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_supported_formats_accepted(self, filename: str) -> None:
        """For any file with a supported extension, upload_file must succeed
        and return a result with a non-empty file_refs list and a valid checksum.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()
        content = b"fake file content for testing"

        result = await svc.upload_file(
            file_content=content,
            filename=filename,
            metadata=metadata,
        )

        # The upload must succeed
        assert result is not None
        assert result.source_type == "upload"
        assert len(result.file_refs) > 0
        assert len(result.checksum) == 64  # SHA-256 hex digest
        assert result.dataset_id == metadata.dataset_id
        assert result.uploaded_by == metadata.uploaded_by

    @pytest.mark.asyncio
    @given(filename=invalid_filename_with_ext)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_unsupported_formats_rejected(self, filename: str) -> None:
        """For any file with an unsupported extension, upload_file must raise
        ValueError with a descriptive message mentioning supported formats.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()
        content = b"fake file content"

        with pytest.raises(ValueError, match="Unsupported file format"):
            await svc.upload_file(
                file_content=content,
                filename=filename,
                metadata=metadata,
            )

    @pytest.mark.asyncio
    @given(ext=supported_extension)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_each_supported_extension_individually(self, ext: str) -> None:
        """For each individual supported extension, upload must succeed.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()
        filename = f"dataset.{ext}"
        content = b"test content"

        result = await svc.upload_file(
            file_content=content,
            filename=filename,
            metadata=metadata,
        )

        assert result.source_type == "upload"
        assert len(result.file_refs) == 1

    @pytest.mark.asyncio
    @given(
        uri=st.builds(
            lambda bucket, key, ext: f"s3://{bucket}/{key}.{ext}",
            bucket=st.text(
                min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
            ),
            key=st.text(
                min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-"
            ),
            ext=supported_extension,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_s3_uri_with_supported_extension_accepted(self, uri: str) -> None:
        """For any s3:// URI pointing to a file with a supported extension,
        register_uri must succeed and return source_type='s3_uri'.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()

        result = await svc.register_uri(uri=uri, metadata=metadata)

        assert result.source_type == "s3_uri"
        assert len(result.file_refs) == 1
        assert result.file_refs[0] == uri
        assert len(result.checksum) == 64

    @pytest.mark.asyncio
    @given(
        uri=st.builds(
            lambda bucket, key, ext: f"s3://{bucket}/{key}.{ext}",
            bucket=st.text(
                min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
            ),
            key=st.text(
                min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-"
            ),
            ext=unsupported_extension,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_s3_uri_with_unsupported_extension_rejected(self, uri: str) -> None:
        """For any s3:// URI pointing to a file with an unsupported extension,
        register_uri must raise ValueError.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()

        with pytest.raises(ValueError, match="Unsupported file format"):
            await svc.register_uri(uri=uri, metadata=metadata)

    @pytest.mark.asyncio
    async def test_no_extension_rejected(self) -> None:
        """A file with no extension must be rejected.

        **Validates: Requirements 1.1**
        """
        svc = _mock_upload_service()
        metadata = _make_metadata()

        with pytest.raises(ValueError, match="Unsupported file format"):
            await svc.upload_file(
                file_content=b"data",
                filename="noextension",
                metadata=metadata,
            )
