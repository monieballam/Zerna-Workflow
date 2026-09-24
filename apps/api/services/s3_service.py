"""S3 service for dataset and artifact storage with organization-scoped paths."""

import hashlib
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from apps.api.config import Settings, get_settings, resolve_s3_endpoint_url


def raise_s3_upload_error_with_storage_hint(
    *,
    bucket: str,
    s3_key: str | None,
    exc: BaseException,
) -> NoReturn:
    """Re-raise upload failures, adding an ops hint when MinIO/S3 reports disk full."""
    text = str(exc).lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    if "xminiostoragefull" in compact or "minimumfreedrivethreshold" in compact.replace("_", ""):
        key_note = f" Failed object key: {s3_key!r}." if s3_key else ""
        raise RuntimeError(
            "Object storage refused the upload: the MinIO/S3 backend is out of free space "
            f"(or below its minimum free-drive threshold). Free disk on the storage node, delete "
            f"unneeded objects in bucket {bucket!r} (for example under runs/ — old _state/snapshots/ "
            "or completed run prefixes), or expand the volume/PVC, then use Resume from the last "
            "checkpoint instead of restarting the pipeline." + key_note
        ) from exc
    if isinstance(exc, ClientError):
        raise RuntimeError(f"Failed to upload file: {exc}") from exc
    raise exc


