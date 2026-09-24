"""Contract versioning strategy for Zerna platform.

This module defines the versioning strategy for API contracts to ensure
backward compatibility and smooth evolution of the platform.

Versioning Strategy:
-------------------

1. **Semantic Versioning**: Contracts follow semantic versioning (MAJOR.MINOR.PATCH)
   - MAJOR: Breaking changes (field removal, type changes, required field additions)
   - MINOR: Backward-compatible additions (new optional fields, new endpoints)
   - PATCH: Bug fixes and documentation updates

2. **API Versioning**: API endpoints are versioned via URL prefix (e.g., /v1/, /v2/)
   - Each major version has its own contract package
   - Multiple versions can coexist during migration periods
   - Deprecated versions are supported for at least 6 months

3. **Contract Evolution Rules**:
   - NEVER remove fields from existing contracts (deprecate instead)
   - NEVER change field types in existing contracts
   - NEVER make optional fields required in existing contracts
   - ALWAYS add new fields as optional with sensible defaults
   - ALWAYS document deprecations with removal timeline

4. **Deprecation Process**:
   - Mark field/endpoint as deprecated in code and documentation
   - Add deprecation warnings to API responses
   - Announce deprecation with 6-month notice
   - Remove in next major version

5. **Migration Support**:
   - Provide migration guides for major version upgrades
   - Offer automated migration tools where possible
   - Support parallel versions during transition periods

Example Usage:
-------------

```python
from pydantic import Field
from zerna_contracts.base import ZernaBaseModel
from zerna_contracts.versioning import ContractVersion, deprecated_field

class DatasetResponse(ZernaBaseModel):
    id: UUID
    name: str

    # Deprecated field - will be removed in v2.0.0
    legacy_format: str | None = deprecated_field(
        default=None,
        deprecated_in="1.5.0",
        removed_in="2.0.0",
        migration_guide="Use 'file_format' field instead"
    )

    # New field added in v1.5.0
    file_format: str | None = Field(
        default=None,
        description="File format (h5ad, 10x, csv, tsv)"
    )
```

Version History:
---------------

- 0.1.0 (2024-01): Initial contract definitions
  - Base models and enums
  - Core entity schemas
  - Authentication contracts
"""

from datetime import datetime
from typing import Any

from pydantic import Field

# Current contract version
CURRENT_VERSION = "0.1.0"

# Supported API versions
SUPPORTED_API_VERSIONS = ["v1"]

# Default API version
DEFAULT_API_VERSION = "v1"


class ContractVersion:
    """Contract version metadata."""

    def __init__(
        self,
        version: str,
        released: str,
        deprecated: str | None = None,
        removed: str | None = None,
    ):
        """Initialize contract version.

        Args:
            version: Semantic version string (e.g., "1.0.0")
            released: Release date (ISO format)
            deprecated: Deprecation date (ISO format), if applicable
            removed: Removal date (ISO format), if applicable
        """
        self.version = version
        self.released = released
        self.deprecated = deprecated
        self.removed = removed

    @property
    def is_deprecated(self) -> bool:
        """Check if this version is deprecated."""
        if not self.deprecated:
            return False
        return datetime.fromisoformat(self.deprecated) <= datetime.utcnow()

    @property
    def is_removed(self) -> bool:
        """Check if this version is removed."""
        if not self.removed:
            return False
        return datetime.fromisoformat(self.removed) <= datetime.utcnow()


def deprecated_field(
    default: Any = None,
    deprecated_in: str | None = None,
    removed_in: str | None = None,
    migration_guide: str | None = None,
    **kwargs: Any,
) -> Any:
    """Create a deprecated field with metadata.

    Args:
        default: Default value for the field
        deprecated_in: Version when field was deprecated
        removed_in: Version when field will be removed
        migration_guide: Instructions for migrating away from this field
        **kwargs: Additional Field arguments

    Returns:
        Pydantic Field with deprecation metadata
    """
    description = kwargs.get("description", "")

    deprecation_notice = "**DEPRECATED**"
    if deprecated_in:
        deprecation_notice += f" since {deprecated_in}"
    if removed_in:
        deprecation_notice += f", will be removed in {removed_in}"
    if migration_guide:
        deprecation_notice += f". {migration_guide}"

    if description:
        description = f"{deprecation_notice}\n\n{description}"
    else:
        description = deprecation_notice

    kwargs["description"] = description
    kwargs["deprecated"] = True

    return Field(default=default, **kwargs)


# Version registry
VERSION_HISTORY = [
    ContractVersion(
        version="0.1.0",
        released="2024-01-01",
        deprecated=None,
        removed=None,
    ),
]


def get_current_version() -> ContractVersion:
    """Get the current contract version."""
    return VERSION_HISTORY[-1]


def get_version(version: str) -> ContractVersion | None:
    """Get a specific contract version.

    Args:
        version: Version string to look up

    Returns:
        ContractVersion if found, None otherwise
    """
    for v in VERSION_HISTORY:
        if v.version == version:
            return v
    return None


def is_version_supported(version: str) -> bool:
    """Check if a version is currently supported.

    Args:
        version: Version string to check

    Returns:
        True if version is supported, False otherwise
    """
    v = get_version(version)
    if not v:
        return False
    return not v.is_removed
