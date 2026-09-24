"""Dataset ingestion workflow definition."""

from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from workflows.dataset_ingestion.schemas import (
        DatasetIngestionInput,
        DatasetIngestionOutput,
    )


@workflow.defn
class DatasetIngestionWorkflow:
    """
    Workflow for dataset ingestion: file upload → validation → metadata extraction.

    This workflow orchestrates the process of ingesting a new dataset:
    1. Validate uploaded files (format, structure)
    2. Extract metadata (cell count, gene count)
    3. Store files in S3 with organization-scoped paths and create DatasetVersion
    4. Emit event on completion for downstream processing
    5. Cleanup S3 files on failure (compensation logic)
    """

    @workflow.run
    async def run(self, input: DatasetIngestionInput) -> DatasetIngestionOutput:
        """Execute the dataset ingestion workflow."""

        # Configure retry policy for activities
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0,
            maximum_attempts=5,
        )

        # Track whether we need to cleanup on failure
        files_to_cleanup = []

        try:
            # Step 1: Validate files
            workflow.logger.info(f"Starting dataset ingestion for dataset_id={input.dataset_id}")

            # Convert input to dict for activity
            input_dict = {
                "dataset_id": str(input.dataset_id),
                "organization_id": str(input.organization_id),
                "files": [{"bucket": f.bucket, "key": f.key} for f in input.files],
            }

            # Track files for potential cleanup
            files_to_cleanup = input_dict["files"]

            validation_result = await workflow.execute_activity(
                "validate_files",
                input_dict,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            if not validation_result.get("valid"):
                workflow.logger.error(f"File validation failed: {validation_result['errors']}")

                # Cleanup S3 files on validation failure
                await self._cleanup_files(files_to_cleanup)

                return DatasetIngestionOutput(
                    dataset_version_id=None,
                    cell_count=0,
                    gene_count=0,
                    validation_errors=validation_result["errors"],
                )

            # Step 2: Extract metadata
            workflow.logger.info("Files validated, extracting metadata...")

            # Pass validation results to metadata extraction
            metadata_input = {
                **input_dict,
                "validation_results": validation_result.get("validation_results", []),
            }

            metadata_result = await workflow.execute_activity(
                "extract_metadata",
                metadata_input,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            # Step 3: Store in S3 and create DatasetVersion
            workflow.logger.info("Metadata extracted, creating DatasetVersion...")

            storage_result = await workflow.execute_activity(
                "store_in_s3",
                {
                    "dataset_id": str(input.dataset_id),
                    "organization_id": str(input.organization_id),
                    "files": input_dict["files"],
                    "metadata": metadata_result,
                },
                start_to_close_timeout=timedelta(seconds=600),
                retry_policy=retry_policy,
            )

            workflow.logger.info(
                f"Dataset ingestion completed successfully. "
                f"DatasetVersion ID: {storage_result['dataset_version_id']}, "
                f"Version: {storage_result.get('version', 'unknown')}"
            )

            # TODO: Emit event for downstream processing (e.g., trigger analysis pipeline)
            # This will be implemented when event system is added

            return DatasetIngestionOutput(
                dataset_version_id=UUID(storage_result["dataset_version_id"]),
                cell_count=storage_result.get("cell_count", metadata_result["cell_count"]),
                gene_count=storage_result.get("gene_count", metadata_result["gene_count"]),
                validation_errors=[],
            )

        except ActivityError as e:
            # Compensation: cleanup S3 files on workflow failure
            workflow.logger.error(f"Dataset ingestion failed: {str(e)}. Initiating cleanup...")

            await self._cleanup_files(files_to_cleanup)

            # Re-raise to mark workflow as failed
            raise

        except Exception as e:
            # Catch any other exceptions and cleanup
            workflow.logger.error(
                f"Unexpected error during dataset ingestion: {str(e)}. Initiating cleanup..."
            )

            await self._cleanup_files(files_to_cleanup)

            # Re-raise to mark workflow as failed
            raise

    async def _cleanup_files(self, files: list[dict]) -> None:
        """Cleanup S3 files (compensation logic).

        Args:
            files: List of file dicts with 'bucket' and 'key' keys
        """
        if not files:
            return

        workflow.logger.info(f"Cleaning up {len(files)} S3 files...")

        try:
            await workflow.execute_activity(
                "cleanup_s3_files",
                {"files": files},
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )
            workflow.logger.info("S3 cleanup completed")
        except Exception as e:
            # Log but don't fail workflow on cleanup errors
            workflow.logger.error(f"Failed to cleanup S3 files: {str(e)}")
