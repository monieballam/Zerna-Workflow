# Temporal Setup Guide

This guide explains how to set up and configure Temporal for the Zerna platform.

## Overview

Temporal is used for orchestrating product-level workflows in the Control Plane:

- **Dataset Ingestion**: File upload → validation → metadata extraction
- **Run Execution**: Template resolution → Python pipeline execution → artifact collection
- **Export**: h5ad generation → report compilation → S3 upload
- **Cross-Dataset Pathway Analysis**: Multi-dataset aggregation → LLM interpretation

## Architecture

```
┌─────────────────┐
│   FastAPI API   │
│  (Control Plane)│
└────────┬────────┘
         │ Start Workflow
         ▼
┌─────────────────┐
│ Temporal Server │
│   (Orchestrator)│
└────────┬────────┘
         │ Execute Activities
         ▼
┌─────────────────┐
│ Temporal Worker │
│   (This Process)│
└────────┬────────┘
         │ Call Services
         ▼
┌─────────────────┐
│ Database, Redis,│
│ S3, Methods     │
└─────────────────┘
```

## Prerequisites

1. **Docker and Docker Compose** installed
2. **Python 3.11+** with uv or pip
3. **PostgreSQL** (provided by Docker Compose)

## Quick Start

### 1. Start Temporal Server

```bash
# Start infra + supervised worker
./scripts/setup-dev-env.sh

# Verify Temporal is running
docker compose ps temporal

# Check Temporal health
docker compose exec temporal tctl cluster health
```

### 2. Configure Environment

Copy `.env.example` to `.env` and ensure these variables are set:

```bash
# Temporal Configuration
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=zerna-control-plane

# Database (for activities)
DATABASE_URL=postgresql://zerna:zerna_dev_password@localhost:5432/zerna

# Redis (for activities)
REDIS_URL=redis://:zerna_redis_password@localhost:6379/0

# S3 (for activities)
S3_ENDPOINT_URL=http://localhost:19000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_DATASETS_BUCKET=zerna-datasets-dev
S3_ARTIFACTS_BUCKET=zerna-artifacts-dev
```

### 3. Start the Worker

```bash
# Follow logs for the supervised Docker Compose worker
./scripts/start-worker.sh

# Or start the compose service directly
docker compose up -d worker

# Or run locally without supervision
./scripts/start-worker.sh --local
```

You should see output like:

```
INFO - Connecting to Temporal at localhost:7233, namespace: default
INFO - Connected to Temporal server
INFO - Starting worker on task queue: zerna-control-plane
INFO - Registered workflows: DatasetIngestionWorkflow, RunExecutionWorkflow, ExportWorkflow, CrossDatasetPathwayWorkflow
INFO - Registered 17 activities
```

The Docker Compose `worker` service is configured with `restart: unless-stopped`, so a crash will
cause Docker to relaunch it automatically. The service also stores checkpoints in a persistent
Docker volume, while active run checkpoints/snapshots are stored durably in PostgreSQL + S3/MinIO.

### 4. Verify Setup

```bash
# Run connection tests
python -m pytest workflows/tests/test_worker_connection.py -v

# Or run directly
python workflows/tests/test_worker_connection.py
```

## Temporal UI

Access the Temporal Web UI at: http://localhost:8080

The UI allows you to:

- View all workflow executions
- Inspect workflow history and state
- Debug failed workflows
- Manually trigger workflows
- View activity execution details

## Configuration

### Retry Policies

Activities are configured with exponential backoff:

```python
RetryPolicy(
    initial_interval=timedelta(seconds=1),      # Start with 1s delay
    maximum_interval=timedelta(seconds=60),     # Cap at 60s delay
    backoff_coefficient=2.0,                    # Double delay each retry
    maximum_attempts=5,                         # Try up to 5 times
)
```

This means:

- Attempt 1: Immediate
- Attempt 2: 1s delay
- Attempt 3: 2s delay
- Attempt 4: 4s delay
- Attempt 5: 8s delay

### Timeouts

**Activity Timeouts:**

- `start_to_close_timeout`: Maximum time for activity execution
  - Short activities (validation): 60s
  - Medium activities (metadata extraction): 300s (5 min)
  - Long activities (pipeline execution): 7200s (2 hours)
- `heartbeat_timeout`: The active run execution activity heartbeats every 15 seconds and times out after 60 seconds without a heartbeat

**Workflow Timeouts:**

- `execution_timeout`: Maximum time for entire workflow (3600s = 1 hour)
- `run_timeout`: Maximum time for a single workflow run (3600s = 1 hour)

### Task Queue

The worker polls the `zerna-control-plane` task queue. All workflows started by the API must use this task queue name.

## Recovery Model

The current run execution workflow is still one long activity, but it is hardened for recovery:

