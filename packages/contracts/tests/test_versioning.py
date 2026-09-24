"""Tests for contract versioning strategy."""

from zerna_contracts import (
    CURRENT_VERSION,
    DEFAULT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    ZernaBaseModel,
    ContractVersion,
    deprecated_field,
    get_current_version,
    get_version,
    is_version_supported,
)


class TestVersionConstants:
    """Test suite for version constants."""

    def test_current_version_format(self):
        """Test that CURRENT_VERSION follows semantic versioning."""
        assert isinstance(CURRENT_VERSION, str)
        parts = CURRENT_VERSION.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)

    def test_supported_api_versions(self):
        """Test that SUPPORTED_API_VERSIONS is a list."""
        assert isinstance(SUPPORTED_API_VERSIONS, list)
        assert len(SUPPORTED_API_VERSIONS) > 0
        assert all(isinstance(v, str) for v in SUPPORTED_API_VERSIONS)

    def test_default_api_version(self):
        """Test that DEFAULT_API_VERSION is in supported versions."""
        assert DEFAULT_API_VERSION in SUPPORTED_API_VERSIONS


class TestContractVersion:
    """Test suite for ContractVersion class."""

    def test_contract_version_creation(self):
        """Test creating a ContractVersion."""
        version = ContractVersion(version="1.0.0", released="2024-01-01")

        assert version.version == "1.0.0"
        assert version.released == "2024-01-01"
        assert version.deprecated is None
        assert version.removed is None

    def test_contract_version_not_deprecated(self):
        """Test that a version without deprecation date is not deprecated."""
        version = ContractVersion(version="1.0.0", released="2024-01-01")

        assert not version.is_deprecated
        assert not version.is_removed

    def test_contract_version_deprecated(self):
        """Test that a version with past deprecation date is deprecated."""
        version = ContractVersion(version="1.0.0", released="2024-01-01", deprecated="2024-06-01")

        assert version.is_deprecated
        assert not version.is_removed

    def test_contract_version_removed(self):
        """Test that a version with past removal date is removed."""
        version = ContractVersion(
            version="1.0.0", released="2024-01-01", deprecated="2024-06-01", removed="2025-01-01"
        )

        assert version.is_deprecated
        assert version.is_removed


class TestDeprecatedField:
    """Test suite for deprecated_field helper."""

    def test_deprecated_field_basic(self):
        """Test creating a deprecated field."""
        field = deprecated_field(default=None, deprecated_in="1.0.0", removed_in="2.0.0")

        assert field.default is None
        assert "DEPRECATED" in field.description
        assert "1.0.0" in field.description
        assert "2.0.0" in field.description

    def test_deprecated_field_with_migration_guide(self):
        """Test deprecated field with migration guide."""
        field = deprecated_field(
            default=None,
            deprecated_in="1.0.0",
            removed_in="2.0.0",
            migration_guide="Use 'new_field' instead",
        )

        assert "Use 'new_field' instead" in field.description

    def test_deprecated_field_in_model(self):
        """Test using deprecated field in a model."""

        class TestModel(ZernaBaseModel):
            old_field: str | None = deprecated_field(
                default=None,
                deprecated_in="1.0.0",
                removed_in="2.0.0",
                migration_guide="Use 'new_field' instead",
            )
            new_field: str | None = None

        # Model should still work with deprecated field
        model = TestModel(old_field="test", new_field="test2")
        assert model.old_field == "test"
        assert model.new_field == "test2"

        # Model should work without deprecated field
        model2 = TestModel(new_field="test")
        assert model2.old_field is None
        assert model2.new_field == "test"


class TestVersionFunctions:
    """Test suite for version utility functions."""

    def test_get_current_version(self):
        """Test getting the current version."""
        version = get_current_version()

        assert isinstance(version, ContractVersion)
        assert version.version == CURRENT_VERSION

    def test_get_version_existing(self):
        """Test getting an existing version."""
        version = get_version("0.1.0")

        assert version is not None
        assert version.version == "0.1.0"

    def test_get_version_nonexistent(self):
        """Test getting a non-existent version."""
        version = get_version("99.99.99")

        assert version is None

    def test_is_version_supported_current(self):
        """Test that current version is supported."""
        assert is_version_supported(CURRENT_VERSION)

    def test_is_version_supported_nonexistent(self):
        """Test that non-existent version is not supported."""
        assert not is_version_supported("99.99.99")
