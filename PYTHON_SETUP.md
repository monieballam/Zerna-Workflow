# Python Environment Setup

This project uses [uv](https://github.com/astral-sh/uv) for fast, deterministic Python dependency management.

## Prerequisites

- Python 3.11 or higher
- uv (install via `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Workspace Structure

The project is organized as a uv workspace with the following Python packages:

- **apps/api** - Control Plane API (FastAPI)
- **packages/contracts** - Shared Pydantic v2 schemas
- **services/compute** - Compute Plane orchestrator (Nextflow integration)
- **services/gpu_abstraction** - Heterogeneous GPU abstraction layer
- **methods** - Scientific method definitions (scanpy, scvi-tools, CellTypist, etc.)
- **workflows** - Temporal workflow definitions

## Installation

Install all dependencies for all workspace packages:

```bash
uv sync
```

Install with optional GPU support:

```bash
# NVIDIA CUDA
uv sync --extra cuda

# AMD ROCm
uv sync --extra rocm

# Apple Metal
uv sync --extra metal

# All GPU backends
uv sync --extra all
```

## Development Tools

The workspace includes shared development tools configured in the root `pyproject.toml`:

### Ruff (Linting and Formatting)

```bash
# Check code
uv run ruff check .

# Format code
uv run ruff format .

# Fix auto-fixable issues
uv run ruff check --fix .
```

### Pytest (Testing)

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Run specific test types
uv run pytest -m unit
uv run pytest -m property
uv run pytest -m integration
```

### Mypy (Type Checking)

```bash
# Type check all packages
uv run mypy apps services methods workflows packages
```

## Adding Dependencies

Add dependencies to the appropriate package's `pyproject.toml`:

```bash
# Add to a specific package
cd apps/api
uv add fastapi

# Add dev dependency to root
uv add --dev pytest-mock
```

## Package Dependencies

Internal workspace dependencies are declared using workspace references:

```toml
[tool.uv.sources]
zerna-contracts = { workspace = true }
```

## Lock File

The `uv.lock` file ensures deterministic dependency resolution across all environments. Commit this file to version control.

## Virtual Environment

uv automatically creates and manages a virtual environment at `.venv/`. Activate it manually if needed:

```bash
source .venv/bin/activate  # Unix/macOS
.venv\Scripts\activate     # Windows
```

## CI/CD Integration

In CI pipelines, use:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --frozen

# Run tests
uv run pytest
```

## Configuration

### Ruff

Configured in `[tool.ruff]` section of root `pyproject.toml`:

- Target: Python 3.11
- Line length: 100
- Enabled rules: pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade, etc.

### Pytest

Configured in `[tool.pytest.ini_options]`:

- Test discovery: `test_*.py`, `*_test.py`
- Coverage reporting: terminal + HTML
- Async support: enabled
- Markers: property, unit, integration, slow

### Mypy

Configured in `[tool.mypy]`:

- Strict mode enabled
- Disallow untyped definitions
- Warn on unused ignores and redundant casts

## Troubleshooting

### Dependency conflicts

```bash
# Clear cache and reinstall
uv cache clean
uv sync --reinstall
```

### GPU backend issues

GPU backends require specific system libraries:

- **CUDA**: NVIDIA drivers + CUDA toolkit
- **ROCm**: AMD drivers + ROCm toolkit
- **Metal**: macOS with Apple Silicon
- **OpenCL**: Intel/AMD drivers with OpenCL support

Install CPU-only versions if GPU is unavailable:

```bash
uv sync  # Installs CPU-only by default
```
