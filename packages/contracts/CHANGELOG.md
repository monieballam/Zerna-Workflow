# Changelog

All notable changes to the Zerna Contracts package will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-01-01

### Added

#### Base Models

- `ZernaBaseModel`: Base Pydantic model with common configuration for all contracts
- `TimestampedModel`: Base model with automatic `created_at` timestamp
- `OrganizationScopedModel`: Base model for resources scoped to an organization
- `IdentifiedModel`: Base model with UUID identifier
- `PaginationParams`: Common pagination parameters for list endpoints
- `PaginatedResponse`: Base model for paginated list responses
- `ErrorDetail`: Detailed error information structure
- `ErrorResponse`: Standard error response format
- `HealthCheckResponse`: Health check response structure

#### Enums

- `UserRole`: User roles for RBAC (ADMIN, MEMBER, VIEWER)
- `RunStatus`: Pipeline run execution status (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
- `ArtifactType`: Types of artifacts produced by runs (H5AD, EMBEDDING_PLOT, QC_REPORT, DE_RESULTS, PATHWAY_SCORES, LIANA_RESULTS)
- `KnowledgePackType`: Types of knowledge packs (CELL_TYPE_MARKERS, PATHWAY_DATABASE, LIGAND_RECEPTOR_PAIRS)
- `ErrorType`: Error classification for retry behavior (USER_ERROR, SYSTEM_ERROR, TRANSIENT_ERROR)
- `SortOrder`: Sort order for queries (ASC, DESC)
- `ComputePreference`: Compute resource preference (CPU_ONLY, GPU_PREFERRED, GPU_REQUIRED)
- `ComputeBackend`: Available compute backends (CUDA, ROCM, METAL, OPENCL, TPU, CPU)

#### Versioning

- Contract versioning strategy with semantic versioning
- `ContractVersion`: Version metadata class
- `deprecated_field()`: Helper for marking fields as deprecated
- Version utility functions: `get_current_version()`, `get_version()`, `is_version_supported()`
- Version constants: `CURRENT_VERSION`, `SUPPORTED_API_VERSIONS`, `DEFAULT_API_VERSION`

#### Documentation

- Comprehensive README with usage examples
- Contract evolution rules and deprecation process
- API versioning strategy documentation

#### Testing

- Unit tests for all base models (100% coverage)
- Unit tests for all enums (100% coverage)
- Unit tests for versioning utilities (98% coverage)
- Overall package coverage: 96%

### Configuration

- Pydantic v2 configuration with strict validation
- Automatic enum value serialization
- Extra fields forbidden by default
- Validation on assignment enabled

[0.1.0]: https://github.com/zerna/platform/releases/tag/contracts-v0.1.0
