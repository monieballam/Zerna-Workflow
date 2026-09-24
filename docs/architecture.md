# Zerna Architecture

> Note: parts of this document still describe the broader cloud/ECS target architecture. The currently validated lightweight deployment path in this repo is the Temporal worker runtime plus the EC2 Compose surface documented in [`README.md`](../README.md) and [`DOCKER_SETUP.md`](../DOCKER_SETUP.md).

## Overview

Zerna is a cloud-native single-cell analysis platform with a clean separation between the **Control Plane** (product workflows, metadata, API) and the **Compute Plane** (scientific pipeline execution). A **Frontend** application provides interactive data exploration.

## System Context

```mermaid
graph TB
    Analyst[Analyst / Scientist]
    Admin[Platform Admin]

    Analyst --> Web[Web Application<br/>Next.js 14 + React 19]
    Admin --> Web

    Web --> API[Control Plane API<br/>FastAPI + Pydantic v2]

    API --> PG[(PostgreSQL<br/>Metadata + Audit)]
    API --> Redis[(Redis<br/>Cache + Rate Limiting)]
    API --> Temporal[Temporal Server<br/>Workflow Orchestration]
    API --> S3[(S3 / MinIO<br/>Datasets + Artifacts)]

    Temporal --> Compute[Compute Plane<br/>Nextflow + Containers]
    Compute --> Methods[Scientific Methods<br/>scanpy, scvi, CellTypist, LIANA]
    Compute --> GPU[GPU Abstraction<br/>CUDA, ROCm, Metal, OpenCL, TPU]
    Compute --> S3

    API --> Jaeger[Jaeger<br/>Distributed Tracing]
    API --> Prometheus[Prometheus<br/>Metrics]
    Prometheus --> Grafana[Grafana<br/>Dashboards]
```

---

## Control Plane

The Control Plane is a FastAPI application (`apps/api`) backed by PostgreSQL, Redis, and Temporal. It handles authentication, metadata management, API routing, and product workflow orchestration.

### Control Plane Architecture

```mermaid
graph LR
    subgraph "Control Plane (apps/api)"
        Router[API Router<br/>FastAPI + Pydantic v2]
        Auth[Auth Service<br/>OAuth2 + JWT]
        RateLimit[Rate Limiter<br/>Token Bucket]
        Tracing[Observability<br/>OpenTelemetry]
    end

    subgraph "Services"
        DatasetSvc[Dataset Service]
        RunSvc[Run Service]
        PipelineSvc[Pipeline Service]
        AnnotationSvc[Annotation Service]
        PathwaySvc[Pathway Service]
        ExportSvc[Export Service]
        AuditSvc[Audit Service]
        QuotaSvc[Quota Service]
        KPSvc[KnowledgePack Service]
    end

    subgraph "Data Stores"
        PG[(PostgreSQL)]
        Redis[(Redis)]
        S3[(S3 / MinIO)]
    end

    subgraph "Orchestration"
        Temporal[Temporal Server]
    end

    Router --> Auth
    Router --> RateLimit
    Router --> Tracing
    Router --> DatasetSvc
    Router --> RunSvc
    Router --> PipelineSvc
    Router --> AnnotationSvc
    Router --> PathwaySvc
    Router --> ExportSvc
    Router --> AuditSvc
    Router --> QuotaSvc
    Router --> KPSvc

    DatasetSvc --> PG
    DatasetSvc --> S3
    RunSvc --> PG
    RunSvc --> Temporal
    AnnotationSvc --> PG
    PathwaySvc --> Temporal
    ExportSvc --> S3
    AuditSvc --> PG
    QuotaSvc --> PG
    QuotaSvc --> Redis
    Auth --> PG
    Auth --> Redis
```

### Key Components

| Component          | Location                               | Responsibility                                                   |
| ------------------ | -------------------------------------- | ---------------------------------------------------------------- |
| API Router         | `apps/api/routes/`                     | RESTful endpoints with Pydantic v2 validation                    |
| Auth Service       | `apps/api/services/auth_service.py`    | OAuth2 + JWT authentication, RBAC                                |
| Rate Limiter       | `apps/api/middleware/rate_limiting.py` | Token bucket per user (100 req/min, admin exempt)                |
| Observability      | `apps/api/middleware/tracing.py`       | OpenTelemetry spans, request_id injection                        |
| Temporal Workflows | `workflows/`                           | Dataset ingestion, run execution, export, cross-dataset analysis |

### API Route Groups

