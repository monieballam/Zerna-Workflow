"""Tests for run routes."""

from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import RunStatus
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import Organization
from apps.api.models.pipeline import PipelineTemplate
from apps.api.services.run_service import RunService


@pytest_asyncio.fixture
async def test_dataset_version(
    async_session: AsyncSession, test_organization: Organization
) -> DatasetVersion:
    """Create a test dataset version."""
    # Create dataset
    dataset = Dataset(
        id=uuid4(),
        organization_id=test_organization.id,
        name="Test Dataset",
        description="Test dataset for run tests",
        extra_metadata={},
    )
    async_session.add(dataset)
    await async_session.commit()

    # Create dataset version
    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="1.0.0",
        s3_path=f"s3://test-bucket/{test_organization.id}/datasets/{dataset.id}/1.0.0",
        cell_count=1000,
        gene_count=2000,
        file_format="h5ad",
    )
    async_session.add(version)
    await async_session.commit()
    await async_session.refresh(version)
    return version


@pytest_asyncio.fixture
async def test_pipeline_template(
    async_session: AsyncSession, test_organization: Organization
) -> PipelineTemplate:
    """Create a test pipeline template."""
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=test_organization.id,
        name="test-pipeline",
        version="1.0.0",
        definition={
            "methods": ["qc_filter", "normalize"],
            "dependencies": {"normalize": ["qc_filter"]},
            "parameter_schema": {
                "required": ["min_cells"],
                "properties": {
                    "min_cells": {"type": "integer", "minimum": 1},
                    "max_genes": {"type": "integer", "maximum": 10000},
                },
            },
        },
        is_active=True,
    )
    async_session.add(template)
    await async_session.commit()
    await async_session.refresh(template)
    return template


@pytest.mark.asyncio
class TestCreateRun:
    """Test create run endpoint."""

    async def test_create_run_success(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test successful run creation."""
        run_service = RunService(db=async_session)

        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10, "max_genes": 5000},
            random_seed=42,
        )

        assert run.organization_id == test_organization.id
        assert run.dataset_version_id == test_dataset_version.id
        assert run.template_id == test_pipeline_template.id
        assert run.status == RunStatus.QUEUED
        assert run.parameters == {"min_cells": 10, "max_genes": 5000}
        assert run.random_seed == 42

    async def test_create_run_invalid_parameters(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test run creation with invalid parameters."""
        run_service = RunService(db=async_session)

        with pytest.raises(ValueError, match="Parameter validation failed"):
            await run_service.create_run(
                org_id=test_organization.id,
                dataset_version_id=test_dataset_version.id,
                template_id=test_pipeline_template.id,
                parameters={"max_genes": 20000},  # Missing required min_cells
            )

    async def test_create_run_dataset_not_found(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test run creation with non-existent dataset version."""
        run_service = RunService(db=async_session)

        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="not found"):
            await run_service.create_run(
                org_id=test_organization.id,
                dataset_version_id=non_existent_id,
                template_id=test_pipeline_template.id,
                parameters={"min_cells": 10},
            )

    async def test_create_run_template_not_found(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
    ):
        """Test run creation with non-existent template."""
        run_service = RunService(db=async_session)

        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="not found"):
            await run_service.create_run(
                org_id=test_organization.id,
                dataset_version_id=test_dataset_version.id,
                template_id=non_existent_id,
                parameters={"min_cells": 10},
            )


@pytest.mark.asyncio
class TestListRuns:
    """Test list runs endpoint."""

    async def test_list_runs_success(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test successful run listing."""
        run_service = RunService(db=async_session)

        # Create test runs
        run1 = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        run2 = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 20},
        )

        # List runs
        runs, total = await run_service.list_runs(org_id=test_organization.id)

        assert len(runs) == 2
        assert any(r.id == run1.id for r in runs)
        assert any(r.id == run2.id for r in runs)

    async def test_list_runs_with_status_filter(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test run listing with status filter."""
        run_service = RunService(db=async_session)

        # Create runs with different statuses
        run1 = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        run2 = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 20},
        )

        # Start run2
        await run_service.start_run(run2.id)

        # List only queued runs
        queued_runs, _ = await run_service.list_runs(
            org_id=test_organization.id, status=RunStatus.QUEUED
        )

        assert len(queued_runs) == 1
        assert queued_runs[0].id == run1.id

        # List only running runs
        running_runs, _ = await run_service.list_runs(
            org_id=test_organization.id, status=RunStatus.RUNNING
        )

        assert len(running_runs) == 1
        assert running_runs[0].id == run2.id

    async def test_list_runs_with_dataset_filter(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test run listing with dataset version filter."""
        run_service = RunService(db=async_session)

        # Create run
        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        # List runs for this dataset version
        runs, _ = await run_service.list_runs(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
        )

        assert len(runs) == 1
        assert runs[0].id == run.id


@pytest.mark.asyncio
class TestGetRun:
    """Test get run endpoint."""

    async def test_get_run_success(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test successful run retrieval."""
        run_service = RunService(db=async_session)

        # Create run
        created_run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        # Get run
        run = await run_service.get_run(run_id=created_run.id, org_id=test_organization.id)

        assert run is not None
        assert run.id == created_run.id
        assert run.status == RunStatus.QUEUED

    async def test_get_run_not_found(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test getting non-existent run."""
        run_service = RunService(db=async_session)

        non_existent_id = uuid4()
        run = await run_service.get_run(run_id=non_existent_id, org_id=test_organization.id)

        assert run is None


@pytest.mark.asyncio
class TestCancelRun:
    """Test cancel run endpoint."""

    async def test_cancel_queued_run(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test cancelling a queued run."""
        run_service = RunService(db=async_session)

        # Create run
        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        # Cancel run
        cancelled_run = await run_service.cancel_run(run.id)

        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.completed_at is not None

    async def test_cancel_running_run(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test cancelling a running run."""
        run_service = RunService(db=async_session)

        # Create and start run
        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )
        await run_service.start_run(run.id)

        # Cancel run
        cancelled_run = await run_service.cancel_run(run.id)

        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.completed_at is not None

    async def test_cancel_completed_run_fails(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test that cancelling a completed run fails."""
        run_service = RunService(db=async_session)

        # Create, start, and complete run
        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )
        await run_service.start_run(run.id)
        await run_service.complete_run(run.id, software_versions={"scanpy": "1.9.3"})

        # Try to cancel completed run
        with pytest.raises(ValueError, match="cannot be cancelled"):
            await run_service.cancel_run(run.id)


@pytest.mark.asyncio
class TestListArtifacts:
    """Test list artifacts endpoint."""

    async def test_list_artifacts_empty(
        self,
        async_session: AsyncSession,
        test_organization: Organization,
        test_dataset_version: DatasetVersion,
        test_pipeline_template: PipelineTemplate,
    ):
        """Test listing artifacts for run with no artifacts."""
        run_service = RunService(db=async_session)

        # Create run
        run = await run_service.create_run(
            org_id=test_organization.id,
            dataset_version_id=test_dataset_version.id,
            template_id=test_pipeline_template.id,
            parameters={"min_cells": 10},
        )

        # List artifacts (without generating URLs to avoid S3 dependency)
        artifacts_with_urls = await run_service.list_artifacts(
            run_id=run.id, org_id=test_organization.id, generate_download_urls=False
        )

        assert len(artifacts_with_urls) == 0

    async def test_list_artifacts_run_not_found(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test listing artifacts for non-existent run."""
        run_service = RunService(db=async_session)

        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="not found"):
            await run_service.list_artifacts(
                run_id=non_existent_id,
                org_id=test_organization.id,
                generate_download_urls=False,
            )
