# @zerna/sdk

TypeScript SDK for the Zerna Control Plane API.

Types are generated directly from the OpenAPI specification produced by the FastAPI backend, so the SDK is always in sync with the server contract.

---

## Installation

```bash
# pnpm (recommended — this is a pnpm workspace)
pnpm add @zerna/sdk openapi-fetch

# npm
npm install @zerna/sdk openapi-fetch

# yarn
yarn add @zerna/sdk openapi-fetch
```

> **Node ≥ 20** and **TypeScript ≥ 5** are required.

---

## Quick start

```ts
import { ZernaClient } from '@zerna/sdk';

const client = new ZernaClient({
  baseUrl: 'http://localhost:8000', // replace with your Zerna API base URL in production
});

// 1. Authenticate
const { access_token, user } = await client.auth.login({
  email: 'analyst@example.com',
  password: 's3cr3t',
});
console.log('Logged in as', user.email);

// 2. List datasets
const { items, total } = await client.datasets.list({ page: 1, page_size: 10 });
console.log(`${total} datasets found`);

// 3. Create a run
const run = await client.runs.create({
  dataset_version_id: items[0].versions[0].id,
  template_id: '<pipeline-template-uuid>',
  parameters: { n_hvgs: 2000, leiden_resolution: 0.5 },
  random_seed: 42,
});
console.log('Run created:', run.id, run.status);
```

---

## Authentication

All endpoints except `POST /v1/auth/login` and `POST /v1/auth/refresh` require a Bearer JWT token.

The client stores the token in memory automatically after a successful `login()` call.

```ts
// Login
await client.auth.login({ email, password });

// Refresh (called automatically on 401 if you implement a retry interceptor)
await client.auth.refresh();

// Logout (clears in-memory tokens)
client.auth.logout();
```

To initialise the client with an existing token (e.g. from `localStorage`):

```ts
const client = new ZernaClient({
  baseUrl: 'http://localhost:8000',
  accessToken: localStorage.getItem('zerna_token') ?? undefined,
});
```

---

## API reference

### `client.datasets`

```ts
// Create a dataset (with optional file upload)
const dataset = await client.datasets.create(
  { name: 'PBMC 10k', description: '10x Genomics PBMC dataset' },
  [file] // optional File[] for multipart upload
);

// List datasets (paginated)
const { items } = await client.datasets.list({ page: 1, page_size: 20 });

// Get a single dataset
const dataset = await client.datasets.get('<dataset-uuid>');

// Update metadata
await client.datasets.update('<dataset-uuid>', { description: 'Updated' });

// Create a new version
const version = await client.datasets.createVersion('<dataset-uuid>', [file]);
```

### `client.runs`

```ts
// Create a run
const run = await client.runs.create({
  dataset_version_id: '<version-uuid>',
  template_id: '<template-uuid>',
  parameters: { leiden_resolution: 0.8 },
  random_seed: 42,
});

// Poll status
const status = await client.runs.get(run.id);
console.log(status.status); // "queued" | "running" | "completed" | "failed"

// List artifacts after completion
const { artifacts } = await client.runs.listArtifacts(run.id);
const h5ad = artifacts.find((a) => a.artifact_type === 'h5ad');
console.log(h5ad?.download_url);

// Cancel a running job
await client.runs.cancel(run.id);

// Initiate an export
const exportResult = await client.runs.export(run.id, { export_type: 'h5ad' });
```

### `client.pipelines`

```ts
// Create a pipeline template
const template = await client.pipelines.create({
  name: 'Standard PBMC Pipeline',
  version: '1.0.0',
  definition: {
    steps: ['qc', 'normalize', 'hvg', 'pca', 'leiden', 'umap'],
    parameters: { n_hvgs: 2000, leiden_resolution: 0.5 },
  },
});

// Validate parameters before creating a run
const { valid, error } = await client.pipelines.validateParameters(template.id, {
  parameters: { leiden_resolution: 0.5 },
});
```

### `client.annotations`

```ts
// Create an annotation revision
const revision = await client.annotations.create(run.id, {
  annotations: { 'cell-001': { cell_type: 'T cell', confidence: 0.95 } },
  method: 'celltypist',
  knowledge_pack_id: '<kp-uuid>',
});

// Edit annotations (creates a new revision automatically)
await client.annotations.edit(revision.id, {
  edits: { 'cell-001': { cell_type: 'CD8+ T cell' } },
});

// Approve a revision
await client.annotations.approve(revision.id);
```

