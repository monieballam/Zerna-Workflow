"""Activities for dataset ingestion workflow."""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from temporalio import activity

from apps.api.dependencies import _get_session_factory as _get_sf
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.services.file_validation_service import FileValidationService
from apps.api.services.s3_service import S3Service

logger = logging.getLogger(__name__)


@activity.defn
async def validate_files(input: dict[str, Any]) -> dict[str, Any]:
    """
    Validate uploaded files for format and structure.

    Args:
        input: Dictionary containing dataset_id, organization_id, and files
              files is a list of dicts with 'bucket' and 'key' keys

    Returns:
        Dictionary with validation results and any errors
    """
    activity.logger.info(f"Validating files for dataset {input['dataset_id']}")

    errors = []
    validation_results = []

    if not input.get("files"):
        errors.append("No files provided")
        return {"valid": False, "errors": errors, "validation_results": []}

    # Initialize services
    file_validation_service = FileValidationService()
    s3_service = S3Service()

    # Download and validate each file
    for file_info in input["files"]:
        bucket = file_info["bucket"]
        key = file_info["key"]

        try:
            # Infer file format from extension
            file_format = _infer_file_format(key)

            # Download file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(key).suffix) as tmp_file:
                tmp_path = Path(tmp_file.name)

                # Download from S3
                try:
                    s3_service.s3_client.download_file(bucket, key, str(tmp_path))
                except Exception as e:
                    errors.append(f"Failed to download {key}: {str(e)}")
                    continue

                # Validate file
                validation_result = await file_validation_service.validate_file(
                    tmp_path, file_format
                )

                if not validation_result.is_valid:
                    errors.append(f"Validation failed for {key}: {validation_result.error_message}")
                else:
                    validation_results.append(
                        {
                            "key": key,
                            "format": file_format,
                            "cell_count": validation_result.metadata.cell_count
                            if validation_result.metadata
                            else 0,
                            "gene_count": validation_result.metadata.gene_count
                            if validation_result.metadata
                            else 0,
                            "additional_metadata": validation_result.metadata.additional_metadata
                            if validation_result.metadata
                            else {},
                        }
                    )

                # Clean up temporary file
                tmp_path.unlink()

        except Exception as e:
            errors.append(f"Error processing {key}: {str(e)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "validation_results": validation_results,
    }


@activity.defn
async def extract_metadata(input: dict[str, Any]) -> dict[str, Any]:
    """
    Extract metadata from validated files (cell count, gene count).

    Args:
        input: Dictionary containing dataset_id, organization_id, and files

    Returns:
        Dictionary with extracted metadata
    """
    activity.logger.info(f"Extracting metadata for dataset {input['dataset_id']}")

    # Metadata extraction is already done in validate_files
    # This activity aggregates the results

    validation_results = input.get("validation_results", [])

    if not validation_results:
        return {
            "cell_count": 0,
            "gene_count": 0,
            "file_format": "unknown",
            "file_formats": [],
        }

    # Aggregate metadata across all files
    total_cell_count = sum(r["cell_count"] for r in validation_results)
    max_gene_count = max((r["gene_count"] for r in validation_results), default=0)
    file_formats = [r["format"] for r in validation_results]

    return {
        "cell_count": total_cell_count,
        "gene_count": max_gene_count,
        "file_format": file_formats[0] if len(file_formats) == 1 else "mixed",
        "file_formats": file_formats,
        "validation_results": validation_results,
    }


