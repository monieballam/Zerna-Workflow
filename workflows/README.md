# Workflows

This directory contains Temporal workflow definitions for product operations:

- `dataset_ingestion/` - File upload → validation → metadata extraction
- `run_execution/` - Template resolution → Python pipeline execution → artifact collection
- `export/` - h5ad generation → report compilation → S3 upload
- `cross_dataset_pathway/` - Multi-dataset aggregation → LLM interpretation → insight generation

## Architecture

The workflows use Temporal for orchestration. The active run path executes the scientific pipeline inside the Temporal worker with Scanpy/scVI-based Python methods.

### Components

- **worker.py**: Main worker process that connects to Temporal and registers workflows/activities
- **config.py**: Configuration management for Temporal connection and retry policies
- **Workflows**: Define the high-level orchestration logic
- **Activities**: Implement the orchestration steps and the active Python pipeline runner

### Run Execution Notes

`RunExecutionWorkflow` still uses one long `execute_pipeline` activity for the active pipeline path, but that activity now has internal hardening:

- scientific steps run in subprocesses, not threads
- per-step snapshots are stored durably in S3/MinIO
- checkpoint metadata is stored on the `Run` row in PostgreSQL
- the API stale-run reconciler can restart stranded runs from checkpoint or mark them failed clearly

### Retry Policies

All activities are configured with exponential backoff retry policies:

- Initial interval: 1 second
- Maximum interval: 60 seconds
- Backoff coefficient: 2.0
- Maximum attempts: 5

This ensures transient errors (network issues, temporary service unavailability) are automatically retried.

## Running the Worker

### Prerequisites

1. Ensure the Docker services are running:

   ```bash
   ./scripts/setup-dev-env.sh
   ```

2. Set up environment variables (copy `.env.example` to `.env` and configure)

### Start the Worker

From the repository root:

```bash
# Follow logs for the supervised Docker Compose worker
./scripts/start-worker.sh

# Or start the compose service directly
docker compose up -d worker

# Or run locally without supervision
./scripts/start-worker.sh --local
```

The worker will:

1. Connect to the Temporal server at `TEMPORAL_ADDRESS`
2. Register all workflows and activities
3. Start polling the `TEMPORAL_TASK_QUEUE` for work
4. Execute workflows and activities as they are triggered

### Monitoring

- **Temporal UI**: http://localhost:8080 (default)
  - View workflow executions
  - Inspect activity history
  - Debug failures

- **Logs**: The worker outputs structured logs with workflow/activity execution details

### Graceful Shutdown

The worker handles SIGINT and SIGTERM signals for graceful shutdown:

- Press Ctrl+C to stop the worker
- In-flight activity retries are handled by Temporal
- Resume after crashes depends on the durable checkpoint/snapshot state for that run

## Development

### Adding a New Workflow

1. Create a new directory under `workflows/` (e.g., `workflows/my_workflow/`)
2. Create the following files:
   - `__init__.py`: Export the workflow class
   - `workflow.py`: Define the workflow using `@workflow.defn`
   - `activities.py`: Define activities using `@activity.defn`
   - `schemas.py`: Define Pydantic models for input/output

3. Register the workflow and activities in `worker.py`:

   ```python
   from workflows.my_workflow.workflow import MyWorkflow
   from workflows.my_workflow.activities import my_activity

   # Add to Worker constructor
   workflows=[..., MyWorkflow],
   activities=[..., my_activity],
   ```

### Testing Workflows

Temporal provides testing utilities for unit testing workflows:

```python
from temporalio.testing import WorkflowEnvironment
from workflows.my_workflow.workflow import MyWorkflow

async def test_my_workflow():
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test",
            workflows=[MyWorkflow],
            activities=[...],
        ):
            result = await env.client.execute_workflow(
                MyWorkflow.run,
                input_data,
                id="test-workflow",
                task_queue="test",
            )
            assert result.status == "completed"
```

## Configuration

Key environment variables (see `.env.example`):

- `TEMPORAL_ADDRESS`: Temporal server address (default: `localhost:7233`)
- `TEMPORAL_NAMESPACE`: Temporal namespace (default: `default`)
- `TEMPORAL_TASK_QUEUE`: Task queue name (default: `zerna-control-plane`)
- `ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS`: Activity timeout baseline (default: 300)
- `WORKFLOW_EXECUTION_TIMEOUT_SECONDS`: Workflow timeout (default: 3600)
- `STALE_RUN_RECONCILER_ENABLED`: Enable API-side stale-run reconciliation
- `STALE_RUN_THRESHOLD_SECONDS`: Age threshold before a RUNNING run is treated as stale

## Troubleshooting

### Worker won't connect to Temporal

- Verify Temporal is running: `docker compose ps temporal`
- Check Temporal health: `docker compose exec temporal tctl cluster health`
- Verify `TEMPORAL_ADDRESS` in `.env`

### Activities timing out

- Increase `ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS` for long-running activities
- Check activity logs for errors
- Verify external services (database, S3) are accessible

### Workflows stuck in running state

- Check Temporal UI for activity failures
- Verify worker is running and polling the correct task queue
- Check `docker compose logs worker`
- Check whether the API stale-run reconciler has already retried or failed the run
