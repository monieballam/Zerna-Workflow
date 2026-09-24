"""Property-based tests for dataset version uniqueness.

**Validates: Requirements 2.4**
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from apps.api.models.dataset import DatasetVersion
from apps.api.models.organization import Organization
from apps.api.services.dataset_service import DatasetService
from apps.api.services.file_validation_service import (
    FileMetadata,
    FileValidationService,
    ValidationResult,
)
from apps.api.services.s3_service import S3Service


# Custom strategies for generating test data
@st.composite
def dataset_creation_params(draw):
    """Generate parameters for dataset creation."""
    name = draw(
        st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_characters="\x00"))
    )
    description = draw(st.text(max_size=100, alphabet=st.characters(blacklist_characters="\x00")))
    num_files = draw(st.integers(min_value=1, max_value=3))
    return {
        "name": name,
        "description": description,
        "num_files": num_files,
    }


@st.composite
def version_creation_count(draw):
    """Generate number of versions to create."""
    return draw(st.integers(min_value=1, max_value=5))


@pytest.fixture
def mock_s3_service():
    """Create a mock S3Service."""
    service = MagicMock(spec=S3Service)
    service.datasets_bucket = "test-datasets-bucket"
    service.generate_dataset_path = MagicMock(
        side_effect=lambda org_id, dataset_id, filename: (
            f"{org_id}/datasets/{dataset_id}/{filename}"
        )
    )
    service.upload_file = MagicMock(
        return_value={"etag": "test-etag", "size": 1024, "checksum": "test-checksum"}
    )
    service.delete_file = MagicMock()
    return service


@pytest.fixture
def mock_file_validation_service():
    """Create a mock FileValidationService."""
    service = MagicMock(spec=FileValidationService)

    async def mock_validate(file_path, file_format):
        return ValidationResult(
            is_valid=True,
            metadata=FileMetadata(
                cell_count=1000,
                gene_count=2000,
                format=file_format,
                additional_metadata={},
            ),
        )

    service.validate_file = AsyncMock(side_effect=mock_validate)
    return service


@pytest_asyncio.fixture
async def organization(async_session):
    """Create a test organization."""
    org = Organization(
        id=uuid4(),
        name="Test Organization",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    async_session.add(org)
    await async_session.commit()
    await async_session.refresh(org)
    return org


@pytest.fixture
def dataset_service(async_session, mock_s3_service, mock_file_validation_service):
    """Create a DatasetService with mocked dependencies."""
    return DatasetService(
        db=async_session,
        s3_service=mock_s3_service,
        file_validation_service=mock_file_validation_service,
    )


class TestDatasetVersionUniquenessProperty:
    """Property-based tests for dataset version uniqueness.

    Property 6: Dataset Version Uniqueness
    For any set of dataset creations, all generated DatasetVersion identifiers
    should be unique across the entire system.
    """

    @pytest.mark.asyncio
    @given(
        num_datasets=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_ids_unique_across_datasets(
        self, num_datasets, dataset_service, organization, async_session
    ):
        """Property: All DatasetVersion IDs should be unique across multiple datasets.

        **Validates: Requirements 2.4**
        """
        # Create multiple datasets
        created_datasets = []
        for i in range(num_datasets):
            files = [("/tmp/test.h5ad", "h5ad")]
            dataset = await dataset_service.create_dataset(
                org_id=organization.id,
                name=f"Dataset {i}",
                description=f"Test dataset {i}",
                metadata={},
                files=files,
            )
            created_datasets.append(dataset)

        # Collect all version IDs
        version_ids = []
        for dataset in created_datasets:
            # Refresh to get latest versions
            await async_session.refresh(dataset)
            stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
            result = await async_session.execute(stmt)
            versions = result.scalars().all()
            version_ids.extend([v.id for v in versions])

        # Property assertion: All version IDs must be unique
        assert len(version_ids) == len(set(version_ids)), (
            f"DatasetVersion IDs are not unique! Found {len(version_ids)} versions "
            f"but only {len(set(version_ids))} unique IDs"
        )

    @pytest.mark.asyncio
    @given(
        num_versions=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_ids_unique_within_dataset(
        self, num_versions, dataset_service, organization, async_session
    ):
        """Property: All DatasetVersion IDs should be unique within a single dataset.

        **Validates: Requirements 2.4**
        """
        # Create a dataset with initial version
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test dataset with multiple versions",
            metadata={},
            files=files,
        )

        # Create additional versions
        for i in range(num_versions - 1):  # -1 because we already have v1
            await dataset_service.create_version(
                dataset_id=dataset.id,
                org_id=organization.id,
                files=files,
            )

        # Get all versions for this dataset
        stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
        result = await async_session.execute(stmt)
        versions = result.scalars().all()

        # Collect version IDs
        version_ids = [v.id for v in versions]

        # Property assertion: All version IDs must be unique
        assert len(version_ids) == num_versions, (
            f"Expected {num_versions} versions, but found {len(version_ids)}"
        )
        assert len(version_ids) == len(set(version_ids)), (
            f"DatasetVersion IDs are not unique within dataset! Found {len(version_ids)} versions "
            f"but only {len(set(version_ids))} unique IDs"
        )

    @pytest.mark.asyncio
    @given(
        num_versions=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_numbers_sequential(
        self, num_versions, dataset_service, organization, async_session
    ):
        """Property: Version numbers should be sequential (v1, v2, v3, ...) within a dataset.

        **Validates: Requirements 2.4**
        """
        # Create a dataset with initial version
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test dataset",
            metadata={},
            files=files,
        )

        # Create additional versions
        for i in range(num_versions - 1):  # -1 because we already have v1
            await dataset_service.create_version(
                dataset_id=dataset.id,
                org_id=organization.id,
                files=files,
            )

        # Get all versions for this dataset
        stmt = (
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.created_at)
        )
        result = await async_session.execute(stmt)
        versions = result.scalars().all()

        # Property assertion: Version numbers should be sequential
        expected_versions = [f"v{i + 1}" for i in range(num_versions)]
        actual_versions = [v.version for v in versions]

        assert actual_versions == expected_versions, (
            f"Version numbers are not sequential! Expected {expected_versions}, "
            f"but got {actual_versions}"
        )

    @pytest.mark.asyncio
    @given(
        num_versions=st.integers(min_value=2, max_value=8),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_numbers_unique_within_dataset(
        self, num_versions, dataset_service, organization, async_session
    ):
        """Property: Version numbers should be unique within a dataset (no duplicates).

        **Validates: Requirements 2.4**
        """
        # Create a dataset with initial version
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test dataset",
            metadata={},
            files=files,
        )

        # Create additional versions
        for i in range(num_versions - 1):
            await dataset_service.create_version(
                dataset_id=dataset.id,
                org_id=organization.id,
                files=files,
            )

        # Get all versions for this dataset
        stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
        result = await async_session.execute(stmt)
        versions = result.scalars().all()

        # Collect version numbers
        version_numbers = [v.version for v in versions]

        # Property assertion: All version numbers must be unique
        assert len(version_numbers) == len(set(version_numbers)), (
            f"Version numbers are not unique within dataset! Found {len(version_numbers)} versions "
            f"but only {len(set(version_numbers))} unique version numbers: {version_numbers}"
        )

    @pytest.mark.asyncio
    @given(
        num_datasets=st.integers(min_value=2, max_value=8),
        versions_per_dataset=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_all_version_ids_globally_unique(
        self, num_datasets, versions_per_dataset, dataset_service, organization, async_session
    ):
        """Property: All DatasetVersion IDs should be globally unique across all datasets and versions.

        **Validates: Requirements 2.4**
        """
        all_version_ids = []

        # Create multiple datasets, each with multiple versions
        for i in range(num_datasets):
            files = [("/tmp/test.h5ad", "h5ad")]

            # Create dataset with initial version
            dataset = await dataset_service.create_dataset(
                org_id=organization.id,
                name=f"Dataset {i}",
                description=f"Test dataset {i}",
                metadata={},
                files=files,
            )

            # Create additional versions
            for j in range(versions_per_dataset - 1):
                await dataset_service.create_version(
                    dataset_id=dataset.id,
                    org_id=organization.id,
                    files=files,
                )

            # Collect version IDs for this dataset
            stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
            result = await async_session.execute(stmt)
            versions = result.scalars().all()
            all_version_ids.extend([v.id for v in versions])

        # Property assertion: All version IDs must be globally unique
        total_versions = num_datasets * versions_per_dataset
        assert len(all_version_ids) == total_versions, (
            f"Expected {total_versions} versions, but found {len(all_version_ids)}"
        )
        assert len(all_version_ids) == len(set(all_version_ids)), (
            f"DatasetVersion IDs are not globally unique! Found {len(all_version_ids)} versions "
            f"but only {len(set(all_version_ids))} unique IDs"
        )

    @pytest.mark.asyncio
    @given(
        num_versions=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_creation_increments_correctly(
        self, num_versions, dataset_service, organization, async_session
    ):
        """Property: Creating N versions should result in version numbers from v1 to vN.

        **Validates: Requirements 2.4**
        """
        # Create a dataset with initial version
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test dataset",
            metadata={},
            files=files,
        )

        # Get the initial version from database
        stmt = (
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.created_at)
        )
        result = await async_session.execute(stmt)
        initial_versions = result.scalars().all()
        created_versions = list(initial_versions)  # v1 from initial creation

        # Create additional versions
        for i in range(num_versions - 1):
            version = await dataset_service.create_version(
                dataset_id=dataset.id,
                org_id=organization.id,
                files=files,
            )
            created_versions.append(version)

        # Property assertion: Each version should have the correct version number
        for i, version in enumerate(created_versions):
            expected_version = f"v{i + 1}"
            assert version.version == expected_version, (
                f"Version {i} has incorrect version number! Expected {expected_version}, "
                f"but got {version.version}"
            )

    @pytest.mark.asyncio
    @given(
        num_orgs=st.integers(min_value=2, max_value=5),
        datasets_per_org=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_property_version_ids_unique_across_organizations(
        self, num_orgs, datasets_per_org, dataset_service, async_session
    ):
        """Property: DatasetVersion IDs should be unique across different organizations.

        **Validates: Requirements 2.4**
        """
        all_version_ids = []

        # Create multiple organizations
        for org_idx in range(num_orgs):
            org = Organization(
                id=uuid4(),
                name=f"Test Organization {org_idx}",
                storage_quota_gb=1000,
                compute_quota_runs=10,
            )
            async_session.add(org)
            await async_session.commit()
            await async_session.refresh(org)

            # Create datasets for this organization
            for dataset_idx in range(datasets_per_org):
                files = [("/tmp/test.h5ad", "h5ad")]
                dataset = await dataset_service.create_dataset(
                    org_id=org.id,
                    name=f"Dataset {dataset_idx}",
                    description=f"Test dataset {dataset_idx}",
                    metadata={},
                    files=files,
                )

                # Collect version IDs
                stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
                result = await async_session.execute(stmt)
                versions = result.scalars().all()
                all_version_ids.extend([v.id for v in versions])

        # Property assertion: All version IDs must be unique across organizations
        total_versions = num_orgs * datasets_per_org
        assert len(all_version_ids) == total_versions, (
            f"Expected {total_versions} versions, but found {len(all_version_ids)}"
        )
        assert len(all_version_ids) == len(set(all_version_ids)), (
            f"DatasetVersion IDs are not unique across organizations! Found {len(all_version_ids)} versions "
            f"but only {len(set(all_version_ids))} unique IDs"
        )

    @pytest.mark.asyncio
    async def test_property_version_immutability(
        self, dataset_service, organization, async_session
    ):
        """Property: Once created, DatasetVersion records should be immutable (version number cannot change).

        **Validates: Requirements 2.4**
        """
        # Create a dataset with initial version
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test dataset",
            metadata={},
            files=files,
        )

        # Get the initial version
        stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
        result = await async_session.execute(stmt)
        initial_version = result.scalar_one()

        # Store original values
        original_version_id = initial_version.id
        original_version_number = initial_version.version

        # Create a second version
        await dataset_service.create_version(
            dataset_id=dataset.id,
            org_id=organization.id,
            files=files,
        )

        # Refresh and verify the first version hasn't changed
        await async_session.refresh(initial_version)

        # Property assertion: Original version should remain unchanged
        assert initial_version.id == original_version_id, (
            "DatasetVersion ID changed after creating new version!"
        )
        assert initial_version.version == original_version_number, (
            f"DatasetVersion number changed! Expected {original_version_number}, "
            f"but got {initial_version.version}"
        )
