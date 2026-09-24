# Zerna Operational Runbooks

> Note: this runbook still includes the ECS deployment/rollback path. The current lightweight server deployment also supports the EC2 Compose path via [`docker-compose.ec2.yml`](../docker-compose.ec2.yml); use the ECS sections only when you are operating that surface.

## Deployment Procedures

### CI/CD Pipeline

Zerna uses GitHub Actions for continuous deployment (`.github/workflows/cd-deploy.yml`).

**Trigger conditions:**

| Branch    | Environment | Trigger                                        |
| --------- | ----------- | ---------------------------------------------- |
| `staging` | Staging     | Automatic on push (after CI passes)            |
| `main`    | Production  | Automatic on push (after CI passes)            |
| Manual    | Either      | `workflow_dispatch` with environment selection |

**Deployment flow:**

1. CI Build workflow runs (lint, type-check, tests)
2. On success, CD Deploy workflow triggers
3. AWS credentials obtained via OIDC (no long-lived keys)
4. Docker images pushed to ECR
5. ECS services updated with `--force-new-deployment`
6. Wait for all services to stabilize
7. Smoke tests run (health check on API and Web)
8. On failure, rollback instructions are printed

**Deployed services:**

| Service  | ECS Service Name       | Description               |
| -------- | ---------------------- | ------------------------- |
| API      | `zerna-{env}-api`      | FastAPI control plane     |
| Web      | `zerna-{env}-web`      | Next.js frontend          |
| Temporal | `zerna-{env}-temporal` | Workflow orchestration    |
| Worker   | `zerna-{env}-worker`   | Temporal activity workers |

### Manual Deployment

To trigger a manual deployment:

1. Go to GitHub Actions → "CD Deploy" workflow
2. Click "Run workflow"
3. Select target environment (staging or production)
4. Production deployments require environment protection approval

---

## Rollback Procedures

### Automated Rollback

Use the rollback script to revert all ECS services to their previous task definition revision:

```bash
# Rollback staging
./scripts/rollback.sh staging

# Rollback production
./scripts/rollback.sh production

# Dry run (preview changes without applying)
./scripts/rollback.sh production --dry-run
```

The script:

1. Fetches the current task definition revision for each service
2. Computes the previous revision number
3. Updates each ECS service to the previous task definition
4. Waits for all services to stabilize
5. Prints a summary table

### Manual ECS Rollback

If the script is unavailable, roll back individual services manually:

```bash
# 1. Find the current task definition
aws ecs describe-services \
  --cluster zerna-production-cluster \
  --services zerna-production-api \
  --query "services[0].taskDefinition" \
  --output text

# 2. Determine the previous revision (e.g., :42 → :41)
# 3. Update the service
aws ecs update-service \
  --cluster zerna-production-cluster \
  --service zerna-production-api \
  --task-definition <previous-task-def-arn>

# 4. Wait for stability
aws ecs wait services-stable \
  --cluster zerna-production-cluster \
  --services zerna-production-api
```

Repeat for all four services: `api`, `web`, `temporal`, `worker`.

---

## Debugging Common Issues

### Service Health Checks

**API health check:**

```bash
# Local
curl http://localhost:8000/health

# Staging
curl https://api.staging.zerna.io/health

# Production
curl https://localhost:8000/health
```

Expected response: `{"status": "healthy", "service": "zerna-api"}`

**Docker service health:**

```bash
# Check all service statuses
docker-compose ps

# Check a specific service
docker-compose ps postgres
```

### Log Inspection

**Local development:**

```bash
# API logs
docker-compose logs -f zerna-api

# All infrastructure service logs
docker-compose logs -f

# Specific service logs
docker-compose logs -f postgres
docker-compose logs -f redis
docker-compose logs -f temporal
```

**ECS (production/staging):**

```bash
# Tail API logs
aws logs tail /ecs/zerna-production-api --follow

# Search for errors in the last hour
aws logs filter-log-events \
  --log-group-name /ecs/zerna-production-api \
  --start-time $(date -d '1 hour ago' +%s000) \
  --filter-pattern "ERROR"
```

### Trace Analysis

Zerna emits OpenTelemetry traces for all API requests and method executions.

**Jaeger UI:**

| Environment | URL                    |
| ----------- | ---------------------- |
| Local       | http://localhost:16686 |

**Common trace queries:**

1. **Slow API requests**: Search service `zerna-api`, sort by duration descending
2. **Failed runs**: Search for tag `run_id=<uuid>` to see the full execution trace
3. **Method execution**: Search service `zerna-api`, operation `method.<method_name>`

**Trace attributes available:**

| Attribute          | Description                                |
| ------------------ | ------------------------------------------ |
| `method.name`      | Scientific method name (e.g., `qc_filter`) |
| `method.version`   | Method version                             |
| `run_id`           | Pipeline run identifier                    |
| `org_id`           | Organization identifier                    |
| `http.method`      | HTTP method                                |
| `http.status_code` | Response status code                       |
| `request_id`       | Unique request identifier                  |

### Common Issues

**Run stuck in "queued" status:**