| Prefix                | Tag             | Description                                |
| --------------------- | --------------- | ------------------------------------------ |
| `/v1/auth`            | authentication  | Login, token refresh                       |
| `/v1/datasets`        | datasets        | CRUD, versioning, file upload              |
| `/v1/runs`            | runs            | Create, list, cancel, artifacts            |
| `/v1/pipelines`       | pipelines       | Template CRUD, parameter validation        |
| `/v1/annotations`     | annotations     | Revision CRUD, approval workflow           |
| `/v1/knowledge-packs` | knowledge-packs | Reference data management                  |
| `/v1/pathway`         | pathway         | Cross-dataset analysis, LLM interpretation |
| `/v1/exports`         | exports         | h5ad, CSV, reproducibility reports         |
| `/v1/quotas`          | quotas          | Storage and compute monitoring             |
| `/v1/audit`           | audit           | Immutable event log                        |

### Temporal Workflows

```mermaid
graph TD
    subgraph "Product Workflows (Temporal)"
        DI[DatasetIngestionWorkflow<br/>Upload → Validate → Extract Metadata]
        RE[RunExecutionWorkflow<br/>Resolve Template → Invoke Nextflow → Collect Artifacts]
        EX[ExportWorkflow<br/>Generate h5ad → Compile Report → Upload to S3]
        CDP[CrossDatasetPathwayWorkflow<br/>Aggregate Patterns → LLM Interpretation → Insights]
    end

    DI -->|creates| DV[DatasetVersion]
    RE -->|invokes| NF[Nextflow Pipeline]
    RE -->|produces| Art[Artifacts in S3]
    EX -->|generates| Report[Reproducibility Report]
    CDP -->|calls| LLM[GPT / Claude API]
```

---

## Compute Plane

The Compute Plane executes scientific pipelines using Nextflow DSL2 with containerized method definitions. Each method is an isolated Python module with explicit Pydantic input/output schemas.

### Compute Plane Architecture

```mermaid
graph TD
    subgraph "Compute Plane"
        NF[Nextflow Orchestrator<br/>DSL2 Pipeline]

        subgraph "Preprocessing"
            QC[QC Filter]
            DD[Doublet Detection]
            Norm[Normalization]
            HVG[HVG Selection]
        end

        subgraph "Dimensionality Reduction"
            PCA[PCA]
            BC[Batch Correction<br/>Harmony / scVI]
            Cluster[Clustering<br/>Leiden / Louvain]
            Embed[Embedding<br/>UMAP / t-SNE]
        end

        subgraph "Annotation & Analysis"
            CT[CellTypist Annotation]
            DE[Differential Expression]
            PS[Pathway Scoring<br/>decoupler]
            LR[Ligand-Receptor<br/>LIANA]
        end
    end

    subgraph "GPU Abstraction (services/gpu_abstraction)"
        Detect[Hardware Detection]
        Select[Backend Selection]
        CUDA[CUDA Backend]
        ROCm[ROCm Backend]
        Metal[Metal Backend]
        OpenCL[OpenCL Backend]
        TPU[TPU Backend]
        CPU[CPU Fallback]
    end

    NF --> QC --> DD --> Norm --> HVG --> PCA
    PCA --> BC --> Cluster
    PCA --> Embed
    Cluster --> CT --> DE --> PS --> LR

    PCA -.-> Select
    Norm -.-> Select
    BC -.-> Select
    Select --> Detect
    Detect --> CUDA
    Detect --> ROCm
    Detect --> Metal
    Detect --> OpenCL
    Detect --> TPU
    Detect --> CPU
```

### Pipeline Execution Flow

The Nextflow pipeline (`services/compute/nextflow/main.nf`) executes methods in dependency order:

1. **QC Filter** → Remove low-quality cells (gene count, mito %)
2. **Doublet Detection** → Identify and flag doublets (scrublet)
3. **Normalization** → Library-size normalization + log1p + scaling
4. **HVG Selection** → Select highly variable genes (seurat_v3)
5. **PCA** → Dimensionality reduction to N components
6. **Batch Correction** _(optional)_ → Harmony or scVI
7. **Clustering** → Leiden or Louvain community detection
8. **Embedding** → UMAP or t-SNE 2D/3D projection
9. **Cell Type Annotation** → CellTypist with majority voting
10. **Differential Expression** → Wilcoxon/t-test between clusters
11. **Pathway Scoring** _(optional)_ → decoupler activity inference
12. **Ligand-Receptor** _(optional)_ → LIANA cell-cell communication

Each step emits a progress event to the Control Plane for real-time UI updates.

### Method Definition Contract

All methods extend `MethodDefinition` (`methods/base.py`):

