# Zerna Control Plane API

FastAPI application for metadata, orchestration, and API gateway.

## Features Implemented

- **JWT authentication** with signup, login, refresh, and `GET /v1/auth/me`
- **Pipeline run lifecycle** with create, resume-from-failure, progress tracking, and artifact registration
- **Pipeline template management** with versioned templates and seeded defaults
- **Results APIs** for run summaries, embeddings, explorer payloads, and artifact previews
- **Background stale-run reconciliation** for stranded `RUNNING` runs

## Project Structure

```
apps/api/
├── config.py              # Configuration management with pydantic-settings
├── dependencies.py        # FastAPI dependencies (DB, Redis, services)
├── main.py               # FastAPI application entry point
├── models/               # SQLAlchemy ORM models
│   ├── organization.py   # Organization, User models
│   ├── dataset.py        # Dataset, DatasetVersion models
│   ├── pipeline.py       # PipelineTemplate, Run models
│   ├── annotation.py     # AnnotationRevision, KnowledgePack models
│   └── audit.py          # AuditEvent model
├── routes/               # API route handlers
│   └── auth.py           # Authentication endpoints
├── schemas/              # Pydantic request/response schemas
│   └── auth.py           # Authentication schemas
├── services/             # Business logic services
│   └── auth_service.py   # Authentication service
└── tests/                # Unit and integration tests
    ├── conftest.py       # Shared test fixtures
    └── test_auth_service.py  # AuthService tests
```

## Running the API

### Prerequisites

- Python 3.11+
- PostgreSQL
- Redis
- Temporal
- S3/MinIO

### Setup

1. Install dependencies:

```bash
uv sync --all-groups
```

2. Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

3. Run database migrations:

```bash
uv run --directory apps/api alembic upgrade head
```

4. Start the API server:

```bash
./scripts/start-api.sh
```

For the full local stack, start Docker services first:

```bash
./scripts/setup-dev-env.sh
```

## API Endpoints

### Authentication

#### POST /v1/auth/login

Authenticate user with email and password.

**Request:**

```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

#### POST /v1/auth/refresh

Refresh access token using a valid refresh token.

**Request:**

```json
{
  "refresh_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

#### POST /v1/auth/signup

Self-service account creation. This also creates the default organization/workspace for the new user.

#### GET /v1/auth/me

Validate the current session and return the authenticated user profile.

### Runs

- `POST /v1/runs` — create and auto-start a run
- `POST /v1/runs/{id}/resume` — resume a failed run from durable checkpoints
- `GET /v1/runs/{id}` — run status and progress
- `GET /v1/runs/{id}/results` — results summary for completed runs
- `GET /v1/runs/{id}/explorer` — explorer payload from the saved H5AD artifact

## Testing

Run all tests:

```bash
uv run pytest apps/api/tests/ -v
```

Run authentication tests only:

```bash
uv run pytest apps/api/tests/test_auth_service.py -v
```

Run with coverage:

```bash
uv run pytest apps/api/tests/ --cov=apps/api --cov-report=html
```

## Configuration

All configuration is managed through environment variables. See `.env.example` for available options.

### Key Configuration Options

- `JWT_SECRET_KEY`: RS256 private key for JWT signing
- `JWT_ALGORITHM`: JWT signing algorithm (default: RS256)
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: Access token expiration (default: 60)
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS`: Refresh token expiration (default: 30)
- `PASSWORD_HASH_ALGORITHM`: Password hashing algorithm (default: argon2id)
- `REDIS_URL`: Redis connection string for refresh token storage
- `DATABASE_URL`: PostgreSQL connection string
- `STALE_RUN_RECONCILER_ENABLED`: Enable stale-run background repair
- `STALE_RUN_THRESHOLD_SECONDS`: How long a run can go without a progress update before reconciliation

## Security Features

### Password Hashing

- **Algorithm**: Argon2id (winner of Password Hashing Competition)
- **Memory cost**: 64 MB
- **Time cost**: 3 iterations
- **Parallelism**: 4 threads

### JWT Tokens

- **Algorithm**: RS256 (RSA with SHA-256)
- **Access token**: 1-hour expiration
- **Refresh token**: 30-day expiration, stored in Redis
- **Token rotation**: New refresh token issued on each refresh

### Refresh Token Storage

- Stored in Redis with automatic expiration (30 days)
- Constant-time comparison to prevent timing attacks
- Revocable by deleting from Redis

## Operational Notes

- The API expects PostgreSQL, Redis, Temporal, and MinIO/S3 to be reachable.
- The stale-run reconciler runs inside the API lifespan process.
- The worker is typically run as the supervised Docker Compose `worker` service, not as an unmanaged local shell process.
