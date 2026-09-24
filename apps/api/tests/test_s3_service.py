"""Unit tests for S3Service."""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from apps.api.config import Settings
from apps.api.services.s3_service import S3Service


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    return Settings(
        database_url="postgresql://test",
        redis_url="redis://test",
        jwt_secret_key="test-secret",
        s3_access_key_id="test-access-key",
        s3_secret_access_key="test-secret-key",
        s3_region="us-east-1",
        s3_datasets_bucket="test-datasets",
        s3_artifacts_bucket="test-artifacts",
        s3_endpoint_url="http://localhost:9000",
    )


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client."""
    return MagicMock()


@pytest.fixture
def s3_service(mock_settings, mock_s3_client):
    """Create S3Service with mocked client."""
    with patch("apps.api.services.s3_service.boto3.client", return_value=mock_s3_client):
        service = S3Service(mock_settings)
        service.s3_client = mock_s3_client
        return service


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        content = b"test content for upload"
        f.write(content)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


class TestS3ServiceInitialization:
    """Tests for S3Service initialization."""

    def test_initialization_with_settings(self, mock_settings):
        """Test S3Service initializes with provided settings."""
        with patch("apps.api.services.s3_service.boto3.client") as mock_boto:
            service = S3Service(mock_settings)

            assert service.settings == mock_settings
            assert service.datasets_bucket == "test-datasets"
            assert service.artifacts_bucket == "test-artifacts"
            assert service.multipart_threshold == 100 * 1024 * 1024
            assert service.multipart_chunk_size == 10 * 1024 * 1024

            # Verify boto3 client was created with correct parameters
            mock_boto.assert_called_once()
            call_kwargs = mock_boto.call_args[1]
            assert call_kwargs["endpoint_url"] == "http://localhost:9000"
            assert call_kwargs["aws_access_key_id"] == "test-access-key"
            assert call_kwargs["aws_secret_access_key"] == "test-secret-key"
            assert call_kwargs["region_name"] == "us-east-1"

    def test_initialization_without_settings(self):
        """Test S3Service initializes with default settings."""
        with patch("apps.api.services.s3_service.get_settings") as mock_get_settings:
            with patch("apps.api.services.s3_service.boto3.client"):
                mock_settings = MagicMock()
                mock_get_settings.return_value = mock_settings

                service = S3Service()

                assert service.settings == mock_settings
                mock_get_settings.assert_called_once()


class TestPathGeneration:
    """Tests for S3 path generation methods."""

    def test_generate_dataset_path(self, s3_service):
        """Test dataset path generation with organization scoping."""
        org_id = uuid4()
        dataset_id = uuid4()
        filename = "data.h5ad"

        path = s3_service.generate_dataset_path(org_id, dataset_id, filename)

        assert path == f"{org_id}/datasets/{dataset_id}/{filename}"
        assert path.startswith(str(org_id))
        assert "/datasets/" in path

    def test_generate_artifact_path(self, s3_service):
        """Test artifact path generation with organization scoping."""
        org_id = uuid4()
        run_id = uuid4()
        artifact_type = "h5ad"
        filename = "result.h5ad"

        path = s3_service.generate_artifact_path(org_id, run_id, artifact_type, filename)

        assert path == f"{org_id}/runs/{run_id}/{artifact_type}/{filename}"
        assert path.startswith(str(org_id))
        assert "/runs/" in path
        assert f"/{artifact_type}/" in path


class TestPresignedURLs:
    """Tests for pre-signed URL generation."""

    def test_generate_presigned_upload_url(self, s3_service, mock_s3_client):
        """Test generation of pre-signed upload URL."""
        bucket = "test-bucket"
        s3_path = "test/path/file.txt"
        expected_url = "https://s3.amazonaws.com/presigned-url"

        mock_s3_client.generate_presigned_url.return_value = expected_url

        url = s3_service.generate_presigned_upload_url(bucket, s3_path)

        assert url == expected_url
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={"Bucket": bucket, "Key": s3_path},
            ExpiresIn=3600,
        )

    def test_generate_presigned_upload_url_with_content_type(self, s3_service, mock_s3_client):
        """Test generation of pre-signed upload URL with content type."""
        bucket = "test-bucket"
        s3_path = "test/path/file.txt"
        content_type = "application/octet-stream"
        expected_url = "https://s3.amazonaws.com/presigned-url"

        mock_s3_client.generate_presigned_url.return_value = expected_url

        url = s3_service.generate_presigned_upload_url(bucket, s3_path, content_type=content_type)

        assert url == expected_url
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={"Bucket": bucket, "Key": s3_path, "ContentType": content_type},
            ExpiresIn=3600,
        )

    def test_generate_presigned_upload_url_with_custom_expiration(self, s3_service, mock_s3_client):
        """Test generation of pre-signed upload URL with custom expiration."""
        bucket = "test-bucket"
        s3_path = "test/path/file.txt"
        expiration = 7200
        expected_url = "https://s3.amazonaws.com/presigned-url"

        mock_s3_client.generate_presigned_url.return_value = expected_url

        url = s3_service.generate_presigned_upload_url(bucket, s3_path, expiration=expiration)

        assert url == expected_url
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={"Bucket": bucket, "Key": s3_path},
            ExpiresIn=expiration,
        )

    def test_generate_presigned_upload_url_error(self, s3_service, mock_s3_client):
        """Test error handling in pre-signed upload URL generation."""
        mock_s3_client.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "generate_presigned_url",
        )

        with pytest.raises(RuntimeError, match="Failed to generate presigned URL"):
            s3_service.generate_presigned_upload_url("bucket", "path")

    def test_generate_presigned_download_url(self, s3_service, mock_s3_client):
        """Test generation of pre-signed download URL."""
        bucket = "test-bucket"
        s3_path = "test/path/file.txt"
        expected_url = "https://s3.amazonaws.com/presigned-download-url"

        mock_s3_client.generate_presigned_url.return_value = expected_url

        url = s3_service.generate_presigned_download_url(bucket, s3_path)

        assert url == expected_url
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_path},
            ExpiresIn=3600,
        )

    def test_generate_presigned_download_url_error(self, s3_service, mock_s3_client):
        """Test error handling in pre-signed download URL generation."""
        mock_s3_client.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}},
            "generate_presigned_url",
        )

        with pytest.raises(RuntimeError, match="Failed to generate presigned URL"):
            s3_service.generate_presigned_download_url("bucket", "path")


class TestMultipartUpload:
    """Tests for multipart upload coordination."""

    def test_initiate_multipart_upload(self, s3_service, mock_s3_client):
        """Test initiating a multipart upload."""
        bucket = "test-bucket"
        s3_path = "test/large-file.bin"
        upload_id = "test-upload-id-12345"

        mock_s3_client.create_multipart_upload.return_value = {"UploadId": upload_id}

        result = s3_service.initiate_multipart_upload(bucket, s3_path)

        assert result == upload_id
        mock_s3_client.create_multipart_upload.assert_called_once_with(Bucket=bucket, Key=s3_path)

    def test_initiate_multipart_upload_with_content_type(self, s3_service, mock_s3_client):
        """Test initiating a multipart upload with content type."""
        bucket = "test-bucket"
        s3_path = "test/large-file.bin"
        content_type = "application/octet-stream"
        upload_id = "test-upload-id-12345"

        mock_s3_client.create_multipart_upload.return_value = {"UploadId": upload_id}

        result = s3_service.initiate_multipart_upload(bucket, s3_path, content_type=content_type)

        assert result == upload_id
        mock_s3_client.create_multipart_upload.assert_called_once_with(
            Bucket=bucket, Key=s3_path, ContentType=content_type
        )

    def test_initiate_multipart_upload_error(self, s3_service, mock_s3_client):
        """Test error handling in multipart upload initiation."""
        mock_s3_client.create_multipart_upload.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "create_multipart_upload",
        )

        with pytest.raises(RuntimeError, match="Failed to initiate multipart upload"):
            s3_service.initiate_multipart_upload("bucket", "path")

    def test_generate_presigned_multipart_upload_urls(self, s3_service, mock_s3_client):
        """Test generation of pre-signed URLs for multipart upload parts."""
        bucket = "test-bucket"
        s3_path = "test/large-file.bin"
        upload_id = "test-upload-id"
        num_parts = 3

        mock_s3_client.generate_presigned_url.side_effect = [
            f"https://s3.amazonaws.com/part-{i}" for i in range(1, num_parts + 1)
        ]

        urls = s3_service.generate_presigned_multipart_upload_urls(
            bucket, s3_path, upload_id, num_parts
        )

        assert len(urls) == num_parts
        for i, url_info in enumerate(urls, start=1):
            assert url_info["part_number"] == i
            assert url_info["url"] == f"https://s3.amazonaws.com/part-{i}"

        assert mock_s3_client.generate_presigned_url.call_count == num_parts

    def test_generate_presigned_multipart_upload_urls_error(self, s3_service, mock_s3_client):
        """Test error handling in multipart URL generation."""
        mock_s3_client.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "InvalidRequest", "Message": "Invalid request"}},
            "generate_presigned_url",
        )

        with pytest.raises(RuntimeError, match="Failed to generate multipart upload URLs"):
            s3_service.generate_presigned_multipart_upload_urls("bucket", "path", "upload-id", 3)

    def test_complete_multipart_upload(self, s3_service, mock_s3_client):
        """Test completing a multipart upload."""
        bucket = "test-bucket"
        s3_path = "test/large-file.bin"
        upload_id = "test-upload-id"
        parts = [
            {"PartNumber": 1, "ETag": "etag1"},
            {"PartNumber": 2, "ETag": "etag2"},
        ]

        mock_s3_client.complete_multipart_upload.return_value = {
            "ETag": "final-etag",
            "Location": "https://s3.amazonaws.com/bucket/key",
        }

        result = s3_service.complete_multipart_upload(bucket, s3_path, upload_id, parts)

        assert result["etag"] == "final-etag"
        assert result["location"] == "https://s3.amazonaws.com/bucket/key"
        mock_s3_client.complete_multipart_upload.assert_called_once_with(
            Bucket=bucket,
            Key=s3_path,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def test_complete_multipart_upload_error(self, s3_service, mock_s3_client):
        """Test error handling in multipart upload completion."""
        mock_s3_client.complete_multipart_upload.side_effect = ClientError(
            {"Error": {"Code": "InvalidPart", "Message": "Invalid part"}},
            "complete_multipart_upload",
        )

        with pytest.raises(RuntimeError, match="Failed to complete multipart upload"):
            s3_service.complete_multipart_upload("bucket", "path", "upload-id", [])

    def test_abort_multipart_upload(self, s3_service, mock_s3_client):
        """Test aborting a multipart upload."""
        bucket = "test-bucket"
        s3_path = "test/large-file.bin"
        upload_id = "test-upload-id"

        s3_service.abort_multipart_upload(bucket, s3_path, upload_id)

        mock_s3_client.abort_multipart_upload.assert_called_once_with(
            Bucket=bucket, Key=s3_path, UploadId=upload_id
        )

    def test_abort_multipart_upload_error(self, s3_service, mock_s3_client):
        """Test error handling in multipart upload abort."""
        mock_s3_client.abort_multipart_upload.side_effect = ClientError(
            {"Error": {"Code": "NoSuchUpload", "Message": "Upload not found"}},
            "abort_multipart_upload",
        )

        with pytest.raises(RuntimeError, match="Failed to abort multipart upload"):
            s3_service.abort_multipart_upload("bucket", "path", "upload-id")


class TestUploadVerification:
    """Tests for upload verification and integrity checks."""

    def test_verify_upload_success(self, s3_service, mock_s3_client):
        """Test successful upload verification."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"
        expected_size = 1024

        from datetime import datetime

        mock_s3_client.head_object.return_value = {
            "ContentLength": expected_size,
            "ETag": '"abc123"',
            "LastModified": datetime(2024, 1, 1, 12, 0, 0),
        }

        result = s3_service.verify_upload(bucket, s3_path, expected_size)

        assert result["exists"] is True
        assert result["size"] == expected_size
        assert result["etag"] == "abc123"
        assert result["last_modified"] == datetime(2024, 1, 1, 12, 0, 0)

    def test_verify_upload_without_expected_size(self, s3_service, mock_s3_client):
        """Test upload verification without size check."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"

        from datetime import datetime

        mock_s3_client.head_object.return_value = {
            "ContentLength": 2048,
            "ETag": '"xyz789"',
            "LastModified": datetime(2024, 1, 1, 12, 0, 0),
        }

        result = s3_service.verify_upload(bucket, s3_path)

        assert result["exists"] is True
        assert result["size"] == 2048
        assert result["etag"] == "xyz789"

    def test_verify_upload_size_mismatch(self, s3_service, mock_s3_client):
        """Test upload verification with size mismatch."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"
        expected_size = 1024

        from datetime import datetime

        mock_s3_client.head_object.return_value = {
            "ContentLength": 2048,
            "ETag": '"abc123"',
            "LastModified": datetime(2024, 1, 1, 12, 0, 0),
        }

        with pytest.raises(ValueError, match="File size mismatch"):
            s3_service.verify_upload(bucket, s3_path, expected_size)

    def test_verify_upload_file_not_found(self, s3_service, mock_s3_client):
        """Test upload verification when file doesn't exist."""
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not found"}}, "head_object"
        )

        result = s3_service.verify_upload("bucket", "path")

        assert result["exists"] is False

    def test_verify_upload_other_error(self, s3_service, mock_s3_client):
        """Test upload verification with other errors."""
        mock_s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "head_object",
        )

        with pytest.raises(RuntimeError, match="Failed to verify upload"):
            s3_service.verify_upload("bucket", "path")

    def test_calculate_file_checksum(self, s3_service, temp_file):
        """Test MD5 checksum calculation."""
        checksum = s3_service.calculate_file_checksum(temp_file)

        # Calculate expected checksum
        expected = hashlib.md5(b"test content for upload").hexdigest()

        assert checksum == expected
        assert len(checksum) == 32  # MD5 hex digest length


