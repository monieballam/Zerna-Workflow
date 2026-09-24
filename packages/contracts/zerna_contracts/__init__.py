"""Zerna Shared Contracts - Pydantic v2 schemas and shared types."""

__version__ = "0.1.0"

# Base models
from .base import (
    ZernaBaseModel,
    ErrorDetail,
    ErrorResponse,
    HealthCheckResponse,
    IdentifiedModel,
    OrganizationScopedModel,
    PaginatedResponse,
    PaginationParams,
    TimestampedModel,
)

# Enums
from .enums import (
    ArtifactType,
    ComputeBackend,
    ComputePreference,
    ErrorType,
    KnowledgePackType,
    RunStatus,
    SortOrder,
    UserRole,
)

# Permissions
from .permissions import (
    ROLE_PERMISSIONS,
    Action,
    Permission,
    ResourceType,
)

# Run checkpoint
from .run_checkpoint import RunCheckpoint

# Run manifest
from .run_manifest import RunManifest

# Versioning
from .versioning import (
    CURRENT_VERSION,
    DEFAULT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    ContractVersion,
    deprecated_field,
    get_current_version,
    get_version,
    is_version_supported,
)

__all__ = [
    # Base models
    "ZernaBaseModel",
    "ErrorDetail",
    "ErrorResponse",
    "HealthCheckResponse",
    "IdentifiedModel",
    "OrganizationScopedModel",
    "PaginatedResponse",
    "PaginationParams",
    "TimestampedModel",
    # Enums
    "ArtifactType",
    "ComputeBackend",
    "ComputePreference",
    "ErrorType",
    "KnowledgePackType",
    "RunStatus",
    "SortOrder",
    "UserRole",
    # Run manifest
    "RunManifest",
    # Run checkpoint
    "RunCheckpoint",
    # Permissions
    "Action",
    "Permission",
    "ResourceType",
    "ROLE_PERMISSIONS",
    # Versioning
    "CURRENT_VERSION",
    "DEFAULT_API_VERSION",
    "SUPPORTED_API_VERSIONS",
    "ContractVersion",
    "deprecated_field",
    "get_current_version",
    "get_version",
    "is_version_supported",
]
