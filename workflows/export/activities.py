"""Activities for export workflow."""

import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from temporalio import activity

from apps.api.dependencies import _get_session_factory as _get_sf
from apps.api.models.pipeline import Run
from apps.api.services.s3_service import S3Service

logger = logging.getLogger(__name__)


@activity.defn
async def generate_h5ad(input: dict[str, Any]) -> dict[str, Any]:
    """
    Generate h5ad file with all annotations and embeddings.

    Args:
        input: Dictionary containing export_id and run_id

    Returns:
        Dictionary with h5ad generation results including:
        - success: bool indicating if generation succeeded
        - h5ad_path: str local path to generated h5ad file
        - error: optional error message if generation failed
    """
    export_id = input["export_id"]
    run_id = UUID(input["run_id"])

    activity.logger.info(f"Generating h5ad for run {run_id}")

    async with _get_sf()() as db:
        try:
            # Get the run to verify it exists
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()

            if run is None:
                return {
                    "success": False,
                    "error": f"Run {run_id} not found",
                }

            # TODO: Implement actual h5ad generation logic
            # This will be implemented in task 15 (Export and reproducibility)
            # For now, create a placeholder file to allow workflow testing
            #
            # Full implementation will:
            # 1. Load run artifacts (processed h5ad)
            # 2. Load all annotation revisions
            # 3. Load embeddings (UMAP, t-SNE)
            # 4. Merge all data into single h5ad
            # 5. Add metadata (software versions, parameters, provenance)
            # 6. Write to temporary file

            # Create temporary directory for export
            temp_dir = Path(tempfile.mkdtemp(prefix=f"export_{export_id}_"))
            h5ad_path = temp_dir / "data.h5ad"

            # Create placeholder file
            h5ad_path.write_text(f"Placeholder h5ad for run {run_id}")

            activity.logger.info(f"H5ad generation completed for run {run_id}. Path: {h5ad_path}")

            return {
                "success": True,
                "h5ad_path": str(h5ad_path),
            }

        except Exception as e:
            activity.logger.error(f"Failed to generate h5ad: {str(e)}")
            return {
                "success": False,
                "error": f"H5ad generation error: {str(e)}",
            }


@activity.defn
async def compile_report(input: dict[str, Any]) -> dict[str, Any]:
    """
    Compile reproducibility report with provenance information.

    Args:
        input: Dictionary containing run_id, export_id, and include_provenance flag

    Returns:
        Dictionary with report compilation results including:
        - success: bool indicating if compilation succeeded
        - report_path: str local path to generated report
        - error: optional error message if compilation failed
    """
    export_id = input["export_id"]
    run_id = UUID(input["run_id"])
    include_provenance = input.get("include_provenance", True)

    activity.logger.info(f"Compiling report for run {run_id} (provenance={include_provenance})")

    async with _get_sf()() as db:
        try:
            # Get the run with all metadata
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()

            if run is None:
                return {
                    "success": False,
                    "error": f"Run {run_id} not found",
                }

            # TODO: Implement actual report compilation logic
            # This will be implemented in task 15 (Export and reproducibility)
            # For now, create a placeholder HTML report
            #
            # Full implementation will:
            # 1. Load run metadata (parameters, software versions, random seed)
            # 2. Load pipeline template definition
            # 3. Load knowledge pack versions used
            # 4. Generate HTML report with:
            #    - Run summary
            #    - Pipeline parameters
            #    - Software versions
            #    - Random seeds
            #    - Provenance information (if include_provenance=True)
            #    - Method execution timeline
            # 5. Write to temporary file

            # Create temporary directory for export
            temp_dir = Path(tempfile.mkdtemp(prefix=f"export_{export_id}_"))
            report_path = temp_dir / "report.html"

            # Create placeholder HTML report
            html_content = f"""
            <html>
            <head><title>Reproducibility Report - Run {run_id}</title></head>
            <body>
                <h1>Reproducibility Report</h1>
                <p>Run ID: {run_id}</p>
                <p>Status: {run.status}</p>
                <p>Parameters: {run.parameters}</p>
                <p>Software Versions: {run.software_versions}</p>
                <p>Random Seed: {run.random_seed}</p>
                <p>Include Provenance: {include_provenance}</p>
            </body>
            </html>
            """
            report_path.write_text(html_content)

            activity.logger.info(
                f"Report compilation completed for run {run_id}. Path: {report_path}"
            )

            return {
                "success": True,
                "report_path": str(report_path),
            }

        except Exception as e:
            activity.logger.error(f"Failed to compile report: {str(e)}")
            return {
                "success": False,
                "error": f"Report compilation error: {str(e)}",
            }