class TestFileOperations:
    """Tests for file upload, download, and deletion."""

    def test_upload_file_small(self, s3_service, mock_s3_client, temp_file):
        """Test uploading a small file (below multipart threshold)."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"

        from datetime import datetime

        mock_s3_client.head_object.return_value = {
            "ContentLength": temp_file.stat().st_size,
            "ETag": '"abc123"',
            "LastModified": datetime(2024, 1, 1, 12, 0, 0),
        }

        result = s3_service.upload_file(temp_file, bucket, s3_path)

        assert "etag" in result
        assert "size" in result
        assert "checksum" in result
        assert result["size"] == temp_file.stat().st_size

        mock_s3_client.upload_file.assert_called_once()

    def test_upload_file_with_content_type(self, s3_service, mock_s3_client, temp_file):
        """Test uploading a file with content type."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"
        content_type = "text/plain"

        from datetime import datetime

        mock_s3_client.head_object.return_value = {
            "ContentLength": temp_file.stat().st_size,
            "ETag": '"abc123"',
            "LastModified": datetime(2024, 1, 1, 12, 0, 0),
        }

        result = s3_service.upload_file(temp_file, bucket, s3_path, content_type=content_type)

        assert "etag" in result
        mock_s3_client.upload_file.assert_called_once()

        # Check that ExtraArgs includes ContentType
        call_args = mock_s3_client.upload_file.call_args
        assert "ExtraArgs" in call_args[1]
        assert call_args[1]["ExtraArgs"]["ContentType"] == content_type

    def test_upload_file_not_found(self, s3_service):
        """Test uploading a non-existent file."""
        with pytest.raises(FileNotFoundError):
            s3_service.upload_file(Path("/nonexistent/file.txt"), "bucket", "path")

    def test_upload_file_error(self, s3_service, mock_s3_client, temp_file):
        """Test error handling in file upload."""
        mock_s3_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "upload_file",
        )

        with pytest.raises(RuntimeError, match="Failed to upload file"):
            s3_service.upload_file(temp_file, "bucket", "path")

    def test_delete_file(self, s3_service, mock_s3_client):
        """Test deleting a file from S3."""
        bucket = "test-bucket"
        s3_path = "test/file.txt"

        s3_service.delete_file(bucket, s3_path)

        mock_s3_client.delete_object.assert_called_once_with(Bucket=bucket, Key=s3_path)

    def test_delete_file_error(self, s3_service, mock_s3_client):
        """Test error handling in file deletion."""
        mock_s3_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "delete_object",
        )

        with pytest.raises(RuntimeError, match="Failed to delete file"):
            s3_service.delete_file("bucket", "path")

    def test_list_files(self, s3_service, mock_s3_client):
        """Test listing files with a prefix."""
        bucket = "test-bucket"
        prefix = "org-123/datasets/"

        from datetime import datetime

        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"{prefix}file1.txt",
                    "Size": 1024,
                    "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                },
                {
                    "Key": f"{prefix}file2.txt",
                    "Size": 2048,
                    "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                },
            ]
        }

        files = s3_service.list_files(bucket, prefix)

        assert len(files) == 2
        assert files[0]["key"] == f"{prefix}file1.txt"
        assert files[0]["size"] == 1024
        assert files[1]["key"] == f"{prefix}file2.txt"
        assert files[1]["size"] == 2048

    def test_list_files_empty(self, s3_service, mock_s3_client):
        """Test listing files when no files match prefix."""
        mock_s3_client.list_objects_v2.return_value = {}

        files = s3_service.list_files("bucket", "prefix/")

        assert files == []

    def test_list_files_error(self, s3_service, mock_s3_client):
        """Test error handling in file listing."""
        mock_s3_client.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "list_objects_v2",
        )

        with pytest.raises(RuntimeError, match="Failed to list files"):
            s3_service.list_files("bucket", "prefix/")


class TestOrganizationScoping:
    """Tests for organization-scoped path enforcement."""

    def test_dataset_path_includes_org_id(self, s3_service):
        """Test that dataset paths always include organization ID."""
        org_id = uuid4()
        dataset_id = uuid4()

        path = s3_service.generate_dataset_path(org_id, dataset_id, "file.h5ad")

        # Path should start with org_id
        assert path.startswith(str(org_id))

    def test_artifact_path_includes_org_id(self, s3_service):
        """Test that artifact paths always include organization ID."""
        org_id = uuid4()
        run_id = uuid4()

        path = s3_service.generate_artifact_path(org_id, run_id, "h5ad", "result.h5ad")

        # Path should start with org_id
        assert path.startswith(str(org_id))

    def test_different_orgs_have_different_paths(self, s3_service):
        """Test that different organizations get different paths."""
        org_id_1 = uuid4()
        org_id_2 = uuid4()
        dataset_id = uuid4()

        path_1 = s3_service.generate_dataset_path(org_id_1, dataset_id, "file.h5ad")
        path_2 = s3_service.generate_dataset_path(org_id_2, dataset_id, "file.h5ad")

        assert path_1 != path_2
        assert str(org_id_1) in path_1
        assert str(org_id_2) in path_2
