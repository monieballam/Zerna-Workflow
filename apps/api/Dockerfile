# ============================================================
# Zerna Control Plane API — FastAPI
# Multi-stage build with uv for dependency management
# ============================================================

# --------------- Stage 1: Build dependencies ----------------
FROM python:3.11-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy workspace-level files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy the packages this service depends on
COPY packages/contracts/ packages/contracts/

# Copy the API project files
COPY apps/api/pyproject.toml apps/api/

# Install dependencies into a virtual environment (no dev deps)
RUN uv sync --frozen --no-dev --package zerna-api

# Copy application source after deps are cached
COPY apps/api/ apps/api/
COPY workflows/ workflows/

# --------------- Stage 2: Runtime image --------------------
FROM python:3.11-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 zerna && \
    useradd --uid 1000 --gid zerna --shell /bin/bash --create-home zerna

WORKDIR /app

# Copy virtual environment and source from builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/packages/contracts /app/packages/contracts
COPY --from=builder /build/apps/api /app/apps/api
COPY --from=builder /build/workflows /app/workflows
COPY methods/ /app/methods
COPY services/ /app/services
COPY scripts/ /app/scripts
COPY third_party/ /app/third_party

# Put venv on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:/app/packages/contracts:/app/workflows" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER zerna

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