```python
class MethodDefinition(ABC):
    name: str
    version: str
    compute_preference: ComputePreference  # CPU_ONLY, GPU_PREFERRED, GPU_REQUIRED

    def input_schema(self) -> Type[BaseModel]: ...
    def output_schema(self) -> Type[BaseModel]: ...
    def execute(self, input: BaseModel, compute: ComputeContext) -> BaseModel: ...
```

Methods declare a `compute_preference` that the GPU abstraction layer uses to select the optimal backend at runtime. GPU-preferred methods include CPU fallback paths.

---

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Web as Web App
    participant API as Control Plane API
    participant Temporal
    participant NF as Nextflow
    participant S3 as S3 / MinIO
    participant PG as PostgreSQL

    User->>Web: Upload dataset
    Web->>API: POST /v1/datasets (files)
    API->>S3: Store files
    API->>PG: Create Dataset + DatasetVersion
    API->>Temporal: Start DatasetIngestionWorkflow

    User->>Web: Create run
    Web->>API: POST /v1/runs
    API->>PG: Create Run (status: queued)
    API->>Temporal: Start RunExecutionWorkflow
    Temporal->>NF: Execute pipeline
    NF->>S3: Store artifacts (h5ad, CSV)
    NF->>API: Emit progress events
    Temporal->>PG: Update Run (status: completed)

    User->>Web: View results
    Web->>API: GET /v1/runs/{id}/artifacts
    API->>S3: Generate pre-signed URLs
    API-->>Web: Artifact download links
```

---

## Deployment Architecture

Zerna deploys to AWS using ECS Fargate with managed data services.

```mermaid
graph TB
    subgraph "AWS Cloud"
        subgraph "ECS Fargate Cluster"
            APISvc[API Service<br/>FastAPI]
            WebSvc[Web Service<br/>Next.js]
            TemporalSvc[Temporal Service]
            WorkerSvc[Worker Service<br/>Temporal Activities]
        end

        subgraph "Managed Data Services"
            RDS[(RDS PostgreSQL<br/>Multi-AZ)]
            ElastiCache[(ElastiCache Redis<br/>Cluster Mode)]
            S3Buckets[(S3 Buckets<br/>Datasets + Artifacts)]
        end

        subgraph "Observability"
            Jaeger[Jaeger<br/>Distributed Tracing]
            Prom[Prometheus<br/>Metrics Collection]
            Graf[Grafana<br/>Dashboards]
        end

        ALB[Application Load Balancer]
        ECR[ECR<br/>Container Registry]
    end

    Internet[Internet] --> ALB
    ALB --> APISvc
    ALB --> WebSvc

    APISvc --> RDS
    APISvc --> ElastiCache
    APISvc --> S3Buckets
    APISvc --> TemporalSvc
    WorkerSvc --> S3Buckets

    APISvc --> Jaeger
    APISvc --> Prom
    Prom --> Graf
```

### Deployment Details

| Service  | Container        | Port | Scaling                        |
| -------- | ---------------- | ---- | ------------------------------ |
| API      | `zerna-api`      | 8000 | Horizontal (ECS desired count) |
| Web      | `zerna-web`      | 3000 | Horizontal (ECS desired count) |
| Temporal | `zerna-temporal` | 7233 | Single instance                |
| Worker   | `zerna-worker`   | —    | Horizontal (task queue based)  |

### CI/CD Pipeline

- **CI**: GitHub Actions runs lint, type-check, and tests on every PR
- **CD**: Pushes to `staging` branch deploy to staging; pushes to `main` deploy to production
- **Authentication**: OIDC-based AWS credentials (no long-lived keys)
- **Rollback**: `./scripts/rollback.sh <environment>` reverts all ECS services to previous task definition revision

### Local Development Stack

For local development, Docker Compose provides all infrastructure services:

| Service    | Image                           | Port                                                                 |
| ---------- | ------------------------------- | -------------------------------------------------------------------- |
| PostgreSQL | `postgres:16-alpine`            | 5432                                                                 |
| Redis      | `redis:7-alpine`                | 6379                                                                 |
| Temporal   | `temporalio/auto-setup:1.22.4`  | 7233, 8080                                                           |
| Jaeger     | `jaegertracing/all-in-one:1.52` | 16686, 4317                                                          |
| MinIO      | `minio/minio:latest`            | 9000/9001 in container; host defaults `19000`/`19001` (`MINIO_PORT`) |
| Prometheus | `prom/prometheus:v2.48.0`       | 9090                                                                 |
| Grafana    | `grafana/grafana:10.2.0`        | 3001                                                                 |
