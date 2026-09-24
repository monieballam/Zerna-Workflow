# Zerna Shared Contracts

Pydantic v2 base models, enums, and shared types for the Zerna platform.

## Overview

This package provides the foundational contracts used across all Zerna services:

- **Base Models**: Common Pydantic models with shared configuration
- **Enums**: Shared enumerations for consistent type definitions
- **Versioning**: Contract versioning strategy and utilities

## Installation

This package is part of the Zerna monorepo and is installed automatically when setting up the workspace:

```bash
# From workspace root
uv sync
```

## Usage

### Base Models

All Zerna contracts should inherit from `ZernaBaseModel`:

```python
from uuid import UUID
from zerna_contracts import ZernaBaseModel, OrganizationScopedModel
from pydantic import Field

class DatasetResponse(OrganizationScopedModel):
    """Response model for dataset endpoints."""

    id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    cell_count: int = Field(ge=0)
    gene_count: int = Field(ge=0)
```

### Enums

Use shared enums for consistent type definitions:

```python
from zerna_contracts import RunStatus, ArtifactType

# In your models
class RunResponse(ZernaBaseModel):
    id: UUID
    status: RunStatus  # Automatically validated

# In your code
if run.status == RunStatus.COMPLETED:
    process_artifacts()
```

### Available Enums

- `UserRole`: ADMIN, MEMBER, VIEWER
- `RunStatus`: QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
- `ArtifactType`: H5AD, EMBEDDING_PLOT, QC_REPORT, DE_RESULTS, PATHWAY_SCORES, LIANA_RESULTS
- `KnowledgePackType`: CELL_TYPE_MARKERS, PATHWAY_DATABASE, LIGAND_RECEPTOR_PAIRS
- `ErrorType`: USER_ERROR, SYSTEM_ERROR, TRANSIENT_ERROR
- `SortOrder`: ASC, DESC
- `ComputePreference`: CPU_ONLY, GPU_PREFERRED, GPU_REQUIRED
- `ComputeBackend`: CUDA, ROCM, METAL, OPENCL, TPU, CPU

### Pagination

Use built-in pagination models:

```python
from zerna_contracts import PaginationParams, PaginatedResponse

class ListDatasetsRequest(PaginationParams):
    """Request parameters for listing datasets."""
    sort_by: str = Field(default="created_at")

class ListDatasetsResponse(PaginatedResponse):
    """Paginated response for dataset list."""
    items: list[DatasetResponse]
```

### Error Handling

Use the standard error response format:

```python
from zerna_contracts import ErrorResponse, ErrorType

def handle_error(error: Exception) -> ErrorResponse:
    return ErrorResponse(
        error_type=ErrorType.USER_ERROR,
        error_code="INVALID_INPUT",
        message=str(error),
        request_id=get_request_id(),
    )
```

### Versioning

The contracts package follows semantic versioning:

```python
from zerna_contracts import (
    CURRENT_VERSION,
    get_current_version,
    is_version_supported,
    deprecated_field,
)

# Check current version
print(f"Contracts version: {CURRENT_VERSION}")

# Check if a version is supported
if is_version_supported("0.1.0"):
    print("Version is supported")

# Mark fields as deprecated
class MyModel(ZernaBaseModel):
    # Old field - deprecated
    old_field: str | None = deprecated_field(
        default=None,
        deprecated_in="0.2.0",
        removed_in="1.0.0",
        migration_guide="Use 'new_field' instead"
    )

    # New field
    new_field: str | None = None
```

## Versioning Strategy

### Semantic Versioning

- **MAJOR**: Breaking changes (field removal, type changes, required field additions)
- **MINOR**: Backward-compatible additions (new optional fields, new endpoints)
- **PATCH**: Bug fixes and documentation updates

### API Versioning

API endpoints are versioned via URL prefix (e.g., `/v1/`, `/v2/`):

- Each major version has its own contract package
- Multiple versions can coexist during migration periods
- Deprecated versions are supported for at least 6 months

### Contract Evolution Rules

- ✅ **DO**: Add new optional fields with sensible defaults
- ✅ **DO**: Add new enums values at the end
- ✅ **DO**: Deprecate fields before removing them
- ❌ **DON'T**: Remove fields from existing contracts
- ❌ **DON'T**: Change field types in existing contracts
- ❌ **DON'T**: Make optional fields required in existing contracts

### Deprecation Process

1. Mark field/endpoint as deprecated in code and documentation
2. Add deprecation warnings to API responses
3. Announce deprecation with 6-month notice
4. Remove in next major version

## Configuration

All models inherit the following Pydantic configuration:

```python
model_config = ConfigDict(
    populate_by_name=True,      # Use attribute names as-is
    validate_assignment=True,    # Validate on assignment
    strict=False,                # Allow type coercion
    use_enum_values=True,        # Serialize enums as values
    validate_default=True,       # Validate default values
    extra="forbid",              # Forbid extra fields
)
```

## Development

### Adding New Contracts

1. Define your model in the appropriate module (or create a new one)
2. Inherit from `ZernaBaseModel` or a specialized base model
3. Add proper type hints and Field validators
4. Export from `__init__.py`
5. Update this README with usage examples

### Adding New Enums

1. Add enum to `enums.py`
2. Export from `__init__.py`
3. Document in this README

### Testing

Contracts should be tested for:

- Serialization/deserialization
- Validation rules
- Default values
- Enum values

Example test:

```python
from zerna_contracts import RunStatus
from pydantic import ValidationError
import pytest

def test_run_status_enum():
    """Test RunStatus enum values."""
    assert RunStatus.QUEUED == "queued"
    assert RunStatus.RUNNING == "running"

def test_model_validation():
    """Test model validation."""
    with pytest.raises(ValidationError):
        MyModel(required_field=None)  # Should fail
```

## Requirements

- Python >= 3.11
- Pydantic >= 2.10.0

## License

Proprietary - Zerna Platform
