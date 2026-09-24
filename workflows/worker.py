"""Temporal worker for Control Plane workflows."""

# Before any imports that may load Numba (in-process cluster/embed steps): TBB layer often
# breaks in slim images; workqueue is always available.
import os

_numba_tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
if _numba_tl in ("", "tbb"):
    os.environ["NUMBA_THREADING_LAYER"] = "workqueue"

import asyncio
import logging
import signal
import sys
from pathlib import Path

from zerna_contracts.pipeline_methods import METHOD_REGISTRY
from temporalio.client import Client
from temporalio.worker import Worker

from workflows.config import get_workflow_settings
from workflows.cross_dataset_pathway.activities import (
    aggregate_pathways,
    call_llm,
    fetch_datasets,
    update_analysis_status,
)
from workflows.cross_dataset_pathway.workflow import CrossDatasetPathwayWorkflow
from workflows.dataset_ingestion.activities import (
    cleanup_s3_files,
    extract_metadata,
    store_in_s3,
    validate_files,
)
from workflows.dataset_ingestion.workflow import DatasetIngestionWorkflow
from workflows.export.activities import (
    cleanup_export_files,
    compile_report,
    generate_h5ad,
    upload_to_s3,
)
from workflows.export.workflow import ExportWorkflow
from workflows.run_execution.activities import (
    cleanup_run_resources,
    collect_artifacts,
    execute_pipeline,
    resolve_template,
    update_run_status_activity,
)
from workflows.run_execution.workflow import RunExecutionWorkflow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _configure_local_numba_threading() -> None:
    """Ensure Numba does not use a broken TBB backend (see module-level env fix)."""
    tl = os.environ.get("NUMBA_THREADING_LAYER", "").strip().lower()
    if tl in ("", "tbb"):
        os.environ["NUMBA_THREADING_LAYER"] = "workqueue"
        logger.info("NUMBA_THREADING_LAYER forced to 'workqueue' (was %r)", tl or None)


class WorkerManager:
    """Manages Temporal worker lifecycle."""

    def __init__(self):
        self.settings = get_workflow_settings()
        self.client: Client | None = None
        self.worker: Worker | None = None
        self.shutdown_event = asyncio.Event()
        ready_file = self.settings.worker_ready_file
        self.ready_file = Path(ready_file) if ready_file else None

    def _set_ready(self, ready: bool) -> None:
        """Persist or clear the worker readiness marker."""
        if self.ready_file is None:
            return

        try:
            if ready:
                self.ready_file.parent.mkdir(parents=True, exist_ok=True)
                self.ready_file.write_text(str(os.getpid()), encoding="utf-8")
            else:
                self.ready_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to update worker readiness marker %s: %s", self.ready_file, exc)

    async def start(self):
        """Start the Temporal worker."""
        self._set_ready(False)
        logger.info(
            "Pipeline METHOD_REGISTRY ready (%d steps): %s",
            len(METHOD_REGISTRY),
            sorted(METHOD_REGISTRY),
        )
        logger.info(
            f"Connecting to Temporal at {self.settings.temporal_address}, "
            f"namespace: {self.settings.temporal_namespace}"
        )

        # Connect to Temporal server
        self.client = await Client.connect(
            self.settings.temporal_address,
            namespace=self.settings.temporal_namespace,
        )

        logger.info("Connected to Temporal server")

        # Create worker with all workflows and activities
        self.worker = Worker(
            self.client,
            task_queue=self.settings.temporal_task_queue,
            max_concurrent_activities=self.settings.temporal_max_concurrent_activities,
            max_concurrent_workflow_tasks=self.settings.temporal_max_concurrent_workflow_tasks,
            workflows=[
                DatasetIngestionWorkflow,
                RunExecutionWorkflow,
                ExportWorkflow,
                CrossDatasetPathwayWorkflow,
            ],
            activities=[
                # Dataset ingestion activities
                validate_files,
                extract_metadata,
                store_in_s3,
                cleanup_s3_files,
                # Run execution activities
                resolve_template,
                execute_pipeline,
                collect_artifacts,
                cleanup_run_resources,
                update_run_status_activity,
                # Export activities
                generate_h5ad,
                compile_report,
                upload_to_s3,
                cleanup_export_files,
                # Cross-dataset pathway activities
                fetch_datasets,
                aggregate_pathways,
                call_llm,
                update_analysis_status,
            ],
        )

        logger.info(f"Starting worker on task queue: {self.settings.temporal_task_queue}")
        logger.info(
            "Worker concurrency: %s activities, %s workflow tasks",
            self.settings.temporal_max_concurrent_activities,
            self.settings.temporal_max_concurrent_workflow_tasks,
        )
        logger.info(
            "Registered workflows: DatasetIngestionWorkflow, RunExecutionWorkflow, "
            "ExportWorkflow, CrossDatasetPathwayWorkflow"
        )
        logger.info(f"Registered {17} activities")
        self._set_ready(True)

        # Run worker until shutdown
        await self.worker.run()

    async def stop(self):
        """Stop the Temporal worker gracefully."""
        logger.info("Shutting down worker...")
        self.shutdown_event.set()
        self._set_ready(False)

        if self.worker:
            # Worker.run() will exit when interrupted
            logger.info("Worker stopped")

    def handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(self.stop())


async def main():
    """Main entry point for the worker."""
    _configure_local_numba_threading()
    manager = WorkerManager()

    # Register signal handlers
    signal.signal(signal.SIGINT, manager.handle_signal)
    signal.signal(signal.SIGTERM, manager.handle_signal)

    try:
        await manager.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
