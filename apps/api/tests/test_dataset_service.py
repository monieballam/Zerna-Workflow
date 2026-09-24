"""Unit tests for DatasetService."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio

from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import Organization
from apps.api.services.dataset_service import DatasetFilters, DatasetService
from apps.api.services.file_validation_service import (
    FileMetadata,
    FileValidationService,
    ValidationResult,
)
from apps.api.services.s3_service import S3Service


def test_dataset_file_heuristics_are_shared_and_stable():
    from zerna_contracts.dataset_files import (
        detect_10x_bundle_member,
        looks_like_metadata_filename,
        sanitize_storage_relative_path,
    )

    assert looks_like_metadata_filename("uploads/meta.txt")
    assert looks_like_metadata_filename("uploads/patient_metadata.csv")
    assert not looks_like_metadata_filename("uploads/matrix.mtx.gz")

    assert detect_10x_bundle_member("/tmp/sample_matrix.mtx.gz") == (
        "matrix",
        "sample",
        "matrix.mtx.gz",
    )
    assert detect_10x_bundle_member("/tmp/sample_features.tsv.gz") == (
        "genes",
        "sample",
        "features.tsv.gz",
    )
    assert detect_10x_bundle_member("/tmp/notes.csv") == (None, None, None)

    assert detect_10x_bundle_member("/tmp/zerna_upload_x/GSM5793824/matrix.mtx.gz") == (
        "matrix",
        "GSM5793824",
        "matrix.mtx.gz",
    )
    assert detect_10x_bundle_member("/tmp/zerna_upload_x/0/matrix.mtx.gz") == (
        "matrix",
        None,
        "matrix.mtx.gz",
    )

    assert sanitize_storage_relative_path("GSM1/matrix.mtx.gz") == "GSM1/matrix.mtx.gz"
    with pytest.raises(ValueError):
        sanitize_storage_relative_path("x/../y")


def test_normalize_uploaded_file_format_handles_compressed_delimited_inputs():
    from apps.api.services.dataset_service import _normalize_uploaded_file_format

    assert _normalize_uploaded_file_format("/tmp/BMET1-Tumor.count.csv.gz", "gz") == "csv"
    assert _normalize_uploaded_file_format("/tmp/metadata.tsv.gz", "gz") == "tsv"
    assert _normalize_uploaded_file_format("/tmp/meta.txt.gz", "gz") == "txt"


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


@pytest.mark.asyncio
class TestDatasetService:
    """Test suite for DatasetService."""

    async def test_create_dataset_success(
        self, dataset_service, organization, mock_file_validation_service, mock_s3_service
    ):
        """Test successful dataset creation with file validation."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]

        # Act
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test description",
            metadata={"source": "test"},
            files=files,
        )

        # Assert
        assert dataset.id is not None
        assert dataset.organization_id == organization.id
        assert dataset.name == "Test Dataset"
        assert dataset.description == "Test description"
        assert dataset.extra_metadata == {"source": "test"}
        assert len(dataset.versions) == 1
        assert dataset.versions[0].version == "v1"
        assert dataset.versions[0].cell_count == 1000
        assert dataset.versions[0].gene_count == 2000

        # Verify file validation was called
        mock_file_validation_service.validate_file.assert_called_once_with("/tmp/test.h5ad", "h5ad")

        # Verify S3 upload was called
        mock_s3_service.upload_file.assert_called_once()

    async def test_create_dataset_validation_failure(
        self, dataset_service, organization, mock_file_validation_service
    ):
        """Test dataset creation fails when file validation fails."""
        # Arrange
        mock_file_validation_service.validate_file = AsyncMock(
            return_value=ValidationResult(is_valid=False, error_message="Invalid file format")
        )
        files = [("/tmp/invalid.h5ad", "h5ad")]

        # Act & Assert
        with pytest.raises(ValueError, match="File validation failed"):
            await dataset_service.create_dataset(
                org_id=organization.id,
                name="Test Dataset",
                description="Test description",
                metadata={},
                files=files,
            )

    async def test_create_dataset_multiple_files(
        self, dataset_service, organization, mock_file_validation_service, mock_s3_service
    ):
        """Test dataset creation with multiple files."""
        # Arrange
        files = [
            ("/tmp/file1.h5ad", "h5ad"),
            ("/tmp/file2.h5ad", "h5ad"),
        ]

        # Act
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Multi-file Dataset",
            description="Multiple files",
            metadata={},
            files=files,
        )

        # Assert
        assert dataset.id is not None
        assert len(dataset.versions) == 1
        assert dataset.versions[0].cell_count == 2000  # 1000 + 1000
        assert dataset.versions[0].gene_count == 2000  # max(2000, 2000)
        assert dataset.versions[0].file_format == "h5ad"
        assert dataset.versions[0].extra_metadata["file_count"] == 2

        # Verify file validation was called twice
        assert mock_file_validation_service.validate_file.call_count == 2

        # Verify S3 upload was called twice
        assert mock_s3_service.upload_file.call_count == 2

    async def test_get_dataset_success(self, dataset_service, organization):
        """Test getting a dataset by ID with organization scoping."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        created_dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test description",
            metadata={},
            files=files,
        )

        # Act
        dataset = await dataset_service.get_dataset(
            created_dataset.id, organization.id, include_versions=True
        )

        # Assert
        assert dataset is not None
        assert dataset.id == created_dataset.id
        assert dataset.name == "Test Dataset"
        assert len(dataset.versions) == 1

    async def test_get_dataset_wrong_organization(self, dataset_service, organization):
        """Test getting a dataset fails with wrong organization ID."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        created_dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="Test description",
            metadata={},
            files=files,
        )

        # Act
        wrong_org_id = uuid4()
        dataset = await dataset_service.get_dataset(
            created_dataset.id, wrong_org_id, include_versions=True
        )

        # Assert
        assert dataset is None

    async def test_get_dataset_not_found(self, dataset_service, organization):
        """Test getting a non-existent dataset returns None."""
        # Act
        dataset = await dataset_service.get_dataset(uuid4(), organization.id, include_versions=True)

        # Assert
        assert dataset is None

    async def test_get_dataset_version_columns_reads_metadata_file(
        self, async_session, dataset_service, organization, mock_s3_service, tmp_path: Path
    ):
        """Dataset-version column inspection should surface metadata-backed batch/cluster choices."""
        dataset = Dataset(
            id=uuid4(),
            organization_id=organization.id,
            name="Columns Dataset",
            description=None,
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.flush()

        s3_path = f"{organization.id}/datasets/{dataset.id}/meta.txt"
        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=s3_path,
            file_format="mixed",
            extra_metadata={"s3_paths": [s3_path], "file_formats": ["txt"]},
        )
        async_session.add(version)
        await async_session.commit()

        metadata_file = tmp_path / "meta.txt"
        metadata_file.write_text(
            "\tcluster\tCellType\torig.ident\n"
            "cell_1\t0\tT cell\tsample_a\n"
            "cell_2\t1\tB cell\tsample_b\n"
        )

        class DummyS3Client:
            def download_file(self, bucket: str, key: str, destination: str) -> None:
                del bucket, key
                Path(destination).write_text(metadata_file.read_text())

        mock_s3_service.s3_client = DummyS3Client()

        result = await dataset_service.get_dataset_version_columns(version.id, organization.id)

        assert result["source"] == "metadata_file"
        assert result["obs_columns"] == ["cluster", "CellType", "orig.ident"]
        assert result["batch_candidates"][0] == "orig.ident"
        assert "cluster" in result["cluster_candidates"]
        assert "leiden" in result["cluster_candidates"]

    async def test_get_dataset_version_columns_recovers_from_generated_only_cache(
        self, async_session, dataset_service, organization, mock_s3_service, tmp_path: Path
    ):
        """Generated-only caches should be re-inspected when a metadata file is available."""
        dataset = Dataset(
            id=uuid4(),
            organization_id=organization.id,
            name="Subset Columns Dataset",
            description=None,
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.flush()

        s3_path = f"{organization.id}/datasets/{dataset.id}/subset_meta.txt"
        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=s3_path,
            file_format="mixed",
            extra_metadata={
                "s3_paths": [s3_path],
                "file_formats": ["txt"],
                "obs_columns": [],
                "batch_candidates": [],
                "cluster_candidates": ["leiden", "louvain"],
                "column_metadata_source": "generated_only",
            },
        )
        async_session.add(version)
        await async_session.commit()

        metadata_file = tmp_path / "subset_meta.txt"
        metadata_file.write_text(
            "\tcluster\tCellType\torig.ident\n"
            "cell_1\t0\tT cell\tsample_a\n"
            "cell_2\t1\tB cell\tsample_b\n"
        )

        class DummyS3Client:
            def download_file(self, bucket: str, key: str, destination: str) -> None:
                del bucket, key
                Path(destination).write_text(metadata_file.read_text())

        mock_s3_service.s3_client = DummyS3Client()

        result = await dataset_service.get_dataset_version_columns(version.id, organization.id)

        assert result["source"] == "metadata_file"
        assert result["obs_columns"] == ["cluster", "CellType", "orig.ident"]
        assert result["batch_candidates"][0] == "orig.ident"

    async def test_list_datasets_no_filters(self, dataset_service, organization):
        """Test listing datasets without filters."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        for i in range(5):
            await dataset_service.create_dataset(
                org_id=organization.id,
                name=f"Dataset {i}",
                description=f"Description {i}",
                metadata={},
                files=files,
            )

        # Act
        page = await dataset_service.list_datasets(org_id=organization.id, page=1, page_size=10)

        # Assert
        assert page.total == 5
        assert len(page.items) == 5
        assert page.page == 1
        assert page.page_size == 10
        assert page.total_pages == 1

    async def test_list_datasets_pagination(self, dataset_service, organization):
        """Test listing datasets with pagination."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        for i in range(15):
            await dataset_service.create_dataset(
                org_id=organization.id,
                name=f"Dataset {i}",
                description=f"Description {i}",
                metadata={},
                files=files,
            )

        # Act - Page 1
        page1 = await dataset_service.list_datasets(org_id=organization.id, page=1, page_size=10)

        # Act - Page 2
        page2 = await dataset_service.list_datasets(org_id=organization.id, page=2, page_size=10)

        # Assert
        assert page1.total == 15
        assert len(page1.items) == 10
        assert page1.total_pages == 2

        assert page2.total == 15
        assert len(page2.items) == 5
        assert page2.total_pages == 2

    async def test_list_datasets_name_filter(self, dataset_service, organization):
        """Test listing datasets with name filter."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        await dataset_service.create_dataset(
            org_id=organization.id,
            name="Alpha Dataset",
            description="",
            metadata={},
            files=files,
        )
        await dataset_service.create_dataset(
            org_id=organization.id,
            name="Beta Dataset",
            description="",
            metadata={},
            files=files,
        )
        await dataset_service.create_dataset(
            org_id=organization.id,
            name="Alpha Test",
            description="",
            metadata={},
            files=files,
        )

        # Act
        filters = DatasetFilters(name="Alpha")
        page = await dataset_service.list_datasets(
            org_id=organization.id, filters=filters, page=1, page_size=10
        )

        # Assert
        assert page.total == 2
        assert all("Alpha" in item.name for item in page.items)

    async def test_list_datasets_date_filter(self, dataset_service, organization):
        """Test listing datasets with date filters."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        now = datetime.utcnow()

        # Create dataset
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Recent Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act - Filter for datasets created after 1 hour ago
        filters = DatasetFilters(created_after=now - timedelta(hours=1))
        page = await dataset_service.list_datasets(
            org_id=organization.id, filters=filters, page=1, page_size=10
        )

        # Assert
        assert page.total == 1
        assert page.items[0].id == dataset.id

        # Act - Filter for datasets created before 1 hour ago
        filters = DatasetFilters(created_before=now - timedelta(hours=1))
        page = await dataset_service.list_datasets(
            org_id=organization.id, filters=filters, page=1, page_size=10
        )

        # Assert
        assert page.total == 0

    async def test_list_datasets_sorting(self, dataset_service, organization):
        """Test listing datasets with sorting."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        await dataset_service.create_dataset(
            org_id=organization.id,
            name="Zebra Dataset",
            description="",
            metadata={},
            files=files,
        )
        await dataset_service.create_dataset(
            org_id=organization.id,
            name="Alpha Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act - Sort by name ascending
        page = await dataset_service.list_datasets(
            org_id=organization.id,
            page=1,
            page_size=10,
            sort_by="name",
            sort_order="asc",
        )

        # Assert
        assert page.items[0].name == "Alpha Dataset"
        assert page.items[1].name == "Zebra Dataset"

        # Act - Sort by name descending
        page = await dataset_service.list_datasets(
            org_id=organization.id,
            page=1,
            page_size=10,
            sort_by="name",
            sort_order="desc",
        )

        # Assert
        assert page.items[0].name == "Zebra Dataset"
        assert page.items[1].name == "Alpha Dataset"

    async def test_create_version_success(self, dataset_service, organization):
        """Test creating a new version for an existing dataset."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act
        new_files = [("/tmp/test_v2.h5ad", "h5ad")]
        version = await dataset_service.create_version(
            dataset_id=dataset.id, org_id=organization.id, files=new_files
        )

        # Assert
        assert version.id is not None
        assert version.dataset_id == dataset.id
        assert version.version == "v2"
        assert version.cell_count == 1000
        assert version.gene_count == 2000

    async def test_create_version_wrong_organization(self, dataset_service, organization):
        """Test creating a version fails with wrong organization ID."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act & Assert
        wrong_org_id = uuid4()
        new_files = [("/tmp/test_v2.h5ad", "h5ad")]
        with pytest.raises(ValueError, match="not found or does not belong"):
            await dataset_service.create_version(
                dataset_id=dataset.id, org_id=wrong_org_id, files=new_files
            )

    async def test_create_version_validation_failure(
        self, dataset_service, organization, mock_file_validation_service
    ):
        """Test creating a version fails when file validation fails."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Mock validation failure for new version
        mock_file_validation_service.validate_file = AsyncMock(
            return_value=ValidationResult(is_valid=False, error_message="Invalid file format")
        )

        # Act & Assert
        new_files = [("/tmp/invalid.h5ad", "h5ad")]
        with pytest.raises(ValueError, match="File validation failed"):
            await dataset_service.create_version(
                dataset_id=dataset.id, org_id=organization.id, files=new_files
            )

    async def test_create_multiple_versions(self, dataset_service, organization):
        """Test creating multiple versions increments version numbers correctly."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act - Create v2
        version2 = await dataset_service.create_version(
            dataset_id=dataset.id, org_id=organization.id, files=files
        )

        # Act - Create v3
        version3 = await dataset_service.create_version(
            dataset_id=dataset.id, org_id=organization.id, files=files
        )

        # Assert
        assert version2.version == "v2"
        assert version3.version == "v3"

    async def test_delete_dataset_success(self, dataset_service, organization, mock_s3_service):
        """Test deleting a dataset and its S3 files."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act
        result = await dataset_service.delete_dataset(dataset.id, organization.id)

        # Assert
        assert result is True

        # Verify S3 delete was called
        mock_s3_service.delete_file.assert_called()

        # Verify dataset is deleted
        deleted_dataset = await dataset_service.get_dataset(dataset.id, organization.id)
        assert deleted_dataset is None

    async def test_delete_dataset_wrong_organization(self, dataset_service, organization):
        """Test deleting a dataset fails with wrong organization ID."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Test Dataset",
            description="",
            metadata={},
            files=files,
        )

        # Act
        wrong_org_id = uuid4()
        result = await dataset_service.delete_dataset(dataset.id, wrong_org_id)

        # Assert
        assert result is False

        # Verify dataset still exists
        existing_dataset = await dataset_service.get_dataset(dataset.id, organization.id)
        assert existing_dataset is not None

    async def test_update_dataset_metadata_success(self, dataset_service, organization):
        """Test updating dataset metadata."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Original Name",
            description="Original description",
            metadata={"key1": "value1"},
            files=files,
        )

        # Act
        updated_dataset = await dataset_service.update_dataset_metadata(
            dataset_id=dataset.id,
            org_id=organization.id,
            name="Updated Name",
            description="Updated description",
            metadata={"key2": "value2"},
        )

        # Assert
        assert updated_dataset is not None
        assert updated_dataset.name == "Updated Name"
        assert updated_dataset.description == "Updated description"
        assert updated_dataset.extra_metadata == {"key1": "value1", "key2": "value2"}

    async def test_update_dataset_metadata_partial(self, dataset_service, organization):
        """Test updating only some dataset metadata fields."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Original Name",
            description="Original description",
            metadata={"key1": "value1"},
            files=files,
        )

        # Act - Update only name
        updated_dataset = await dataset_service.update_dataset_metadata(
            dataset_id=dataset.id, org_id=organization.id, name="New Name"
        )

        # Assert
        assert updated_dataset.name == "New Name"
        assert updated_dataset.description == "Original description"
        assert updated_dataset.extra_metadata == {"key1": "value1"}

    async def test_update_dataset_metadata_wrong_organization(self, dataset_service, organization):
        """Test updating dataset metadata fails with wrong organization ID."""
        # Arrange
        files = [("/tmp/test.h5ad", "h5ad")]
        dataset = await dataset_service.create_dataset(
            org_id=organization.id,
            name="Original Name",
            description="",
            metadata={},
            files=files,
        )

        # Act
        wrong_org_id = uuid4()
        updated_dataset = await dataset_service.update_dataset_metadata(
            dataset_id=dataset.id, org_id=wrong_org_id, name="New Name"
        )

        # Assert
        assert updated_dataset is None

    async def test_organization_isolation(self, dataset_service, async_session):
        """Test that datasets are properly isolated by organization."""
        # Arrange - Create two organizations
        org1 = Organization(id=uuid4(), name="Org 1")
        org2 = Organization(id=uuid4(), name="Org 2")
        async_session.add(org1)
        async_session.add(org2)
        await async_session.commit()

        files = [("/tmp/test.h5ad", "h5ad")]

        # Create datasets in different organizations
        dataset1 = await dataset_service.create_dataset(
            org_id=org1.id, name="Dataset 1", description="", metadata={}, files=files
        )
        dataset2 = await dataset_service.create_dataset(
            org_id=org2.id, name="Dataset 2", description="", metadata={}, files=files
        )

        # Act - List datasets for org1
        page1 = await dataset_service.list_datasets(org_id=org1.id, page=1, page_size=10)

        # Act - List datasets for org2
        page2 = await dataset_service.list_datasets(org_id=org2.id, page=1, page_size=10)

        # Assert - Each org only sees their own datasets
        assert page1.total == 1
        assert page1.items[0].id == dataset1.id

        assert page2.total == 1
        assert page2.items[0].id == dataset2.id

        # Assert - Cannot get dataset from wrong org
        assert await dataset_service.get_dataset(dataset1.id, org2.id) is None
        assert await dataset_service.get_dataset(dataset2.id, org1.id) is None
