"""Main FastAPI application for the Zerna Control Plane API."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from apps.api.config import get_settings
from apps.api.dependencies import _get_session_factory, get_redis
from apps.api.errors import CatchDependencyExceptionGroupsMiddleware, register_error_handlers
from apps.api.logging_config import configure_logging
from apps.api.middleware.rate_limiting import RateLimitMiddleware
from apps.api.middleware.tracing import ObservabilityMiddleware
from apps.api.models.organization import Organization
from apps.api.observability import instrument_fastapi, setup_metrics, setup_tracing
from apps.api.routes import (
    admin_router,
    annotations_router,
    audit_router,
    auth_router,
    datasets_router,
    embeddings_router,
    exports_router,
    feedback_router,
    knowledge_packs_router,
    nextflow_router,
    pathway_router,
    pipelines_router,
    quotas_router,
    results_router,
    runs_router,
    uploads_router,
)
from apps.api.services.auth_service import AuthService
from apps.api.services.pipeline_service import PipelineService
from apps.api.services.run_service import RunService

settings = get_settings()
logger = logging.getLogger(__name__)

# Configure structured logging before anything else
configure_logging(level=settings.log_level, fmt=settings.log_format)

# Set up distributed tracing (OTLP → Jaeger)
setup_tracing(
    service_name=settings.otel_service_name,
    otlp_endpoint=settings.otel_exporter_otlp_endpoint,
    environment=settings.environment,
)

# Set up Prometheus metrics
setup_metrics(service_name=settings.otel_service_name)

# OpenAPI tag metadata — defines display order and descriptions in the generated spec
OPENAPI_TAGS = [
    {
        "name": "authentication",
        "description": "OAuth2 + JWT authentication. Login, refresh tokens, and user profile.",
    },
    {
        "name": "datasets",
        "description": (
            "Dataset lifecycle management. Upload single-cell data files (h5ad, 10x h5, "
            "10x mtx, csv, tsv), create versioned snapshots, and query dataset metadata."
        ),
    },
    {
        "name": "runs",
        "description": (
            "Pipeline run lifecycle. Create, monitor, and cancel analysis runs. "
            "Retrieve run artifacts (h5ad, embeddings, DE results, pathway scores)."
        ),
    },
    {
        "name": "pipelines",
        "description": (
            "Pipeline template management. Define reusable analysis workflows with "
            "configurable parameters and validate parameter schemas."
        ),
    },
    {
        "name": "feedback",
        "description": (
            "End-user feedback submissions for run-specific issues, scientific concerns, "
            "UI issues, and system-wide requests."
        ),
    },
    {
        "name": "admin",
        "description": ("Admin-only organization views for feedback review and member management."),
    },
    {
        "name": "annotations",
        "description": (
            "Cell type annotation revisions. Create, edit, and approve hierarchical "
            "cell type annotations with full provenance tracking."
        ),
    },
    {
        "name": "knowledge-packs",
        "description": (
            "Versioned reference data management. Manage cell type marker databases, "
            "pathway databases, and ligand-receptor pair collections."
        ),
    },
    {
        "name": "pathway",
        "description": (
            "Cross-dataset pathway analysis and LLM interpretation. Aggregate pathway "
            "patterns across multiple datasets and generate biological hypotheses via GPT/Claude."
        ),
    },
    {
        "name": "exports",
        "description": (
            "Data export and reproducibility. Export run results as h5ad, CSV, or HTML "
            "reproducibility reports with full provenance information."
        ),
    },
    {
        "name": "quotas",
        "description": "Organization resource quota monitoring (storage and compute).",
    },
    {
        "name": "audit",
        "description": "Immutable audit event log for compliance and traceability.",
    },
    {
        "name": "health",
        "description": "Service health check endpoints.",
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup: Initialize Redis connection
    await get_redis()
    shutdown_event = asyncio.Event()
    reconciler_task: asyncio.Task | None = None
    try:
        async with _get_session_factory()() as db:
            auth_service = AuthService(
                db=db,
                redis_client=await get_redis(),
                jwt_secret_key=settings.jwt_secret_key,
                jwt_algorithm=settings.jwt_algorithm,
                access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
                refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
            )
            try:
                await auth_service.ensure_bootstrap_admin(
                    email=settings.bootstrap_admin_email,
                    organization_name=settings.bootstrap_admin_org_name,
                    password=settings.bootstrap_admin_password,
                )
            except Exception:
                logger.exception("Failed to ensure bootstrap admin during startup")
                await db.rollback()

            result = await db.execute(select(Organization.id))
            org_ids = list(result.scalars().all())
            pipeline_service = PipelineService(db)
            for org_id in org_ids:
                try:
                    await pipeline_service.sync_default_templates(org_id)
                except Exception:
                    logger.exception(
                        "Failed to sync seeded pipeline templates for organization %s",
                        org_id,
                    )
                    await db.rollback()
    except Exception:
        logger.exception("Failed to initialize seeded pipeline templates during startup")

    if settings.stale_run_reconciler_enabled:

        async def stale_run_reconciler_loop() -> None:
            while not shutdown_event.is_set():
                try:
                    redis = await get_redis()
                    lock_key = "zerna:stale-run-reconciler:lock"
                    lock_value = str(uuid4())
                    lock_ttl = max(30, settings.stale_run_reconciler_interval_seconds * 2)
                    acquired = await redis.set(lock_key, lock_value, ex=lock_ttl, nx=True)
                    if acquired:
                        try:
                            async with _get_session_factory()() as db:
                                run_service = RunService(db=db)
                                reconciled = await run_service.reconcile_stale_runs(
                                    stale_after_seconds=settings.stale_run_threshold_seconds,
                                    max_auto_restart_attempts=settings.stale_run_max_auto_restart_attempts,
                                )
                                if reconciled:
                                    logger.info(
                                        "Stale-run reconciler handled %d run(s)",
                                        len(reconciled),
                                    )
                        finally:
                            current_lock_value = await redis.get(lock_key)
                            if current_lock_value == lock_value.encode():
                                await redis.delete(lock_key)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Stale-run reconciler loop failed")

                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=max(1, settings.stale_run_reconciler_interval_seconds),
                    )
                except TimeoutError:
                    continue

        reconciler_task = asyncio.create_task(stale_run_reconciler_loop())

    yield
    # Shutdown: Close connections if needed
    shutdown_event.set()
    if reconciler_task is not None:
        reconciler_task.cancel()
        try:
            await reconciler_task
        except asyncio.CancelledError:
            pass


# Create FastAPI application
app = FastAPI(
    title="Zerna Control Plane API",
    description=(
        "Production-ready, cloud-native single-cell analysis platform API.\n\n"
        "## Overview\n\n"
        "Zerna is a multi-user platform for cancer research that separates the **control plane** "
        "(metadata, orchestration, API) from the **compute plane** (scientific method execution).\n\n"
        "## Authentication\n\n"
        "All endpoints (except `/v1/auth/login` and `/v1/auth/refresh`) require a Bearer JWT token "
        "obtained from `POST /v1/auth/login`.\n\n"
        "```\nAuthorization: Bearer <access_token>\n```\n\n"
        "## Versioning\n\n"
        "All API endpoints are versioned under the `/v1` prefix. Breaking changes will be "
        "introduced under a new version prefix (e.g., `/v2`).\n\n"
        "## Error Responses\n\n"
        "- `422 Unprocessable Entity` — request validation failure (field-level details included)\n"
        "- `401 Unauthorized` — missing or invalid JWT token\n"
        "- `403 Forbidden` — insufficient permissions\n"
        "- `404 Not Found` — resource does not exist or is outside your organization\n"
        "- `429 Too Many Requests` — rate limit exceeded (see `Retry-After` header)\n"
    ),
    version="1.0.0",
    openapi_version="3.1.0",
    openapi_tags=OPENAPI_TAGS,
    contact={
        "name": "Zerna Platform Team",
        "url": "https://github.com/monieballam-png/zerna-platform",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)

# Attach OpenTelemetry auto-instrumentation (must be before other middleware)
instrument_fastapi(app)

# Register structured error handlers (ZernaError, RequestValidationError, unhandled)
register_error_handlers(app)

# Rate limiting middleware (token bucket per user, admin exempt)
app.add_middleware(RateLimitMiddleware)

# Observability middleware: request_id, latency metrics, error counting
app.add_middleware(ObservabilityMiddleware)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outermost: map Postgres/Redis-down ExceptionGroup to 503 (cannot use add_exception_handler for BaseExceptionGroup).
app.add_middleware(CatchDependencyExceptionGroupsMiddleware)

# Register routers
app.include_router(audit_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(datasets_router)
app.include_router(exports_router)
app.include_router(feedback_router)
app.include_router(nextflow_router)
app.include_router(pipelines_router)
app.include_router(runs_router)
app.include_router(results_router)
app.include_router(embeddings_router)
app.include_router(knowledge_packs_router)
app.include_router(annotations_router)
app.include_router(pathway_router)
app.include_router(quotas_router)
app.include_router(uploads_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "zerna-api"}


@app.get("/v1/health", tags=["health"])
async def v1_health_check() -> dict[str, str]:
    """V1 health check endpoint."""
    return {"status": "healthy", "service": "zerna-api", "version": "v1"}


@app.get("/metrics", tags=["health"])
def prometheus_metrics() -> Response:
    """Prometheus scrape endpoint (OpenTelemetry PrometheusMetricReader registry)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def custom_openapi() -> dict[str, Any]:
    """Generate and cache the OpenAPI schema with security scheme definitions."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        tags=OPENAPI_TAGS,
        routes=app.routes,
        contact=app.contact,
        license_info=app.license_info,
    )

    # Add Bearer JWT security scheme
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token obtained from POST /v1/auth/login",
        }
    }

    # Apply security globally (all endpoints require auth by default)
    schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