@activity.defn
async def upload_to_s3(input: dict[str, Any]) -> dict[str, Any]:
    """
    Upload export artifacts to S3 and generate pre-signed download URLs.

    Args:
        input: Dictionary containing export_id, run_id, h5ad_path, and report_path

    Returns:
        Dictionary with S3 upload results including:
        - success: bool indicating if upload succeeded
        - h5ad_url: str pre-signed download URL for h5ad
        - report_url: str pre-signed download URL for report
        - h5ad_s3_path: str S3 path for h5ad (for cleanup)
        - report_s3_path: str S3 path for report (for cleanup)
        - error: optional error message if upload failed
    """
    export_id = input["export_id"]
    run_id = UUID(input["run_id"])
    h5ad_path = input.get("h5ad_path")
    report_path = input.get("report_path")

    activity.logger.info(f"Uploading export artifacts for run {run_id}")

    async with _get_sf()() as db:
        try:
            # Get the run to get organization_id
            stmt = select(Run).where(Run.id == run_id)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()

            if run is None:
                return {
                    "success": False,
                    "error": f"Run {run_id} not found",
                }

            # Initialize S3 service
            s3_service = S3Service()

            # Generate S3 paths for export artifacts
            h5ad_s3_path = s3_service.generate_artifact_path(
                org_id=run.organization_id,
                run_id=run_id,
                artifact_type="export",
                filename=f"{export_id}_data.h5ad",
            )

            report_s3_path = s3_service.generate_artifact_path(
                org_id=run.organization_id,
                run_id=run_id,
                artifact_type="export",
                filename=f"{export_id}_report.html",
            )

            # Upload h5ad file to S3
            if h5ad_path:
                h5ad_file = Path(h5ad_path)
                if not h5ad_file.exists():
                    return {
                        "success": False,
                        "error": f"H5ad file not found: {h5ad_path}",
                    }

                activity.logger.info(f"Uploading h5ad to {h5ad_s3_path}")
                s3_service.upload_file(
                    file_path=h5ad_file,
                    bucket=s3_service.artifacts_bucket,
                    s3_path=h5ad_s3_path,
                    content_type="application/octet-stream",
                )

            # Upload report file to S3
            if report_path:
                report_file = Path(report_path)
                if not report_file.exists():
                    return {
                        "success": False,
                        "error": f"Report file not found: {report_path}",
                    }

                activity.logger.info(f"Uploading report to {report_s3_path}")
                s3_service.upload_file(
                    file_path=report_file,
                    bucket=s3_service.artifacts_bucket,
                    s3_path=report_s3_path,
                    content_type="text/html",
                )

            # Generate pre-signed download URLs (valid for 7 days)
            h5ad_url = s3_service.generate_presigned_download_url(
                bucket=s3_service.artifacts_bucket,
                s3_path=h5ad_s3_path,
                expiration=7 * 24 * 3600,  # 7 days
            )

            report_url = s3_service.generate_presigned_download_url(
                bucket=s3_service.artifacts_bucket,
                s3_path=report_s3_path,
                expiration=7 * 24 * 3600,  # 7 days
            )

            # Clean up temporary files
            if h5ad_path:
                Path(h5ad_path).unlink(missing_ok=True)
                # Clean up temp directory
                Path(h5ad_path).parent.rmdir()

            if report_path:
                Path(report_path).unlink(missing_ok=True)
                # Clean up temp directory
                Path(report_path).parent.rmdir()

            activity.logger.info(
                f"Upload completed for run {run_id}. H5ad: {h5ad_s3_path}, Report: {report_s3_path}"
            )

            return {
                "success": True,
                "h5ad_url": h5ad_url,
                "report_url": report_url,
                "h5ad_s3_path": h5ad_s3_path,
                "report_s3_path": report_s3_path,
            }

        except Exception as e:
            activity.logger.error(f"Failed to upload to S3: {str(e)}")
            return {
                "success": False,
                "error": f"S3 upload error: {str(e)}",
            }


@activity.defn
async def cleanup_export_files(input: dict[str, Any]) -> None:
    """
    Cleanup export files from S3 on workflow failure (compensation logic).

    Args:
        input: Dictionary containing:
            - export_id: UUID of the export
            - h5ad_s3_path: optional S3 path for h5ad file
            - report_s3_path: optional S3 path for report file
    """
    export_id = input["export_id"]
    h5ad_s3_path = input.get("h5ad_s3_path")
    report_s3_path = input.get("report_s3_path")

    activity.logger.info(f"Cleaning up export files for export {export_id}")

    try:
        s3_service = S3Service()

        # Delete h5ad file if it was uploaded
        if h5ad_s3_path:
            try:
                s3_service.delete_file(
                    bucket=s3_service.artifacts_bucket,
                    s3_path=h5ad_s3_path,
                )
                activity.logger.info(f"Deleted h5ad file: {h5ad_s3_path}")
            except Exception as e:
                activity.logger.error(f"Failed to delete h5ad file {h5ad_s3_path}: {str(e)}")

        # Delete report file if it was uploaded
        if report_s3_path:
            try:
                s3_service.delete_file(
                    bucket=s3_service.artifacts_bucket,
                    s3_path=report_s3_path,
                )
                activity.logger.info(f"Deleted report file: {report_s3_path}")
            except Exception as e:
                activity.logger.error(f"Failed to delete report file {report_s3_path}: {str(e)}")

        activity.logger.info(f"Cleanup completed for export {export_id}")

    except Exception as e:
        activity.logger.error(f"Failed to cleanup export files for export {export_id}: {str(e)}")
        # Don't raise - cleanup is best-effort