@activity.defn
async def store_in_s3(input: dict[str, Any]) -> dict[str, Any]:
    """
    Store validated files in S3 with organization-scoped paths and create DatasetVersion.

    Args:
        input: Dictionary containing dataset_id, organization_id, files, and metadata

    Returns:
        Dictionary with storage results including dataset_version_id
    """
    activity.logger.info(
        f"Creating DatasetVersion for dataset {input['dataset_id']}, "
        f"organization {input['organization_id']}"
    )

    dataset_id = UUID(input["dataset_id"])
    organization_id = UUID(input["organization_id"])
    metadata = input.get("metadata", {})
    files = input.get("files", [])

    # Files are already in S3 (uploaded via presigned URLs)
    # We just need to create the DatasetVersion record

    # Get database session
    async with _get_sf()() as db:
        try:
            # Get dataset to verify it exists and belongs to organization
            stmt = select(Dataset).where(
                Dataset.id == dataset_id, Dataset.organization_id == organization_id
            )
            result = await db.execute(stmt)
            dataset = result.scalar_one_or_none()

            if dataset is None:
                raise ValueError(
                    f"Dataset {dataset_id} not found or does not belong to organization {organization_id}"
                )

            # Determine next version number
            stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
            result = await db.execute(stmt)
            existing_versions = result.scalars().all()

            version_numbers = []
            for v in existing_versions:
                try:
                    num = int(v.version.lstrip("v"))
                    version_numbers.append(num)
                except ValueError:
                    pass

            next_version_num = max(version_numbers, default=0) + 1
            version_name = f"v{next_version_num}"

            # Create S3 paths list
            s3_paths = [f"{file_info['key']}" for file_info in files]

            # Create DatasetVersion
            dataset_version = DatasetVersion(
                id=uuid4(),
                dataset_id=dataset_id,
                version=version_name,
                s3_path=s3_paths[0] if len(s3_paths) == 1 else ",".join(s3_paths),
                cell_count=metadata.get("cell_count"),
                gene_count=metadata.get("gene_count"),
                file_format=metadata.get("file_format", "unknown"),
                extra_metadata={
                    "file_count": len(files),
                    "s3_paths": s3_paths,
                    "file_formats": metadata.get("file_formats", []),
                    "validation_results": metadata.get("validation_results", []),
                },
                created_at=datetime.utcnow(),
            )

            db.add(dataset_version)
            await db.commit()
            await db.refresh(dataset_version)

            activity.logger.info(
                f"DatasetVersion created successfully. ID: {dataset_version.id}, Version: {version_name}"
            )

            return {
                "dataset_version_id": str(dataset_version.id),
                "version": version_name,
                "s3_paths": s3_paths,
                "cell_count": dataset_version.cell_count,
                "gene_count": dataset_version.gene_count,
            }

        except Exception as e:
            await db.rollback()
            activity.logger.error(f"Failed to create DatasetVersion: {str(e)}")
            raise


@activity.defn
async def cleanup_s3_files(input: dict[str, Any]) -> None:
    """
    Cleanup S3 files on workflow failure (compensation logic).

    Args:
        input: Dictionary containing files to delete (list of dicts with 'bucket' and 'key')
    """
    activity.logger.info("Cleaning up S3 files after workflow failure")

    files = input.get("files", [])
    if not files:
        activity.logger.info("No files to clean up")
        return

    s3_service = S3Service()

    for file_info in files:
        bucket = file_info["bucket"]
        key = file_info["key"]

        try:
            s3_service.delete_file(bucket, key)
            activity.logger.info(f"Deleted S3 file: {bucket}/{key}")
        except Exception as e:
            activity.logger.error(f"Failed to delete S3 file {bucket}/{key}: {str(e)}")
            # Continue with other files even if one fails


def _infer_file_format(filename: str) -> str:
    """Infer file format from filename extension.

    Args:
        filename: Name of the file

    Returns:
        File format string (h5ad, 10x_h5, 10x_mtx, csv, tsv)
    """
    filename_lower = filename.lower()

    if filename_lower.endswith(".h5ad"):
        return "h5ad"
    elif filename_lower.endswith(".h5"):
        return "10x_h5"
    elif filename_lower.endswith((".zip", ".tar", ".tar.gz")) or "mtx" in filename_lower:
        return "10x_mtx"
    elif filename_lower.endswith((".csv", ".csv.gz", ".csv.bz2")):
        return "csv"
    elif filename_lower.endswith((".tsv", ".tsv.gz", ".txt", ".txt.gz", ".tab", ".tab.gz")):
        return "tsv"
    else:
        # Default to h5ad
        return "h5ad"
