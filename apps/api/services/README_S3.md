# S3 Service Usage Guide

The S3Service provides organization-scoped storage operations for datasets and artifacts with support for multipart uploads and pre-signed URLs.

## Features

- **Organization-scoped paths**: All S3 paths are prefixed with organization ID for data isolation
- **Pre-signed URLs**: Generate secure URLs for direct browser uploads/downloads
- **Multipart upload**: Automatic handling of large files (>100MB) with multipart upload
- **Upload verification**: Checksum validation and integrity checks
- **File operations**: Upload, download, delete, and list files

## Basic Usage

### Initialize the Service

```python
from apps.api.services import S3Service
from apps.api.config import get_settings

# Initialize with default settings
s3_service = S3Service()

# Or with custom settings
settings = get_settings()
s3_service = S3Service(settings)
```

### Generate Organization-Scoped Paths

```python
from uuid import uuid4

org_id = uuid4()
dataset_id = uuid4()
run_id = uuid4()

# Dataset path: {org_id}/datasets/{dataset_id}/filename
dataset_path = s3_service.generate_dataset_path(
    org_id=org_id,
    dataset_id=dataset_id,
    filename="expression_data.h5ad"
)
# Result: "123e4567-e89b-12d3-a456-426614174000/datasets/789e4567-e89b-12d3-a456-426614174000/expression_data.h5ad"

# Artifact path: {org_id}/runs/{run_id}/{artifact_type}/filename
artifact_path = s3_service.generate_artifact_path(
    org_id=org_id,
    run_id=run_id,
    artifact_type="h5ad",
    filename="processed_data.h5ad"
)
# Result: "123e4567-e89b-12d3-a456-426614174000/runs/456e4567-e89b-12d3-a456-426614174000/h5ad/processed_data.h5ad"
```

### Generate Pre-signed Upload URLs

```python
# For direct browser upload (small files)
upload_url = s3_service.generate_presigned_upload_url(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    expiration=3600,  # 1 hour
    content_type="application/octet-stream"
)

# Client can now PUT directly to this URL
# curl -X PUT -H "Content-Type: application/octet-stream" --data-binary @file.h5ad "$upload_url"
```

### Multipart Upload for Large Files

```python
# Step 1: Initiate multipart upload
upload_id = s3_service.initiate_multipart_upload(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    content_type="application/octet-stream"
)

# Step 2: Calculate number of parts (file_size / chunk_size)
file_size = 500 * 1024 * 1024  # 500MB
chunk_size = 10 * 1024 * 1024   # 10MB
num_parts = (file_size + chunk_size - 1) // chunk_size

# Step 3: Generate pre-signed URLs for each part
part_urls = s3_service.generate_presigned_multipart_upload_urls(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    upload_id=upload_id,
    num_parts=num_parts,
    expiration=3600
)

# Client uploads each part and collects ETags
# parts = [
#     {"PartNumber": 1, "ETag": "etag1"},
#     {"PartNumber": 2, "ETag": "etag2"},
#     ...
# ]

# Step 4: Complete the multipart upload
result = s3_service.complete_multipart_upload(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    upload_id=upload_id,
    parts=parts
)

# Or abort if upload fails
# s3_service.abort_multipart_upload(
#     bucket=s3_service.datasets_bucket,
#     s3_path=dataset_path,
#     upload_id=upload_id
# )
```

### Upload File from Server

```python
from pathlib import Path

# Upload a local file
local_file = Path("/path/to/local/file.h5ad")

result = s3_service.upload_file(
    file_path=local_file,
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    content_type="application/octet-stream"
)

print(f"Uploaded: {result['size']} bytes")
print(f"ETag: {result['etag']}")
print(f"Checksum: {result['checksum']}")
```

### Verify Upload

```python
# Verify file exists and check integrity
verification = s3_service.verify_upload(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    expected_size=1024 * 1024  # Optional size check
)

if verification["exists"]:
    print(f"File size: {verification['size']} bytes")
    print(f"ETag: {verification['etag']}")
    print(f"Last modified: {verification['last_modified']}")
else:
    print("File not found")
```

### Generate Download URL

