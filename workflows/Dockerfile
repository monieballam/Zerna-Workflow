# ============================================================
# Zerna Temporal Worker
# Multi-stage build with uv for dependency management
# ============================================================

# --------------- Stage 1: Build dependencies ----------------
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gfortran \
        git \
        libopenblas-dev \
        ninja-build \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy workspace-level files needed for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy the packages this service depends on
COPY apps/api/ apps/api/
COPY methods/ methods/
COPY packages/contracts/ packages/contracts/
COPY services/gpu_abstraction/ services/gpu_abstraction/
COPY scripts/ scripts/
COPY workflows/ workflows/

# Install dependencies (no dev deps) as non-editable packages so the runtime
# image does not depend on /build-era workspace paths.
RUN uv sync --frozen --no-dev --no-editable --package zerna-workflows

# --------------- Stage 2: Runtime image --------------------
FROM python:3.11-slim AS runtime

ARG ZERNA_INSTALL_OPTIONAL_R_BACKENDS=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        curl \
        gfortran \
        git \
        libcairo2-dev \
        libcurl4-openssl-dev \
        libfontconfig1-dev \
        libfribidi-dev \
        libfreetype6-dev \
        libgomp1 \
        libharfbuzz-dev \
        libjpeg62-turbo-dev \
        libopenblas-dev \
        libopenblas0 \
        libpng-dev \
        libssl-dev \
        libtbb-dev \
        libtiff5-dev \
        libuv1-dev \
        libwebp-dev \
        libxml2-dev \
        pkg-config \
        r-base \
        r-base-dev \
        zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

RUN if [ "${ZERNA_INSTALL_OPTIONAL_R_BACKENDS}" = "1" ]; then \
      Rscript -e "options(Ncpus=max(1L, parallel::detectCores()-1L)); \
        install_if_missing <- function(pkgs, installer) { \
          missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; \
          if (length(missing) > 0) installer(missing); \
        }; \
        install_if_missing(c('BiocManager', 'remotes'), function(pkgs) install.packages(pkgs, repos='https://cloud.r-project.org')); \
        install_if_missing( \
          c('Cairo', 'textshaping', 'ragg', 'ggrastr', 'SeuratObject', 'Seurat'), \
          function(pkgs) install.packages(pkgs, repos='https://cloud.r-project.org') \
        ); \
        install_if_missing( \
          c('SingleCellExperiment', 'BiocParallel', 'scds', 'scater', 'scDblFinder'), \
          function(pkgs) BiocManager::install(pkgs, ask=FALSE, update=FALSE) \
        ); \
        if (!requireNamespace('DoubletFinder', quietly=TRUE)) remotes::install_github('chris-mcginnis-ucsf/DoubletFinder', upgrade='never'); \
        if (!requireNamespace('SoupX', quietly=TRUE)) remotes::install_github('constantAmateur/SoupX', upgrade='never')"; \
    else \
      echo "Skipping optional R backends"; \
    fi

RUN groupadd --gid 1000 zerna && \
    useradd --uid 1000 --gid zerna --shell /bin/bash --create-home zerna && \
    mkdir -p /var/lib/zerna/checkpoints /var/lib/zerna/celltypist && \
    chown -R zerna:zerna /var/lib/zerna

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/apps/api /app/apps/api
COPY --from=builder /build/methods /app/methods
COPY --from=builder /build/packages/contracts /app/packages/contracts
COPY --from=builder /build/services/gpu_abstraction /app/services/gpu_abstraction
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/workflows /app/workflows
COPY third_party/ /app/third_party

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/packages/contracts:/app/services/gpu_abstraction"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CELLTYPIST_FOLDER="/var/lib/zerna/celltypist"
# workqueue avoids Numba's TBB backend (often missing/broken in slim images despite libtbb-dev).
ENV NUMBA_THREADING_LAYER=workqueue

USER zerna

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import temporalio; print('ok')" || exit 1

CMD ["python", "-m", "workflows.worker"]