class S3Service:
    """Service for S3 operations with organization-scoped paths and multipart uploads."""

    def __init__(self, settings: Settings | None = None):
        """Initialize S3 service with boto3 client.

        Args:
            settings: Application settings. If None, uses get_settings().
        """
        self.settings = settings or get_settings()

        resolved_endpoint = resolve_s3_endpoint_url(self.settings)

        # Configure boto3 client
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"} if resolved_endpoint else {},
        )

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=resolved_endpoint,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
            region_name=self.settings.s3_region,
            config=config,
        )

        self.datasets_bucket = self.settings.s3_datasets_bucket
        self.artifacts_bucket = self.settings.s3_artifacts_bucket

        # Multipart upload threshold (100MB)
        self.multipart_threshold = 100 * 1024 * 1024
        # Multipart chunk size (10MB)
        self.multipart_chunk_size = 10 * 1024 * 1024

    def generate_dataset_path(self, org_id: UUID, dataset_id: UUID, filename: str) -> str:
        """Generate organization-scoped S3 path for dataset file.

        Args:
            org_id: Organization UUID
            dataset_id: Dataset UUID
            filename: Original filename

        Returns:
            S3 path in format: {org_id}/datasets/{dataset_id}/{filename}
        """
        return f"{org_id}/datasets/{dataset_id}/{filename}"

    def generate_artifact_path(
        self, org_id: UUID, run_id: UUID, artifact_type: str, filename: str
    ) -> str:
        """Generate organization-scoped S3 path for artifact file.

        Args:
            org_id: Organization UUID
            run_id: Run UUID
            artifact_type: Type of artifact (e.g., 'h5ad', 'embedding_plot')
            filename: Original filename

        Returns:
            S3 path in format: {org_id}/runs/{run_id}/{artifact_type}/{filename}
        """
        return f"{org_id}/runs/{run_id}/{artifact_type}/{filename}"

    def generate_presigned_upload_url(
        self,
        bucket: str,
        s3_path: str,
        expiration: int = 3600,
        content_type: str | None = None,
    ) -> str:
        """Generate pre-signed URL for direct browser upload to S3.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            expiration: URL expiration time in seconds (default: 1 hour)
            content_type: Optional content type for the upload

        Returns:
            Pre-signed URL string

        Raises:
            ClientError: If URL generation fails
        """
        params = {
            "Bucket": bucket,
            "Key": s3_path,
        }

        if content_type:
            params["ContentType"] = content_type

        try:
            url = self.s3_client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expiration,
            )
            return cast(str, url)
        except ClientError as e:
            raise RuntimeError(f"Failed to generate presigned URL: {e}") from e

    def generate_presigned_download_url(
        self, bucket: str, s3_path: str, expiration: int = 3600
    ) -> str:
        """Generate pre-signed URL for downloading from S3.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Pre-signed URL string

        Raises:
            ClientError: If URL generation fails
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": s3_path},
                ExpiresIn=expiration,
            )
            return cast(str, url)
        except ClientError as e:
            raise RuntimeError(f"Failed to generate presigned URL: {e}") from e

    def initiate_multipart_upload(
        self, bucket: str, s3_path: str, content_type: str | None = None
    ) -> str:
        """Initiate a multipart upload for large files.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            content_type: Optional content type

        Returns:
            Upload ID for the multipart upload

        Raises:
            ClientError: If initiation fails
        """
        params = {"Bucket": bucket, "Key": s3_path}

        if content_type:
            params["ContentType"] = content_type

        try:
            response = self.s3_client.create_multipart_upload(**params)
            return cast(str, response["UploadId"])
        except ClientError as e:
            raise RuntimeError(f"Failed to initiate multipart upload: {e}") from e

    def generate_presigned_multipart_upload_urls(
        self,
        bucket: str,
        s3_path: str,
        upload_id: str,
        num_parts: int,
        expiration: int = 3600,
    ) -> list[dict[str, Any]]:
        """Generate pre-signed URLs for each part of a multipart upload.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            upload_id: Upload ID from initiate_multipart_upload
            num_parts: Number of parts to generate URLs for
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            List of dicts with 'part_number' and 'url' keys

        Raises:
            ClientError: If URL generation fails
        """
        urls: list[dict[str, Any]] = []

        try:
            for part_number in range(1, num_parts + 1):
                url = self.s3_client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": bucket,
                        "Key": s3_path,
                        "UploadId": upload_id,
                        "PartNumber": part_number,
                    },
                    ExpiresIn=expiration,
                )
                urls.append({"part_number": part_number, "url": url})

            return urls
        except ClientError as e:
            raise RuntimeError(f"Failed to generate multipart upload URLs: {e}") from e

    def complete_multipart_upload(
        self, bucket: str, s3_path: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Complete a multipart upload after all parts are uploaded.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            upload_id: Upload ID from initiate_multipart_upload
            parts: List of dicts with 'PartNumber' and 'ETag' keys

        Returns:
            Response from S3 with ETag and Location

        Raises:
            ClientError: If completion fails
        """
        try:
            response = self.s3_client.complete_multipart_upload(
                Bucket=bucket,
                Key=s3_path,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            return {
                "etag": response["ETag"],
                "location": response["Location"],
            }
        except ClientError as e:
            raise RuntimeError(f"Failed to complete multipart upload: {e}") from e

    def abort_multipart_upload(self, bucket: str, s3_path: str, upload_id: str) -> None:
        """Abort a multipart upload and clean up parts.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            upload_id: Upload ID from initiate_multipart_upload

        Raises:
            ClientError: If abort fails
        """
        try:
            self.s3_client.abort_multipart_upload(Bucket=bucket, Key=s3_path, UploadId=upload_id)
        except ClientError as e:
            raise RuntimeError(f"Failed to abort multipart upload: {e}") from e

    def verify_upload(
        self, bucket: str, s3_path: str, expected_size: int | None = None
    ) -> dict[str, Any]:
        """Verify that a file was uploaded successfully and check integrity.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path
            expected_size: Optional expected file size in bytes

        Returns:
            Dict with 'exists', 'size', 'etag', and 'last_modified' keys

        Raises:
            ClientError: If verification fails
            ValueError: If size doesn't match expected_size
        """
        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=s3_path)

            size = response["ContentLength"]
            etag = response["ETag"].strip('"')
            last_modified = response["LastModified"]

            if expected_size is not None and size != expected_size:
                raise ValueError(f"File size mismatch: expected {expected_size}, got {size}")

            return {
                "exists": True,
                "size": size,
                "etag": etag,
                "last_modified": last_modified,
            }
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return {"exists": False}
            raise RuntimeError(f"Failed to verify upload: {e}") from e

    def calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate MD5 checksum of a file.

        Args:
            file_path: Path to the file

        Returns:
            Hex digest of MD5 checksum
        """
        md5_hash = hashlib.md5()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)

        return md5_hash.hexdigest()

    def upload_file(
        self,
        file_path: Path,
        bucket: str,
        s3_path: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to S3 with automatic multipart for large files.

        Args:
            file_path: Path to the local file
            bucket: S3 bucket name
            s3_path: S3 object key/path
            content_type: Optional content type

        Returns:
            Dict with 'etag', 'size', and 'checksum' keys

        Raises:
            FileNotFoundError: If file doesn't exist
            ClientError: If upload fails
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        checksum = self.calculate_file_checksum(file_path)

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            # Use multipart upload for large files
            if file_size > self.multipart_threshold:
                self.s3_client.upload_file(
                    str(file_path),
                    bucket,
                    s3_path,
                    ExtraArgs=extra_args,
                    Config=boto3.s3.transfer.TransferConfig(
                        multipart_threshold=self.multipart_threshold,
                        multipart_chunksize=self.multipart_chunk_size,
                    ),
                )
            else:
                self.s3_client.upload_file(str(file_path), bucket, s3_path, ExtraArgs=extra_args)

            # Verify upload
            verification = self.verify_upload(bucket, s3_path, file_size)

            return {
                "etag": verification["etag"],
                "size": file_size,
                "checksum": checksum,
            }
        except Exception as e:
            raise_s3_upload_error_with_storage_hint(bucket=bucket, s3_key=s3_path, exc=e)

    def delete_file(self, bucket: str, s3_path: str) -> None:
        """Delete a file from S3.

        Args:
            bucket: S3 bucket name
            s3_path: S3 object key/path

        Raises:
            ClientError: If deletion fails
        """
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=s3_path)
        except ClientError as e:
            raise RuntimeError(f"Failed to delete file: {e}") from e

    def list_files(self, bucket: str, prefix: str) -> list[dict[str, Any]]:
        """List files in S3 with a given prefix.

        Args:
            bucket: S3 bucket name
            prefix: S3 key prefix to filter by

        Returns:
            List of dicts with 'key', 'size', and 'last_modified' keys

        Raises:
            ClientError: If listing fails
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)

            if "Contents" not in response:
                return []

            return [
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                }
                for obj in response["Contents"]
            ]
        except ClientError as e:
            raise RuntimeError(f"Failed to list files: {e}") from e