```python
# Generate pre-signed download URL
download_url = s3_service.generate_presigned_download_url(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path,
    expiration=3600
)

# Client can now GET from this URL
# curl -o downloaded_file.h5ad "$download_url"
```

### List Files

```python
# List all files for an organization's datasets
prefix = f"{org_id}/datasets/"

files = s3_service.list_files(
    bucket=s3_service.datasets_bucket,
    prefix=prefix
)

for file in files:
    print(f"{file['key']}: {file['size']} bytes, modified {file['last_modified']}")
```

### Delete File

```python
# Delete a file
s3_service.delete_file(
    bucket=s3_service.datasets_bucket,
    s3_path=dataset_path
)
```

## Configuration

The S3Service uses settings from `apps/api/config.py`:

```python
# Required settings
s3_access_key_id: str          # AWS access key ID
s3_secret_access_key: str      # AWS secret access key
s3_datasets_bucket: str        # Bucket for datasets
s3_artifacts_bucket: str       # Bucket for artifacts

# Optional settings
s3_endpoint_url: str = None    # For MinIO or custom S3-compatible storage
s3_region: str = "us-east-1"   # AWS region
```

## Environment Variables

Set these in your `.env` file:

```bash
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_REGION=us-east-1
S3_DATASETS_BUCKET=zerna-datasets-dev
S3_ARTIFACTS_BUCKET=zerna-artifacts-dev

# For local development with MinIO (host → container port mapping; default 19000 → 9000)
S3_ENDPOINT_URL=http://localhost:19000
```

Resolution uses `apps.api.config.resolve_s3_endpoint_url`: set `S3_ENDPOINT_URL` explicitly, or use defaults (`http://minio:9000` in Docker, `http://localhost:${MINIO_PORT:-19000}` on the host).

## Organization Isolation

All paths are automatically scoped by organization ID to ensure data isolation:

- Dataset files: `{org_id}/datasets/{dataset_id}/{filename}`
- Artifact files: `{org_id}/runs/{run_id}/{artifact_type}/{filename}`

This ensures:

- No cross-organization data access
- Easy quota enforcement per organization
- Simple cleanup when deleting an organization
- Clear audit trail of data ownership

## Error Handling

All methods raise `RuntimeError` with descriptive messages on failure:

```python
try:
    result = s3_service.upload_file(file_path, bucket, s3_path)
except FileNotFoundError:
    # Local file doesn't exist
    pass
except RuntimeError as e:
    # S3 operation failed
    print(f"Upload failed: {e}")
```

## Testing

The service includes comprehensive unit tests in `apps/api/tests/test_s3_service.py`:

```bash
# Run S3 service tests
pytest apps/api/tests/test_s3_service.py -v

# Run with coverage
pytest apps/api/tests/test_s3_service.py --cov=apps.api.services.s3_service
```

## Integration with Other Services

### Dataset Service

```python
from apps.api.services import S3Service

class DatasetService:
    def __init__(self):
        self.s3_service = S3Service()

    async def create_dataset(self, org_id, dataset_id, files):
        # Generate pre-signed URLs for client upload
        upload_urls = []
        for file in files:
            s3_path = self.s3_service.generate_dataset_path(
                org_id, dataset_id, file.filename
            )
            url = self.s3_service.generate_presigned_upload_url(
                self.s3_service.datasets_bucket,
                s3_path,
                content_type=file.content_type
            )
            upload_urls.append({"filename": file.filename, "url": url})

        return upload_urls
```

### Run Service

```python
from apps.api.services import S3Service

class RunService:
    def __init__(self):
        self.s3_service = S3Service()

    async def store_artifact(self, org_id, run_id, artifact_type, file_path):
        # Upload artifact from compute worker
        s3_path = self.s3_service.generate_artifact_path(
            org_id, run_id, artifact_type, file_path.name
        )

        result = self.s3_service.upload_file(
            file_path,
            self.s3_service.artifacts_bucket,
            s3_path
        )

        # Verify upload
        verification = self.s3_service.verify_upload(
            self.s3_service.artifacts_bucket,
            s3_path,
            expected_size=file_path.stat().st_size
        )

        return {
            "s3_path": s3_path,
            "size": result["size"],
            "checksum": result["checksum"],
            "etag": verification["etag"]
        }
```
