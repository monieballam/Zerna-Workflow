# Zerna API Reference

## Interactive Documentation

The FastAPI application auto-generates interactive API documentation:

| Interface    | URL                                | Description                                |
| ------------ | ---------------------------------- | ------------------------------------------ |
| Swagger UI   | http://localhost:8000/docs         | Interactive API explorer with "Try it out" |
| ReDoc        | http://localhost:8000/redoc        | Read-only API reference                    |
| OpenAPI JSON | http://localhost:8000/openapi.json | Raw OpenAPI 3.1 specification              |

## Exporting the OpenAPI Spec

To export the OpenAPI specification as a JSON file:

```bash
# Default output: openapi.json in project root
uv run python -m apps.api.export_openapi

# Custom output path
uv run python -m apps.api.export_openapi --output packages/sdk/openapi.json
```

The exported spec can be used to generate client SDKs for any language.

---

## Authentication

All endpoints except `/v1/auth/login` and `/v1/auth/refresh` require a Bearer JWT token.

### Authentication Flow

1. **Login** — obtain access and refresh tokens:

```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'
```

Response:

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "member",
    "organizations": [{ "id": "...", "name": "My Lab" }]
  }
}
```

2. **Use the token** — include it in the `Authorization` header:

```bash
curl http://localhost:8000/v1/datasets \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIs..."
```

3. **Refresh** — obtain a new access token before expiry:

```bash
curl -X POST http://localhost:8000/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "dGhpcyBpcyBhIHJlZnJlc2g..."}'
```

---

## Rate Limiting

The API enforces rate limits using a token bucket algorithm:

| Parameter          | Value                                          |
| ------------------ | ---------------------------------------------- |
| Rate limit         | 100 requests per minute per user               |
| Algorithm          | Token bucket                                   |
| Admin exempt       | Yes — admin role users bypass rate limits      |
| Response on exceed | HTTP 429 Too Many Requests                     |
| Headers            | `Retry-After` header indicates seconds to wait |

Example 429 response:

```json
{
  "detail": "Rate limit exceeded",
  "retry_after": 12
}
```

---

## API Endpoint Groups

### Authentication (`/v1/auth`)

| Method | Path               | Description                        |
| ------ | ------------------ | ---------------------------------- |
| POST   | `/v1/auth/login`   | Authenticate and obtain JWT tokens |
| POST   | `/v1/auth/refresh` | Refresh an expired access token    |

### Datasets (`/v1/datasets`)

| Method | Path                         | Description                           |
| ------ | ---------------------------- | ------------------------------------- |
| POST   | `/v1/datasets`               | Create a dataset with file uploads    |
| GET    | `/v1/datasets`               | List datasets (paginated, org-scoped) |
| GET    | `/v1/datasets/{id}`          | Get dataset details and versions      |
| POST   | `/v1/datasets/{id}/versions` | Create a new dataset version          |

Example — create a dataset:

```bash
curl -X POST http://localhost:8000/v1/datasets \
  -H "Authorization: Bearer <token>" \
  -F "name=PBMC 10k" \
  -F "description=10k PBMCs from healthy donor" \
  -F "files=@pbmc_10k.h5ad"
```

Response:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "...",
  "name": "PBMC 10k",
  "description": "10k PBMCs from healthy donor",
  "metadata": {},
  "created_at": "2024-01-15T10:30:00Z",
  "versions": [
    {
      "id": "...",
      "version": "1",
      "cell_count": 10000,
      "gene_count": 33694,
      "file_format": "h5ad"
    }
  ]
}
```

### Runs (`/v1/runs`)

| Method | Path                      | Description                           |
| ------ | ------------------------- | ------------------------------------- |
| POST   | `/v1/runs`                | Create and start a pipeline run       |
| GET    | `/v1/runs`                | List runs (paginated, org-scoped)     |
| GET    | `/v1/runs/{id}`           | Get run status and details            |
| POST   | `/v1/runs/{id}/cancel`    | Cancel a running pipeline             |
| GET    | `/v1/runs/{id}/artifacts` | List run artifacts with download URLs |

Example — create a run:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_version_id": "550e8400-...",
    "template_id": "660e8400-...",
    "parameters": {
      "clustering_resolution": 1.0,
      "embedding_method": "umap"
    },
    "random_seed": 42
  }'
