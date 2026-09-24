# Docker Development Environment

This repo has more than one Docker surface. The important distinction is that the root [`docker-compose.yml`](./docker-compose.yml) is the **local scientific runtime**, not the full production app by itself.

## What Is Actually Used

### Core local stack

These services are part of the normal local development/runtime path:

- `postgres`: application metadata and Temporal persistence
- `redis`: cache/session/task support
- `temporal`: workflow orchestration
- `minio`: local S3-compatible object storage
- `minio-init`: one-shot bucket bootstrap
- `worker`: supervised Temporal worker that executes the live pipeline

### Optional local observability

These services are available only with `--profile observability`:

- `jaeger`
- `prometheus`
- `grafana`

### Not in the root compose file

- `api` and `web` are usually started from the host in local development
- [`docker-compose.ec2.yml`](./docker-compose.ec2.yml) adds `api` and `web` for EC2 deployments
- `services/compute` / Nextflow code remains in the repo, but it is not the default live execution path today

## Quick Start

### Core stack

```bash
cp .env.example .env
./scripts/setup-dev-env.sh
```

### Core stack plus observability

```bash
cp .env.example .env
./scripts/setup-dev-env.sh --with-observability
```

The setup script:

- starts the Docker services
- waits for the core stack to become healthy
- syncs the Python workspace
- installs the R-backed scientific method dependencies
- leaves the worker running as a supervised Docker Compose service

## Manual Compose Commands

### Start core services

```bash
docker compose up -d
```

### Start core services plus observability

```bash
docker compose --profile observability up -d
```

### Stop services

```bash
docker compose down
```

### Stop services and remove volumes

```bash
docker compose down -v
```

## Local App Process Model

After the Docker stack is up:

```bash
uv run --directory apps/api alembic upgrade head
./scripts/start-api.sh
pnpm --dir apps/web dev
```

The worker does **not** need to be started separately if you used `./scripts/setup-dev-env.sh`; it is already running in Docker. Use `./scripts/start-worker.sh` only when you want to follow/restart the supervised worker logs, or `./scripts/start-worker.sh --local` for an unsupervised host worker.

## Local URLs

### Core stack

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Web: `http://localhost:3000`
- Temporal UI: `http://localhost:8080`
- MinIO API (host): `http://localhost:19000`
- MinIO Console: `http://localhost:19001`

### Observability profile only

- Jaeger UI: `http://localhost:16686`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

## Default Local Credentials

- PostgreSQL: `zerna` / `zerna_dev_password`
- Redis: password `zerna_redis_password`
- MinIO: `minioadmin` / `minioadmin`
- Grafana: `admin` / `zerna_grafana` when observability is enabled

The application itself does not seed a default admin login account.

## Volumes And Persistence

The root compose file persists data in named volumes:

- `zerna-postgres-data`
- `zerna-redis-data`
- `zerna-temporal-data`
- `zerna-minio-data`
- `zerna-prometheus-data` when observability is enabled
- `zerna-grafana-data` when observability is enabled
- `zerna-worker-checkpoints`
- `zerna-worker-celltypist-cache`

`minio-init` is a bootstrap container, not a persistent service.

## Notes On Accuracy

- The root compose file is the source of truth for which containers are actually used.
- Observability is opt-in.
- EC2 deployment uses the core compose stack plus [`docker-compose.ec2.yml`](./docker-compose.ec2.yml), not the host-local dev process model.
