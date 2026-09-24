"""Run execution workflow definition."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.run_execution.schemas import (
        RunExecutionInput,
        RunExecutionOutput,
        RunStatus,
    )


@workflow.defn
class RunExecutionWorkflow:
    """
    Workflow for run execution: template resolution → pipeline execution → artifact collection.

    Steps:
    1. Resolve pipeline template and validate parameters
    2. Execute the pipeline (Python-based scanpy methods)
    3. Collect generated artifacts and store in S3
    4. Update run status in the database
    """

    @workflow.run
    async def run(self, input: RunExecutionInput) -> RunExecutionOutput:
        """Execute the run execution workflow."""

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0,
            maximum_attempts=5,
        )

        workflow.logger.info(f"Starting run execution for run_id={input.run_id}")

        try:
            # Step 1: Resolve template
            workflow.logger.info("Resolving pipeline template...")
            template_result = await workflow.execute_activity(
                "resolve_template",
                input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            )

            if not template_result.get("valid"):
                error = template_result.get("error", "Unknown template error")
                workflow.logger.error(f"Template resolution failed: {error}")
                await self._update_status(input.run_id, "failed", error)
                return RunExecutionOutput(
                    run_id=input.run_id,
                    status=RunStatus.FAILED,
                    artifacts=[],
                    error_message=error,
                )

            # Step 2: Execute pipeline (Python in worker via activities.execute_pipeline).
            # Dashboard runs do not use the optional /v1/nextflow API path here.
            workflow.logger.info("Executing pipeline...")
            pipeline_result = await workflow.execute_activity(
                "execute_pipeline",
                {
                    "run_id": str(input.run_id),
                    "dataset_version_id": str(input.dataset_version_id),
                    "template": template_result["template"],
                    "parameters": input.parameters,
                    "random_seed": input.random_seed,
                },
                start_to_close_timeout=timedelta(seconds=7200),  # 2 hours
                # Annotation (agent_v3) and heavy steps can stall heartbeats if the worker is
                # CPU-throttled, blocked on I/O, or the event loop is briefly saturated; 120s
                # is tight and surfaces as "Activity task timed out" mid-annotate.
                heartbeat_timeout=timedelta(seconds=600),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=120),
                    backoff_coefficient=2.0,
                    maximum_attempts=3,
                ),
            )

            if not pipeline_result.get("success"):
                error = pipeline_result.get("error", "Pipeline execution failed")
                workflow.logger.error(f"Pipeline failed: {error}")
                await self._update_status(input.run_id, "failed", error)
                return RunExecutionOutput(
                    run_id=input.run_id,
                    status=RunStatus.FAILED,
                    artifacts=[],
                    error_message=error,
                )

            # Step 3: Collect artifacts
            workflow.logger.info("Collecting artifacts...")
            artifacts_result = await workflow.execute_activity(
                "collect_artifacts",
                {
                    "run_id": str(input.run_id),
                    "artifact_s3_key": pipeline_result.get("artifact_s3_key"),
                    "artifact_size": pipeline_result.get("artifact_size", 0),
                    "additional_artifacts": pipeline_result.get("additional_artifacts", []),
                    "software_versions": pipeline_result.get("software_versions", {}),
                    "step_metrics": pipeline_result.get("step_metrics", {}),
                },
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            # Step 4: Update run status to COMPLETED
            await self._update_status(input.run_id, "completed")

            workflow.logger.info(
                f"Run completed. {artifacts_result.get('artifact_count', 0)} artifacts collected."
            )
            return RunExecutionOutput(
                run_id=input.run_id,
                status=RunStatus.COMPLETED,
                artifacts=artifacts_result.get("artifact_ids", []),
                error_message=None,
            )

        except Exception as e:
            workflow.logger.error(f"Run execution failed: {e}")
            # Try cleanup
            try:
                await workflow.execute_activity(
                    "cleanup_run_resources",
                    {"run_id": str(input.run_id), "artifacts": []},
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=10),
                        backoff_coefficient=2.0,
                    ),
                )
            except Exception as cleanup_err:
                workflow.logger.error(f"Cleanup failed: {cleanup_err}")

            await self._update_status(input.run_id, "failed", str(e))
            return RunExecutionOutput(
                run_id=input.run_id,
                status=RunStatus.FAILED,
                artifacts=[],
                error_message=str(e),
            )

    async def _update_status(self, run_id, status: str, error_message: str = None):
        """Helper to call the update_run_status_activity."""
        try:
            await workflow.execute_activity(
                "update_run_status_activity",
                {
                    "run_id": str(run_id),
                    "status": status,
                    "error_message": error_message,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    maximum_attempts=5,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )
        except Exception as e:
            workflow.logger.error(f"Failed to update run status: {e}")
