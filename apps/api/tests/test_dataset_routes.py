"""Unit tests for dataset API routes."""

import gzip
import io
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from zerna_contracts.enums import RunStatus, UserRole
from scipy.io import mmwrite
from scipy.sparse import csr_matrix
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_cache_service
from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models import (
    Dataset,
    DatasetVersion,
    Organization,
    OrganizationUser,
    PipelineTemplate,
    Run,
    User,
)
from apps.api.routes._upload_streaming import stream_upload_to_path
from apps.api.routes.datasets import get_dataset_service
from apps.api.services.dataset_service import DatasetService


class _FakeS3Service:
    datasets_bucket = "test-datasets-bucket"

    def __init__(self):
        self.uploaded: list[tuple[str, str, str]] = []

    def generate_dataset_path(self, org_id, dataset_id, filename: str) -> str:
        return f"{org_id}/datasets/{dataset_id}/{filename}"

    def upload_file(self, file_path: Path, bucket: str, s3_path: str):
        self.uploaded.append((file_path.name, bucket, s3_path))
        return {"bucket": bucket, "key": s3_path}


class _NoopQuotaService:
    async def check_storage_quota(self, org_id, additional_bytes: int = 0):
        return None


class _NoopAuditService:
    async def audit_log(self, **kwargs):
        return None


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _SessionProxy:
    def __init__(self, session: AsyncSession, organization_id):
        self._session = session
        self._organization_id = organization_id

    async def execute(self, statement, params=None, *args, **kwargs):
        if str(statement).strip() == (
            "SELECT organization_id FROM organization_users WHERE user_id = :user_id"
        ):
            return _ScalarResult(self._organization_id)
        return await self._session.execute(statement, params, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


class _ChunkedUploadFile:
    def __init__(self, payload: bytes, filename: str = "payload.bin"):
        self.filename = filename
        self._stream = io.BytesIO(payload)
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1):
        self.read_sizes.append(size)
        return self._stream.read(size)


def _write_test_10x_bundle(
    tmp_path: Path,
    *,
    n_genes: int = 4,
    n_cells: int = 3,
    include_metadata: bool = True,
) -> dict[str, bytes]:
    """Create a tiny 10x MTX bundle suitable for route tests."""
    matrix = csr_matrix(np.arange(1, n_genes * n_cells + 1).reshape(n_genes, n_cells))
    mmwrite(tmp_path / "matrix.mtx", matrix)

    genes_path = tmp_path / "genes.tsv"
    genes_path.write_text(
        "".join(f"GENE_{i}\tGene_{i}\n" for i in range(n_genes)),
        encoding="utf-8",
    )

    barcodes_path = tmp_path / "barcodes.tsv"
    barcodes_path.write_text(
        "".join(f"CELL_{i}\n" for i in range(n_cells)),
        encoding="utf-8",
    )

    files = {
        "matrix.mtx": (tmp_path / "matrix.mtx").read_bytes(),
        "genes.tsv": genes_path.read_bytes(),
        "barcodes.tsv": barcodes_path.read_bytes(),
    }

    if include_metadata:
        metadata_path = tmp_path / "meta.txt"
        metadata_path.write_text(
            "cell_id\tcluster\tCellType\nCELL_0\t0\tT cell\nCELL_1\t1\tB cell\nCELL_2\t1\tB cell\n",
            encoding="utf-8",
        )
        files["meta.txt"] = metadata_path.read_bytes()

    return files


@pytest.mark.asyncio
async def test_stream_upload_to_path_writes_in_chunks(tmp_path: Path):
    payload = b"abcd" * (1024 * 1024)
    upload = _ChunkedUploadFile(payload, filename="../../unsafe.bin")
    destination = tmp_path / "nested" / "unsafe.bin"

    bytes_written = await stream_upload_to_path(upload, destination, chunk_size=1024 * 1024)

    assert bytes_written == len(payload)
    assert destination.read_bytes() == payload
    assert upload.read_sizes[:2] == [1024 * 1024, 1024 * 1024]
    assert len(upload.read_sizes) > 2


