"""Export workflow definition."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.export.schemas import ExportInput, ExportOutput, ExportStatus


@workflow.defn
class ExportWorkflow:
    """
    Workflow for data export: h5ad generation → report compilation → S3 upload.

    This workflow orchestrates the export of analysis results:
    1. Generate h5ad file with all annotations and embeddings
    2. Compile reproducibility report with provenance information
    3. Upload export artifacts to S3
    4. Generate pre-signed download URLs
    """

    @workflow.run
    async def run(self, input: ExportInput) -> ExportOutput:
        """Execute the export workflow with compensation logic for partial exports."""

        # Configure retry policy for activities
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0,
            maximum_attempts=5,
        )

        workflow.logger.info(f"Starting export for run_id={input.run_id}")

        # Track uploaded files for cleanup on failure
        h5ad_s3_path = None
        report_s3_path = None

        try:
            # Step 1: Generate h5ad file
            workflow.logger.info("Generating h5ad file...")

            h5ad_result = await workflow.execute_activity(
                "generate_h5ad",
                input,
                start_to_close_timeout=timedelta(seconds=600),
                retry_policy=retry_policy,
            )

            if not h5ad_result.get("success"):
                workflow.logger.error(f"H5ad generation failed: {h5ad_result.get('error')}")
                return ExportOutput(
                    export_id=input.export_id,
                    status=ExportStatus.FAILED,
                    h5ad_url=None,
                    report_url=None,
                    error_message=h5ad_result.get("error"),
                )

            # Step 2: Compile reproducibility report
            workflow.logger.info("Compiling reproducibility report...")

            report_result = await workflow.execute_activity(
                "compile_report",
                {
                    "run_id": input.run_id,
                    "export_id": input.export_id,
                    "include_provenance": input.include_provenance,
                },
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            if not report_result.get("success"):
                workflow.logger.error(f"Report compilation failed: {report_result.get('error')}")
                return ExportOutput(
                    export_id=input.export_id,
                    status=ExportStatus.FAILED,
                    h5ad_url=None,
                    report_url=None,
                    error_message=report_result.get("error"),
                )

            # Step 3: Upload to S3 and generate download URLs
            workflow.logger.info("Uploading export artifacts to S3...")

            upload_result = await workflow.execute_activity(
                "upload_to_s3",
                {
                    "export_id": input.export_id,
                    "run_id": input.run_id,
                    "h5ad_path": h5ad_result.get("h5ad_path"),
                    "report_path": report_result.get("report_path"),
                },
                start_to_close_timeout=timedelta(seconds=600),
                retry_policy=retry_policy,
            )

            if not upload_result.get("success"):
                workflow.logger.error(f"S3 upload failed: {upload_result.get('error')}")
                # Cleanup any partial uploads
                await self._cleanup_partial_export(
                    input.export_id,
                    upload_result.get("h5ad_s3_path"),
                    upload_result.get("report_s3_path"),
                )
                return ExportOutput(
                    export_id=input.export_id,
                    status=ExportStatus.FAILED,
                    h5ad_url=None,
                    report_url=None,
                    error_message=upload_result.get("error"),
                )

            # Store S3 paths for potential cleanup
            h5ad_s3_path = upload_result.get("h5ad_s3_path")
            report_s3_path = upload_result.get("report_s3_path")

            workflow.logger.info("Export completed successfully")

            return ExportOutput(
                export_id=input.export_id,
                status=ExportStatus.COMPLETED,
                h5ad_url=upload_result.get("h5ad_url"),
                report_url=upload_result.get("report_url"),
                error_message=None,
            )

        except Exception as e:
            workflow.logger.error(f"Export failed with exception: {e}")
            # Cleanup any partial uploads
            await self._cleanup_partial_export(
                input.export_id,
                h5ad_s3_path,
                report_s3_path,
            )
            return ExportOutput(
                export_id=input.export_id,
                status=ExportStatus.FAILED,
                h5ad_url=None,
                report_url=None,
                error_message=str(e),
            )

    async def _cleanup_partial_export(
        self,
        export_id: str,
        h5ad_s3_path: str | None,
        report_s3_path: str | None,
    ) -> None:
        """
        Cleanup partial export files from S3 (compensation logic).

        Args:
            export_id: Export UUID
            h5ad_s3_path: Optional S3 path for h5ad file
            report_s3_path: Optional S3 path for report file
        """
        if not h5ad_s3_path and not report_s3_path:
            workflow.logger.info("No files to cleanup")
            return

        workflow.logger.info(
            f"Cleaning up partial export {export_id}. "
            f"H5ad: {h5ad_s3_path}, Report: {report_s3_path}"
        )

        try:
            await workflow.execute_activity(
                "cleanup_export_files",
                {
                    "export_id": export_id,
                    "h5ad_s3_path": h5ad_s3_path,
                    "report_s3_path": report_s3_path,
                },
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )
            workflow.logger.info(f"Cleanup completed for export {export_id}")
        except Exception as e:
            workflow.logger.error(f"Failed to cleanup partial export {export_id}: {e}")
            # Don't raise - cleanup is best-effort
