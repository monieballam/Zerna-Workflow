"""Example usage of the Zerna contracts package.

This script demonstrates how to use the shared contracts package
for defining API models, handling errors, and managing versioning.
"""

from datetime import datetime
from uuid import UUID, uuid4

from zerna_contracts import (
    CURRENT_VERSION,
    ArtifactType,
    ZernaBaseModel,
    ComputeBackend,
    ErrorResponse,
    ErrorType,
    OrganizationScopedModel,
    PaginatedResponse,
    PaginationParams,
    RunStatus,
    UserRole,
    deprecated_field,
    get_current_version,
)
from pydantic import Field


# Example 1: Define a dataset response model
class DatasetResponse(OrganizationScopedModel):
    """Response model for dataset endpoints."""

    id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    cell_count: int = Field(ge=0)
    gene_count: int = Field(ge=0)
    file_format: str


# Example 2: Define a run response model with enums
class RunResponse(ZernaBaseModel):
    """Response model for run endpoints."""

    id: UUID
    dataset_id: UUID
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None


# Example 3: Define a paginated list response
class ListDatasetsResponse(PaginatedResponse):
    """Paginated response for dataset list."""

    items: list[DatasetResponse]


# Example 4: Using deprecated fields
class LegacyModel(ZernaBaseModel):
    """Model with deprecated field."""

    # Old field - deprecated
    old_format: str | None = deprecated_field(
        default=None,
        deprecated_in="0.2.0",
        removed_in="1.0.0",
        migration_guide="Use 'new_format' field instead",
    )

    # New field
    new_format: str | None = None


def main():
    """Demonstrate contract usage."""

    print("=" * 60)
    print("Zerna Contracts Package - Usage Examples")
    print("=" * 60)
    print()

    # Show version info
    print(f"📦 Package Version: {CURRENT_VERSION}")
    version = get_current_version()
    print(f"📅 Released: {version.released}")
    print()

    # Example 1: Create a dataset response
    print("Example 1: Dataset Response")
    print("-" * 60)
    dataset = DatasetResponse(
        id=uuid4(),
        organization_id=uuid4(),
        name="Cancer Cell Atlas",
        description="Single-cell RNA-seq data from tumor samples",
        cell_count=50000,
        gene_count=20000,
        file_format="h5ad",
    )
    print(f"Dataset: {dataset.name}")
    print(f"Cells: {dataset.cell_count:,}, Genes: {dataset.gene_count:,}")
    print(f"Format: {dataset.file_format}")
    print(f"Created: {dataset.created_at}")
    print()

    # Example 2: Create a run response with status
    print("Example 2: Run Response with Status")
    print("-" * 60)
    run = RunResponse(
        id=uuid4(), dataset_id=dataset.id, status=RunStatus.RUNNING, created_at=datetime.utcnow()
    )
    print(f"Run ID: {run.id}")
    print(f"Status: {run.status}")
    print(f"Created: {run.created_at}")
    print()

    # Example 3: Create a paginated response
    print("Example 3: Paginated Response")
    print("-" * 60)
    pagination = PaginationParams(page=1, page_size=20)
    response = ListDatasetsResponse(
        items=[dataset], total=1, page=pagination.page, page_size=pagination.page_size
    )
    print(
        f"Page: {response.page}/{(response.total + response.page_size - 1) // response.page_size}"
    )
    print(f"Items: {len(response.items)}/{response.total}")
    print()

    # Example 4: Create an error response
    print("Example 4: Error Response")
    print("-" * 60)
    error = ErrorResponse(
        error_type=ErrorType.USER_ERROR,
        error_code="INVALID_FILE_FORMAT",
        message="Unsupported file format. Expected h5ad, 10x, csv, or tsv.",
        details={"provided_format": "xlsx", "supported_formats": ["h5ad", "10x", "csv", "tsv"]},
        request_id="req-123456",
    )
    print(f"Error Type: {error.error_type}")
    print(f"Error Code: {error.error_code}")
    print(f"Message: {error.message}")
    print(f"Details: {error.details}")
    print()

    # Example 5: Show available enums
    print("Example 5: Available Enums")
    print("-" * 60)
    print(f"User Roles: {', '.join(r for r in [UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER])}")
    print(
        f"Run Statuses: {', '.join(s for s in [RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.COMPLETED])}"
    )
    print(
        f"Artifact Types: {', '.join(a for a in [ArtifactType.H5AD, ArtifactType.QC_REPORT, ArtifactType.DE_RESULTS])}"
    )
    print(
        f"Compute Backends: {', '.join(b for b in [ComputeBackend.CUDA, ComputeBackend.ROCM, ComputeBackend.CPU])}"
    )
    print()

    # Example 6: JSON serialization
    print("Example 6: JSON Serialization")
    print("-" * 60)
    dataset_json = dataset.model_dump_json(indent=2)
    print("Dataset as JSON:")
    print(dataset_json[:200] + "...")
    print()

    print("=" * 60)
    print("✅ All examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