```

### Pipelines (`/v1/pipelines`)

| Method | Path                          | Description                        |
| ------ | ----------------------------- | ---------------------------------- |
| POST   | `/v1/pipelines`               | Create a pipeline template         |
| GET    | `/v1/pipelines`               | List pipeline templates            |
| GET    | `/v1/pipelines/{id}`          | Get template details               |
| POST   | `/v1/pipelines/{id}/validate` | Validate parameters against schema |

### Annotations (`/v1/annotations`)

| Method | Path                                  | Description                    |
| ------ | ------------------------------------- | ------------------------------ |
| POST   | `/v1/annotations`                     | Create an annotation revision  |
| GET    | `/v1/annotations/{run_id}`            | List revisions for a run       |
| GET    | `/v1/annotations/{run_id}/{revision}` | Get specific revision          |
| POST   | `/v1/annotations/{id}/approve`        | Approve an annotation revision |

### Knowledge Packs (`/v1/knowledge-packs`)

| Method | Path                       | Description                |
| ------ | -------------------------- | -------------------------- |
| POST   | `/v1/knowledge-packs`      | Upload a knowledge pack    |
| GET    | `/v1/knowledge-packs`      | List knowledge packs       |
| GET    | `/v1/knowledge-packs/{id}` | Get knowledge pack details |

Supported types: `cell_type_markers`, `pathway_database`, `ligand_receptor_pairs`

### Pathway Analysis (`/v1/pathway`)

| Method | Path                                  | Description                          |
| ------ | ------------------------------------- | ------------------------------------ |
| POST   | `/v1/pathway/cross-dataset`           | Start cross-dataset pathway analysis |
| GET    | `/v1/pathway/{analysis_id}`           | Get analysis results                 |
| POST   | `/v1/pathway/{analysis_id}/interpret` | Generate LLM interpretation          |

Example — cross-dataset analysis:

```bash
curl -X POST http://localhost:8000/v1/pathway/cross-dataset \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_ids": ["id-1", "id-2", "id-3"],
    "pathway_database": "MSigDB",
    "aggregation_method": "meta-analysis"
  }'
```

### Exports (`/v1/exports`)

| Method | Path                 | Description                            |
| ------ | -------------------- | -------------------------------------- |
| POST   | `/v1/exports/h5ad`   | Export run results as h5ad             |
| POST   | `/v1/exports/csv`    | Export DE results or embeddings as CSV |
| POST   | `/v1/exports/report` | Generate HTML reproducibility report   |

### Quotas (`/v1/quotas`)

| Method | Path         | Description                          |
| ------ | ------------ | ------------------------------------ |
| GET    | `/v1/quotas` | Get current organization quota usage |

Response:

```json
{
  "organization_id": "...",
  "storage": {
    "used_gb": 45.2,
    "quota_gb": 1000,
    "percentage": 4.52
  },
  "compute": {
    "active_runs": 3,
    "quota_runs": 10,
    "percentage": 30.0
  }
}
```

### Audit (`/v1/audit`)

| Method | Path        | Description                                |
| ------ | ----------- | ------------------------------------------ |
| GET    | `/v1/audit` | Query audit events (paginated, filterable) |

Audit events are immutable and cannot be modified or deleted. Each event records:

- `timestamp` — when the action occurred
- `user_id` — who performed the action
- `action_type` — what happened (e.g., `dataset.create`, `run.start`, `annotation.approve`)
- `resource_type` and `resource_id` — what was affected
- `before_state` and `after_state` — JSON snapshots for change tracking

### Health (`/health`, `/v1/health`)

| Method | Path         | Description            |
| ------ | ------------ | ---------------------- |
| GET    | `/health`    | Basic health check     |
| GET    | `/v1/health` | Versioned health check |

---

## Error Responses

All errors follow a consistent format:

| Status | Meaning                                                   |
| ------ | --------------------------------------------------------- |
| 401    | Missing or invalid JWT token                              |
| 403    | Insufficient permissions for the requested resource       |
| 404    | Resource not found or outside your organization           |
| 422    | Request validation failure (field-level details included) |
| 429    | Rate limit exceeded (check `Retry-After` header)          |
| 500    | Internal server error                                     |

Example 422 response:

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```

## Versioning

All API endpoints are versioned under the `/v1` prefix. Breaking changes will be introduced under a new version prefix (e.g., `/v2`).
