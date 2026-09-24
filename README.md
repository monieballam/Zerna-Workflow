# Zerna

MIT-licensed, cloud-native single-cell analysis platform for multi-user research.

Zerna runs a Scanpy / scVI / CellTypist pipeline behind FastAPI, Temporal, PostgreSQL, Redis, and MinIO, with a Next.js explorer for run creation and results.

This repository is self-contained. It does not vendor a private research codebase.

## Architecture

- **Control plane** — FastAPI + PostgreSQL + Redis + Temporal
- **Scientific execution** — Temporal worker + Python methods (Scanpy, scVI, CellTypist)
- **Frontend** — Next.js 14 + React 19 + Deck.GL

The live run path is the Python/Temporal worker under [`workflows/`](./workflows). `services/compute` / Nextflow remains in the repo for compatibility and is not the default local path.

## Pipeline

QC → doublet detection → normalization → HVG → PCA → optional batch correction → clustering → UMAP → **CellTypist annotation** → differential expression → pathway scoring → ligand-receptor analysis

Annotation uses CellTypist (or optional conservative / marker-pack / hybrid modes shipped in this repo). There is no external knowledge-base checkout.

## Monorepo

```
zerna-platform/
├── apps/
│   ├── api/          # FastAPI control plane
│   └── web/          # Next.js frontend
├── packages/
│   ├── contracts/    # Shared Pydantic schemas
│   └── sdk/          # TypeScript SDK
├── services/
│   ├── compute/      # Optional Nextflow layer
│   └── gpu_abstraction/
├── methods/          # Scientific methods
├── workflows/        # Temporal workflows
├── infra/            # Prometheus / Grafana
├── scripts/          # Dev setup
└── docs/             # Architecture and ops
```

## Prerequisites

| Tool | Version | Purpose |
| --- | --- | --- |
| Docker | >= 24.0 | Local services |
| Docker Compose | >= 2.20 | Orchestration |
| Node.js | >= 20.0.0 | Frontend |
| pnpm | >= 8.0.0 | Node packages |
| Python | >= 3.11 | API and methods |
| uv | >= 0.4 | Python packages |

## Getting started

```bash
git clone https://github.com/monieballam-png/zerna-platform.git
cd zerna-platform
cp .env.example .env
pnpm install
./scripts/setup-dev-env.sh
uv run --directory apps/api alembic upgrade head
./scripts/start-api.sh
pnpm --dir apps/web dev
```

Local URLs:

| Service | URL |
| --- | --- |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Web | http://localhost:3000 |
| Temporal UI | http://localhost:8080 |
| MinIO API | http://localhost:19000 |
| MinIO console | http://localhost:19001 |

Default local credentials are development placeholders only (`zerna` / `zerna_dev_password`, MinIO `minioadmin` / `minioadmin`). Change them before any shared deployment.

## License

MIT — see [LICENSE](./LICENSE).