1. Check Temporal UI (http://localhost:8080) for workflow status
2. Look for failed activities in the workflow history
3. Check worker logs for errors:
   ```bash
   docker-compose logs -f worker
   ```

**Database connection errors:**

```bash
# Verify PostgreSQL is running and accepting connections
docker-compose exec postgres pg_isready -U zerna

# Check connection count
docker-compose exec postgres psql -U zerna -c "SELECT count(*) FROM pg_stat_activity;"
```

**Redis connection errors:**

```bash
# Verify Redis is running
docker-compose exec redis redis-cli -a zerna_redis_password ping
# Expected: PONG

# Check memory usage
docker-compose exec redis redis-cli -a zerna_redis_password info memory
```

**S3/MinIO upload failures:**

```bash
# Verify MinIO is healthy (use host API port from MINIO_PORT, default 19000)
curl http://localhost:19000/minio/health/live

# List buckets (inside the minio container, API is always :9000)
docker compose exec minio curl -sf http://localhost:9000/minio/health/live
```

**`XMinioStorageFull` / “minimum free drive threshold” (uploads still fail after code changes):**

This is returned by **MinIO when the backing volume has too little free space** (MinIO keeps a safety margin, often ~1% of capacity). **Fixing error messages in the app does not free disk.** You must delete objects, expand storage, or (dev only) reset the MinIO volume.

1. **Confirm host and Docker disk** (Docker Desktop / Linux often fills the VM disk before the host looks “empty”):

   ```bash
   docker system df
   df -h
   ```

2. **Delete pipeline artifacts** in the artifacts bucket (destructive; dev/staging typical). Keys live under `runs/<run-id>/` including `_state/snapshots/`. From repo root, with the same `S3_*` env as the API (see `.env.example`):

   ```bash
   export S3_ENDPOINT_URL=http://127.0.0.1:19000
   export S3_ACCESS_KEY_ID=minioadmin
   export S3_SECRET_ACCESS_KEY=minioadmin
   python scripts/prune_artifacts_bucket.py --dry-run
   python scripts/prune_artifacts_bucket.py
   ```

   To remove only one failed run:

   ```bash
   python scripts/prune_artifacts_bucket.py --prefix 'runs/<run-uuid>/'
   ```

   Equivalent with AWS CLI:

   ```bash
   aws s3 rm s3://zerna-artifacts-dev/runs/ --recursive --endpoint-url "$S3_ENDPOINT_URL"
   ```

3. **Expand capacity**: increase the Docker disk image size (Docker Desktop → Settings → Resources), or grow the Kubernetes PVC / VM disk where MinIO runs.

4. **Last resort (local compose, deletes all MinIO data):** stop stack, remove the named volume `zerna-minio-data`, start again — buckets are recreated by `minio-init`, but **all** uploaded datasets and artifacts are lost.

---

## Monitoring and Alerting

### Grafana Dashboards

| Environment | URL                   | Credentials           |
| ----------- | --------------------- | --------------------- |
| Local       | http://localhost:3001 | admin / zerna_grafana |

Dashboards are provisioned from `infra/grafana/dashboards/` and include:

- **API Overview**: Request rate, latency percentiles, error rate, active connections
- **Run Execution**: Run duration, success/failure rate, method execution times
- **Infrastructure**: PostgreSQL connections, Redis memory, S3 operations

### Prometheus Metrics

| Environment | URL                   |
| ----------- | --------------------- |
| Local       | http://localhost:9090 |

**Key metrics to monitor:**

| Metric                          | Description                   | Alert Threshold |
| ------------------------------- | ----------------------------- | --------------- |
| `http_request_duration_seconds` | API request latency           | p99 > 5s        |
| `http_requests_total`           | Total request count by status | 5xx rate > 1%   |
| `zerna_runs_active`             | Currently running pipelines   | > quota limit   |
| `zerna_run_duration_seconds`    | Pipeline execution time       | > 1 hour        |
| `process_resident_memory_bytes` | API memory usage              | > 2GB           |

**Useful PromQL queries:**

```promql
# API error rate (5xx) over last 5 minutes
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])

# p95 API latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Active runs per organization
zerna_runs_active{status="running"}
```

### Jaeger Tracing

| Environment | URL                    |
| ----------- | ---------------------- |
| Local       | http://localhost:16686 |

Traces are collected via OTLP (gRPC on port 4317, HTTP on port 4318).

**Trace investigation workflow:**

1. Start with the failing request's `request_id` (from API error response or logs)
2. Search Jaeger by tag `request_id=<value>`
3. Inspect the span waterfall for latency bottlenecks or errors
4. For pipeline runs, search by `run_id` to see the full execution trace across services

### Alerting Recommendations

| Alert           | Condition                    | Severity | Action                                |
| --------------- | ---------------------------- | -------- | ------------------------------------- |
| API Down        | Health check fails for 2 min | Critical | Check ECS service, restart if needed  |
| High Error Rate | 5xx rate > 5% for 5 min      | Critical | Check logs, consider rollback         |
| High Latency    | p99 > 10s for 10 min         | Warning  | Check database connections, Redis     |
| Run Failures    | > 3 consecutive failures     | Warning  | Check Temporal workflows, method logs |
| Disk Usage      | > 80% on any volume          | Warning  | Clean old artifacts, increase volume  |
| Memory Usage    | > 90% on API service         | Warning  | Check for memory leaks, scale up      |