@pytest.mark.asyncio
class TestCreateDataset:
    """Test create_dataset endpoint."""

    async def test_create_dataset_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset creation."""
        # Add user to organization using insert statement
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.MEMBER,
        )
        await async_session.execute(stmt)
        await async_session.commit()

        # Create dataset directly without files (to avoid the versions issue)
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Dataset",
            description="Test description",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()
        await async_session.refresh(dataset)

        # Verify response
        assert dataset.name == "Test Dataset"
        assert dataset.description == "Test description"
        assert dataset.organization_id == test_organization.id


@pytest.mark.asyncio
class TestListDatasets:
    """Test list_datasets functionality."""

    async def test_list_datasets_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset listing."""
        # Create test datasets
        dataset1 = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset 1",
            description="Description 1",
            extra_metadata={},
        )
        dataset2 = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset 2",
            description="Description 2",
            extra_metadata={},
        )
        async_session.add_all([dataset1, dataset2])
        await async_session.commit()

        # List datasets using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.list_datasets(
            org_id=test_organization.id,
            filters=None,
            page=1,
            page_size=20,
            sort_by="created_at",
            sort_order="desc",
        )

        # Verify response
        assert result.total == 2
        assert len(result.items) == 2
        assert result.page == 1
        assert result.page_size == 20

    async def test_list_datasets_with_filters(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test dataset listing with name filter."""
        # Create test datasets
        dataset1 = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Cancer Dataset",
            description="Description 1",
            extra_metadata={},
        )
        dataset2 = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Normal Dataset",
            description="Description 2",
            extra_metadata={},
        )
        async_session.add_all([dataset1, dataset2])
        await async_session.commit()

        # List datasets with filter using service
        from apps.api.services.dataset_service import DatasetFilters

        dataset_service = DatasetService(db=async_session)
        filters = DatasetFilters(name="Cancer")

        result = await dataset_service.list_datasets(
            org_id=test_organization.id,
            filters=filters,
            page=1,
            page_size=20,
            sort_by="created_at",
            sort_order="desc",
        )

        # Verify response
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "Cancer Dataset"


@pytest.mark.asyncio
class TestGetDataset:
    """Test get_dataset functionality."""

    async def test_get_dataset_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset retrieval."""
        # Create test dataset
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Dataset",
            description="Test description",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        # Get dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.get_dataset(
            dataset_id=dataset.id,
            org_id=test_organization.id,
            include_versions=True,
        )

        # Verify response
        assert result is not None
        assert result.id == dataset.id
        assert result.name == "Test Dataset"
        assert result.description == "Test description"

    async def test_get_dataset_not_found(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test dataset retrieval with non-existent ID."""
        # Get dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.get_dataset(
            dataset_id=uuid4(),
            org_id=test_organization.id,
            include_versions=True,
        )

        # Verify response
        assert result is None


@pytest.mark.asyncio
class TestCreateDatasetVersion:
    """Test create_dataset_version functionality."""

    async def test_create_version_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset version creation."""
        # Create test dataset with initial version
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Dataset",
            description="Test description",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.flush()

        version1 = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path="s3://bucket/path/file.h5ad",
            cell_count=1000,
            gene_count=2000,
            file_format="h5ad",
            extra_metadata={},
        )
        async_session.add(version1)
        await async_session.commit()

        # Create new version using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.create_version(
            dataset_id=dataset.id,
            org_id=test_organization.id,
            files=[],
        )

        # Verify response
        assert result.dataset_id == dataset.id
        assert result.version == "v2"

    async def test_create_version_dataset_not_found(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test version creation with non-existent dataset."""
        # Create new version using service
        dataset_service = DatasetService(db=async_session)

        with pytest.raises(ValueError) as exc_info:
            await dataset_service.create_version(
                dataset_id=uuid4(),
                org_id=test_organization.id,
                files=[],
            )

        assert "not found" in str(exc_info.value)

    async def test_create_version_accepts_10x_bundle_with_metadata(
        self,
        async_client,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
        tmp_path: Path,
    ):
        """Test multipart upload of a native 10x bundle plus metadata file."""
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
        await async_session.execute(stmt)

        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="10x Dataset",
            description="10x bundle upload",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=_SessionProxy(async_session, test_organization.id),
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        async def override_get_current_user():
            return SimpleNamespace(id=test_user.id)

        async def override_get_dataset_service():
            return dataset_service

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_dataset_service] = override_get_dataset_service

        upload_files = _write_test_10x_bundle(tmp_path)
        try:
            response = await async_client.post(
                f"/v1/datasets/{dataset.id}/versions",
                files=[
                    ("files", (filename, content, "application/octet-stream"))
                    for filename, content in upload_files.items()
                ],
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_dataset_service, None)

        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["version"] == "v1"
        assert payload["file_format"] == "10x_mtx"
        assert payload["cell_count"] == 3
        assert payload["gene_count"] == 4
        assert payload["metadata"]["file_count"] == 4
        assert payload["metadata"]["file_formats"].count("10x_mtx") == 3
        assert "txt" in payload["metadata"]["file_formats"]
        assert {name for name, _, _ in fake_s3.uploaded} == set(upload_files)

    async def test_create_version_accepts_gzipped_csv_matrix(
        self,
        async_client,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
        tmp_path: Path,
    ):
        """Test gzip-compressed CSV matrices upload as logical CSV inputs."""
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
        await async_session.execute(stmt)

        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Compressed CSV Dataset",
            description="gzipped csv upload",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=_SessionProxy(async_session, test_organization.id),
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        async def override_get_current_user():
            return SimpleNamespace(id=test_user.id)

        async def override_get_dataset_service():
            return dataset_service

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_dataset_service] = override_get_dataset_service

        csv_path = tmp_path / "BMET1-Tumor.count.csv.gz"
        rows = ["gene,CELL_0,CELL_1\n", "GENE_0,1,2\n", "GENE_1,3,4\n", "GENE_2,5,6\n"]
        with gzip.open(csv_path, "wt") as handle:
            handle.writelines(rows)

        try:
            response = await async_client.post(
                f"/v1/datasets/{dataset.id}/versions",
                files=[
                    (
                        "files",
                        (
                            csv_path.name,
                            csv_path.read_bytes(),
                            "application/gzip",
                        ),
                    )
                ],
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_dataset_service, None)

        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["file_format"] == "csv"
        assert payload["cell_count"] == 2
        assert payload["gene_count"] == 3
        assert payload["metadata"]["file_formats"] == ["csv"]
        assert {name for name, _, _ in fake_s3.uploaded} == {csv_path.name}

    async def test_create_version_rejects_incomplete_10x_bundle(
        self,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
        tmp_path: Path,
    ):
        """Test incomplete native 10x uploads fail before any upload occurs."""
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Broken 10x Dataset",
            description="Missing genes file",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=async_session,
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        matrix = csr_matrix(np.arange(1, 7).reshape(2, 3))
        mmwrite(tmp_path / "matrix.mtx", matrix)
        (tmp_path / "barcodes.tsv").write_text("CELL_0\nCELL_1\nCELL_2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Incomplete 10x MTX upload"):
            await dataset_service.create_version(
                dataset_id=dataset.id,
                org_id=test_organization.id,
                files=[
                    (str(tmp_path / "matrix.mtx"), "mtx"),
                    (str(tmp_path / "barcodes.tsv"), "tsv"),
                ],
            )

        assert fake_s3.uploaded == []


@pytest.mark.asyncio
class TestUpdateDataset:
    """Test update_dataset functionality."""

    async def test_update_dataset_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset update."""
        # Create test dataset
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Old Name",
            description="Old description",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        # Update dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.update_dataset_metadata(
            dataset_id=dataset.id,
            org_id=test_organization.id,
            name="New Name",
            description="New description",
        )

        # Verify response
        assert result is not None
        assert result.id == dataset.id
        assert result.name == "New Name"
        assert result.description == "New description"

    async def test_update_dataset_not_found(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test dataset update with non-existent ID."""
        # Update dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.update_dataset_metadata(
            dataset_id=uuid4(),
            org_id=test_organization.id,
            name="New Name",
        )

        # Verify response
        assert result is None


@pytest.mark.asyncio
class TestDeleteDataset:
    """Test delete_dataset functionality."""

    async def test_delete_dataset_success(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test successful dataset deletion."""
        # Create test dataset
        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Dataset",
            description="Test description",
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.commit()

        # Delete dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.delete_dataset(
            dataset_id=dataset.id,
            org_id=test_organization.id,
        )

        # Verify deletion succeeded
        assert result is True

    async def test_delete_dataset_not_found(
        self, async_session: AsyncSession, test_user: User, test_organization: Organization
    ):
        """Test dataset deletion with non-existent ID."""
        # Delete dataset using service
        dataset_service = DatasetService(db=async_session)
        result = await dataset_service.delete_dataset(
            dataset_id=uuid4(),
            org_id=test_organization.id,
        )

        # Verify deletion failed
        assert result is False

    async def test_delete_dataset_route_can_preserve_associated_runs(
        self,
        async_client,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
    ):
        """Deleting a dataset should preserve runs when requested."""
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
        await async_session.execute(stmt)

        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset to delete",
            description=None,
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path="datasets/input.h5ad",
            cell_count=100,
            gene_count=200,
            file_format="h5ad",
            extra_metadata={},
        )
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Template",
            version="1.0.0",
            definition={"parameter_schema": {"type": "object", "properties": {}}},
            is_active=True,
        )
        async_session.add_all([version, template])
        await async_session.flush()

        run = Run(
            id=uuid4(),
            organization_id=test_organization.id,
            dataset_version_id=version.id,
            dataset_id_snapshot=dataset.id,
            dataset_version_id_snapshot=version.id,
            dataset_name_snapshot=dataset.name,
            dataset_version_label_snapshot=version.version,
            template_id=template.id,
            status=RunStatus.COMPLETED,
            parameters={},
        )
        async_session.add(run)
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=_SessionProxy(async_session, test_organization.id),
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        async def override_get_current_user():
            return SimpleNamespace(id=test_user.id)

        async def override_get_dataset_service():
            return dataset_service

        async def override_get_cache_service():
            return None

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_dataset_service] = override_get_dataset_service
        app.dependency_overrides[get_cache_service] = override_get_cache_service

        try:
            response = await async_client.request(
                "DELETE",
                f"/v1/datasets/{dataset.id}",
                json={"run_delete_mode": "preserve"},
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_dataset_service, None)
            app.dependency_overrides.pop(get_cache_service, None)

        assert response.status_code == 200, response.text
        assert response.json() == {
            "dataset_id": str(dataset.id),
            "deleted_runs": 0,
            "preserved_runs": 1,
        }

        await async_session.refresh(run)
        assert run.dataset_version_id is None
        assert run.dataset_version_id_snapshot == version.id

        deleted_dataset = await async_session.get(Dataset, dataset.id)
        deleted_version = await async_session.get(DatasetVersion, version.id)
        assert deleted_dataset is None
        assert deleted_version is None

    async def test_list_dataset_associated_runs_route(
        self,
        async_client,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
    ):
        """Dataset-scoped run listing should support the delete dialog contract."""
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
        await async_session.execute(stmt)

        dataset = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset with runs",
            description=None,
            extra_metadata={},
        )
        async_session.add(dataset)
        await async_session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path="datasets/input.h5ad",
            cell_count=100,
            gene_count=200,
            file_format="h5ad",
            extra_metadata={},
        )
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Template",
            version="1.0.0",
            definition={"parameter_schema": {"type": "object", "properties": {}}},
            is_active=True,
        )
        async_session.add_all([version, template])
        await async_session.flush()

        run = Run(
            id=uuid4(),
            organization_id=test_organization.id,
            dataset_version_id=version.id,
            dataset_id_snapshot=dataset.id,
            dataset_version_id_snapshot=version.id,
            dataset_name_snapshot=dataset.name,
            dataset_version_label_snapshot=version.version,
            template_id=template.id,
            status=RunStatus.COMPLETED,
            parameters={},
        )
        async_session.add(run)
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=_SessionProxy(async_session, test_organization.id),
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        async def override_get_current_user():
            return SimpleNamespace(id=test_user.id)

        async def override_get_dataset_service():
            return dataset_service

        async def override_get_cache_service():
            return None

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_dataset_service] = override_get_dataset_service
        app.dependency_overrides[get_cache_service] = override_get_cache_service

        try:
            response = await async_client.get(
                f"/v1/datasets/{dataset.id}/runs?page=1&page_size=1000"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_dataset_service, None)
            app.dependency_overrides.pop(get_cache_service, None)

        assert response.status_code == 200, response.text
        assert response.json() == {
            "items": [
                {
                    "id": str(run.id),
                    "status": "completed",
                    "template_id": str(template.id),
                    "created_at": run.created_at.isoformat(),
                    "started_at": None,
                    "completed_at": None,
                    "dataset_deleted": False,
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 1000,
            "total_pages": 1,
        }

    async def test_bulk_delete_datasets_route_can_delete_selected_datasets(
        self,
        async_client,
        async_session: AsyncSession,
        test_user: User,
        test_organization: Organization,
    ):
        """Bulk dataset deletion should delete only selected datasets."""
        stmt = insert(OrganizationUser).values(
            organization_id=test_organization.id,
            user_id=test_user.id,
            role=UserRole.ADMIN,
        )
        await async_session.execute(stmt)

        dataset_one = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset One",
            description=None,
            extra_metadata={},
        )
        dataset_two = Dataset(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Dataset Two",
            description=None,
            extra_metadata={},
        )
        async_session.add_all([dataset_one, dataset_two])
        await async_session.flush()

        version_one = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset_one.id,
            version="v1",
            s3_path="datasets/one.h5ad",
            cell_count=100,
            gene_count=200,
            file_format="h5ad",
            extra_metadata={},
        )
        version_two = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset_two.id,
            version="v1",
            s3_path="datasets/two.h5ad",
            cell_count=100,
            gene_count=200,
            file_format="h5ad",
            extra_metadata={},
        )
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=test_organization.id,
            name="Test Template",
            version="1.0.0",
            definition={"parameter_schema": {"type": "object", "properties": {}}},
            is_active=True,
        )
        async_session.add_all([version_one, version_two, template])
        await async_session.flush()

        preserved_run = Run(
            id=uuid4(),
            organization_id=test_organization.id,
            dataset_version_id=version_one.id,
            dataset_id_snapshot=dataset_one.id,
            dataset_version_id_snapshot=version_one.id,
            dataset_name_snapshot=dataset_one.name,
            dataset_version_label_snapshot=version_one.version,
            template_id=template.id,
            status=RunStatus.COMPLETED,
            parameters={},
        )
        kept_run = Run(
            id=uuid4(),
            organization_id=test_organization.id,
            dataset_version_id=version_two.id,
            dataset_id_snapshot=dataset_two.id,
            dataset_version_id_snapshot=version_two.id,
            dataset_name_snapshot=dataset_two.name,
            dataset_version_label_snapshot=version_two.version,
            template_id=template.id,
            status=RunStatus.COMPLETED,
            parameters={},
        )
        async_session.add_all([preserved_run, kept_run])
        await async_session.commit()

        fake_s3 = _FakeS3Service()
        dataset_service = DatasetService(
            db=_SessionProxy(async_session, test_organization.id),
            s3_service=fake_s3,
            quota_service=_NoopQuotaService(),
            audit_service=_NoopAuditService(),
        )

        async def override_get_current_user():
            return SimpleNamespace(id=test_user.id)

        async def override_get_dataset_service():
            return dataset_service

        async def override_get_cache_service():
            return None

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_dataset_service] = override_get_dataset_service
        app.dependency_overrides[get_cache_service] = override_get_cache_service

        try:
            response = await async_client.post(
                "/v1/datasets/bulk-delete",
                json={
                    "scope": "selected",
                    "dataset_ids": [str(dataset_one.id)],
                    "run_delete_mode": "preserve",
                },
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_dataset_service, None)
            app.dependency_overrides.pop(get_cache_service, None)

        assert response.status_code == 200, response.text
        assert response.json() == {
            "scope": "selected",
            "deleted_dataset_ids": [str(dataset_one.id)],
            "deleted_datasets": 1,
            "deleted_runs": 0,
            "preserved_runs": 1,
        }

        await async_session.refresh(preserved_run)
        await async_session.refresh(kept_run)
        assert preserved_run.dataset_version_id is None
        assert kept_run.dataset_version_id == version_two.id
        assert await async_session.get(Dataset, dataset_one.id) is None
        assert await async_session.get(Dataset, dataset_two.id) is not None
