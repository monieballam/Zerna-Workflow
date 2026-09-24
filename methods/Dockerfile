# ============================================================
# Zerna Scientific Methods — Base Image
# Contains all shared scientific Python dependencies.
# Per-method images extend this base with method-specific code.
# ============================================================

# --------------- Stage 1: Build dependencies ----------------
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Install system libs required by scientific packages (HDF5, BLAS) and for
# scikit-misc (scanpy[skmisc] via scvi-tools): Meson build + git for sdist metadata.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gfortran \
        git \
        libhdf5-dev \
        libopenblas-dev \
        meson \
        ninja-build \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Copy workspace-level files
COPY pyproject.toml uv.lock ./

# Copy workspace packages this service depends on
COPY packages/contracts/ packages/contracts/
COPY services/gpu_abstraction/ services/gpu_abstraction/

# Full methods tree must exist before uv sync: setuptools reads [tool.setuptools.package-dir]
# (analysis/, annotation/, …) while resolving the editable/workspace install.
COPY methods/ methods/

# Install dependencies (no dev deps)
RUN uv sync --frozen --no-dev --package zerna-methods

# Quick sanity check: package roots exist and import after sync
RUN /build/.venv/bin/python -c "import methods.annotation, methods.analysis, methods.preprocessing"

# --------------- Stage 2: Runtime base image ----------------
FROM python:3.11-slim-bookworm AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libhdf5-103 \
        libopenblas0 \
        curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 zerna && \
    useradd --uid 1000 --gid zerna --shell /bin/bash --create-home zerna

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/packages/contracts /app/packages/contracts
COPY --from=builder /build/services/gpu_abstraction /app/services/gpu_abstraction
COPY --from=builder /build/methods /app/methods
COPY third_party/ /app/third_party

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER zerna

HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=2 \
    CMD python -c "import scanpy; print('ok')" || exit 1

# ============================================================
# Per-method images — extend the base target above
# Build with: docker build --target preprocessing .
# ============================================================

# --- Preprocessing (QC, doublet detection, normalization, HVG) ---
FROM base AS preprocessing
CMD ["python", "-m", "methods.preprocessing"]

# --- Dimensionality Reduction (PCA, batch correction, clustering, embedding) ---
FROM base AS dimensionality_reduction
CMD ["python", "-m", "methods.dimensionality_reduction"]

# --- Annotation (cell typing, DE, pathway scoring, ligand-receptor) ---
FROM base AS annotation
CMD ["python", "-m", "methods.annotation"]