### `client.knowledgePacks`

```ts
// List available knowledge packs
const { items } = await client.knowledgePacks.list({
  pack_type: 'pathway_database',
});

// Create a new knowledge pack
const kp = await client.knowledgePacks.create({
  name: 'MSigDB Hallmarks',
  version: '2024.1',
  pack_type: 'pathway_database',
  s3_path: 's3://zerna-data/knowledge-packs/msigdb-hallmarks-2024.1.json',
});
```

### `client.pathway`

```ts
// Start cross-dataset pathway analysis
const analysis = await client.pathway.analyzeCrossDataset({
  dataset_ids: ['<uuid-1>', '<uuid-2>', '<uuid-3>'],
  pathway_database: 'MSigDB',
  aggregation_method: 'meta-analysis',
});

// Poll until completed
let result = await client.pathway.getAnalysis(analysis.analysis_id);
while (result.status !== 'completed') {
  await new Promise((r) => setTimeout(r, 5000));
  result = await client.pathway.getAnalysis(analysis.analysis_id);
}

// Request LLM interpretation
const interpretation = await client.pathway.interpret(analysis.analysis_id, {
  model: 'gpt-4',
  context: 'PBMC samples from cancer patients',
});
console.log(interpretation.interpretation);
console.log('Hypotheses:', interpretation.hypotheses);
```

### `client.exports`

```ts
// Check which exports are available
const { available_exports } = await client.exports.getStatus(run.id);

// Get a pre-signed download URL
const { download_url } = await client.exports.getDownloadUrl(run.id, 'h5ad');
```

### `client.audit`

```ts
// List audit events for your organization
const { items } = await client.audit.list({
  resource_type: 'dataset',
  page: 1,
  page_size: 50,
});
```

---

## Generating types from the OpenAPI spec

The SDK ships with hand-authored types that mirror the server schemas. For the
most up-to-date generated types, run the generation pipeline:

```bash
# 1. Export the OpenAPI spec from the running FastAPI server
#    (from the repo root)
uv run python -m apps.api.export_openapi --output openapi.json

# 2. Generate TypeScript types
pnpm --filter @zerna/sdk generate

# 3. Build the SDK
pnpm --filter @zerna/sdk build
```

The generated schema is written to `packages/sdk/src/generated/schema.ts` and
re-exported from `@zerna/sdk/generated`.

---

## Error handling

All API errors throw an `ApiResponseError`:

```ts
import { ZernaClient, ApiResponseError } from '@zerna/sdk';

try {
  await client.datasets.get('non-existent-id');
} catch (err) {
  if (err instanceof ApiResponseError) {
    console.error(err.status, err.body);
    // e.g. 404, { detail: "Dataset not found" }
  }
}
```

Common status codes:

| Status | Meaning                                                               |
| ------ | --------------------------------------------------------------------- |
| `401`  | Missing or expired JWT — call `client.auth.refresh()`                 |
| `403`  | Insufficient permissions                                              |
| `404`  | Resource not found or outside your organization                       |
| `422`  | Request validation failure — check `err.body.detail` for field errors |
| `429`  | Rate limit exceeded — respect the `Retry-After` header                |

---

## Using with Next.js

```ts
// lib/zerna.ts
import { ZernaClient } from '@zerna/sdk';

export const zerna = new ZernaClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
});
```

```tsx
// app/datasets/page.tsx (React Server Component)
import { zerna } from '@/lib/zerna';

export default async function DatasetsPage() {
  const { items } = await zerna.datasets.list({ page_size: 20 });
  return (
    <ul>
      {items.map((d) => (
        <li key={d.id}>{d.name}</li>
      ))}
    </ul>
  );
}
```

---

## Development

```bash
# Install dependencies
pnpm install

# Generate types (requires openapi.json at repo root)
pnpm --filter @zerna/sdk generate

# Build
pnpm --filter @zerna/sdk build

# Lint
pnpm --filter @zerna/sdk lint
```

---

## License

Apache 2.0 — see [LICENSE](../../LICENSE).
