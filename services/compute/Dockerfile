# ============================================================
# Zerna Nextflow Orchestrator
# Based on official Nextflow image with Python client
# ============================================================

# --------------- Stage 1: Build Python client ---------------
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gfortran \
        git \
        libopenblas-dev \
        ninja-build \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Copy workspace-level files
COPY pyproject.toml uv.lock ./

# Copy the packages this service depends on
COPY methods/ methods/
COPY packages/contracts/ packages/contracts/
COPY services/compute/ services/compute/

# Install dependencies (no dev deps) as non-editable packages so the runtime
# image does not depend on /build-era workspace paths.
RUN uv sync --frozen --no-dev --no-editable --package zerna-compute

# --------------- Stage 2: Runtime with Nextflow -------------
FROM python:3.11-slim-bookworm AS runtime

ARG NXF_VER=24.04.4

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        openjdk-17-jre-headless && \
    rm -rf /var/lib/apt/lists/* && \
    NXF_VER="${NXF_VER}" bash -c "curl -fsSL https://get.nextflow.io | bash" && \
    mv nextflow /usr/local/bin/nextflow && \
    chmod +x /usr/local/bin/nextflow

RUN groupadd --gid 1000 zerna && \
    useradd --uid 1000 --gid zerna --shell /bin/bash --create-home zerna

WORKDIR /app

# Copy Python venv and source from builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/methods /app/methods
COPY --from=builder /build/packages/contracts /app/packages/contracts
COPY --from=builder /build/services/compute /app/services/compute

# Copy Nextflow pipeline files
COPY services/compute/nextflow/ /app/pipelines/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app:/app/packages/contracts" \
    NXF_HOME="/app/.nextflow"

USER zerna

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD nextflow -version > /dev/null 2>&1 || exit 1

CMD ["nextflow", "run", "/app/pipelines/main.nf", "-resume"]