- scientific steps run in subprocesses instead of worker threads
- per-step snapshots are uploaded to S3/MinIO
- checkpoint metadata is stored on the `Run` row in PostgreSQL
- the API runs a stale-run reconciler that can re-dispatch stale runs from checkpoint or mark them failed with a clear reason

## Workflow Execution

### From Python Code

```python
from temporalio.client import Client
from workflows.dataset_ingestion.schemas import DatasetIngestionInput, S3Path

# Connect to Temporal
client = await Client.connect("localhost:7233")

# Start a workflow
input_data = DatasetIngestionInput(
    dataset_id=dataset_id,
    organization_id=org_id,
    files=[S3Path(bucket="bucket", key="file.h5ad")],
)

handle = await client.start_workflow(
    "DatasetIngestionWorkflow",
    input_data,
    id=f"dataset-ingestion-{dataset_id}",
    task_queue="zerna-control-plane",
)

# Wait for result
result = await handle.result()
print(f"Dataset version: {result.dataset_version_id}")
```

### From the API

The FastAPI application will start workflows via the Temporal client when users trigger actions (upload dataset, start run, export results).

## Monitoring

### Logs

The worker outputs structured logs:

```
INFO - Starting dataset ingestion for dataset_id=123e4567-e89b-12d3-a456-426614174000
INFO - Files validated, extracting metadata...
INFO - Metadata extracted, storing files in S3...
INFO - Dataset ingestion completed successfully. DatasetVersion ID: 789e0123-e89b-12d3-a456-426614174000
```

### Metrics

Temporal automatically tracks:

- Workflow execution count
- Workflow success/failure rate
- Activity execution time
- Activity retry count

Access metrics via the Temporal UI or export to Prometheus.

### Distributed Tracing

The worker is configured with OpenTelemetry to emit traces to Jaeger:

- Endpoint: http://localhost:4317 (OTLP gRPC)
- Service name: `zerna-workflows`

View traces at: http://localhost:16686 (Jaeger UI)

## Troubleshooting

### Worker won't start

**Error: `Connection refused`**

- Temporal server is not running
- Solution: `docker compose up -d temporal`

**Error: `Invalid namespace`**

- Namespace doesn't exist
- Solution: Use `default` namespace or create a new one via `tctl`

### Workflows not executing

**Symptom: Workflows stay in "Running" state**

- Worker is not running or not polling the correct task queue
- Solution: Verify worker is running and check `TEMPORAL_TASK_QUEUE` matches

**Symptom: Activities timing out**

- Activity is taking longer than `start_to_close_timeout`
- Solution: Increase timeout in workflow definition

### Activities failing

**Check activity logs:**

```bash
# Worker logs show activity execution details
docker compose logs worker -f
```

**Check Temporal UI:**

- Navigate to the workflow execution
- Click on the failed activity
- View the error message and stack trace

### Database connection errors

**Error: `Connection refused` to PostgreSQL**

- Database is not running
- Solution: `docker compose up -d postgres`

**Error: `Authentication failed`**

- Incorrect credentials in `.env`
- Solution: Verify `DATABASE_URL` matches the Docker Compose settings

## Production Considerations

### High Availability

For production, run multiple worker instances:

```bash
# Docker Compose / container orchestrator
docker compose up -d --scale worker=3 worker
```

Temporal will automatically distribute work across workers.

### Scaling

- **Horizontal scaling**: Add more worker instances
- **Vertical scaling**: Increase worker resources (CPU, memory)
- **Activity concurrency**: Configure max concurrent activities per worker

### Monitoring

- Set up Prometheus metrics export
- Configure alerting for workflow failures
- Monitor worker health and task queue lag

### Security

- Use TLS for Temporal connections in production
- Rotate credentials regularly
- Use secret management (AWS Secrets Manager, HashiCorp Vault)
- Implement mTLS for worker authentication

## Development

### Adding a New Workflow

See the main [README.md](./README.md) for instructions on adding new workflows.

### Testing Workflows

Use Temporal's testing utilities:

```python
from temporalio.testing import WorkflowEnvironment

async def test_my_workflow():
    async with await WorkflowEnvironment.start_local() as env:
        # Test workflow in isolated environment
        ...
```

### Debugging

1. **Enable debug logging:**

   ```bash
   LOG_LEVEL=DEBUG ./scripts/start-worker.sh --local
   ```

2. **Use Temporal UI:**
   - View workflow execution history
   - Inspect activity inputs/outputs
   - See retry attempts and errors

3. **Add breakpoints:**
   ```python
   @activity.defn
   async def my_activity(input):
       import pdb; pdb.set_trace()  # Debugger
       ...
   ```

## References

- [Temporal Documentation](https://docs.temporal.io/)
- [Temporal Python SDK](https://docs.temporal.io/dev-guide/python)
- [Temporal Best Practices](https://docs.temporal.io/dev-guide/best-practices)
