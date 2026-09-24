"""Integration test for artifact association with pre-signed URLs."""

from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType

from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import Organization
from apps.api.models.pipeline import Artifact, PipelineTemplate
from apps.api.services.run_service import RunService


@pytest_asyncio.fixture
async def setup_test_data(async_session):
    """Create test organization, dataset, template, and run."""
    # Create organization
    org = Organization(
        id=uuid4(),
        name="Test Organization",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    async_session.add(org)
    await async_session.flush()

    # Create dataset with version
    dataset = Dataset(
        id=uuid4(),
        organization_id=org.id,
        name="Test Dataset",
        description="Test description",
        extra_metadata={},
    )
    async_session.add(dataset)
    await async_session.flush()

    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://test-bucket/test-dataset/file.h5ad",
        cell_count=1000,
        gene_count=2000,
        file_format="h5ad",
        extra_metadata={},
    )
    async_session.add(version)
    await async_session.flush()

    # Create pipeline template
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="1.0.0",
        definition={
            "methods": ["qc_filter", "normalize", "cluster"],
            "dependencies": {"normalize": ["qc_filter"], "cluster": ["normalize"]},
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "min_cells": {"type": "integer", "minimum": 0},
                },
                "required": ["min_cells"],
            },
        },
        is_active=True,
    )
    async_session.add(template)
    await async_session.commit()

    return org, version, template


@pytest.mark.asyncio
class TestArtifactIntegration:
    """Integration tests for artifact association and download URL generation."""

    async def test_complete_artifact_workflow(self, async_session, setup_test_data):
        """Test complete workflow: create run, add artifacts, list with download URLs."""
        # Arrange
        org, version, template = setup_test_data
        run_service = RunService(db=async_session)

        # Act 1: Create a run
        run = await run_service.create_run(
            org_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            parameters={"min_cells": 3},
        )

        # Act 2: Simulate pipeline execution by adding artifacts
        artifacts_data = [
            {
                "type": ArtifactType.H5AD,
                "path": f"{org.id}/runs/{run.id}/h5ad/output.h5ad",
                "size": 1024 * 1024,  # 1MB
                "metadata": {"cell_count": 1000, "gene_count": 2000},
            },
            {
                "type": ArtifactType.QC_REPORT,
                "path": f"{org.id}/runs/{run.id}/qc_report/report.html",
                "size": 512 * 1024,  # 512KB
                "metadata": {"passed_cells": 950, "filtered_cells": 50},
            },
            {
                "type": ArtifactType.EMBEDDING_PLOT,
                "path": f"{org.id}/runs/{run.id}/embedding_plot/umap.png",
                "size": 256 * 1024,  # 256KB
                "metadata": {"embedding_type": "umap", "n_neighbors": 15},
            },
        ]

        for artifact_data in artifacts_data:
            artifact = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=artifact_data["type"],
                s3_path=artifact_data["path"],
                size_bytes=artifact_data["size"],
                extra_metadata=artifact_data["metadata"],
            )
            async_session.add(artifact)

        await async_session.commit()

        # Act 3: List artifacts without download URLs
        artifacts_no_urls = await run_service.list_artifacts(
            run.id, org.id, generate_download_urls=False
        )

        # Assert: Verify artifacts without URLs
        assert len(artifacts_no_urls) == 3
        for artifact, url in artifacts_no_urls:
            assert url is None
            assert artifact.run_id == run.id
            assert artifact.size_bytes > 0

        # Act 4: List artifacts with download URLs
        artifacts_with_urls = await run_service.list_artifacts(
            run.id, org.id, generate_download_urls=True
        )

        # Assert: Verify artifacts with URLs
        assert len(artifacts_with_urls) == 3

        # Verify each artifact type is present
        artifact_types = {a.artifact_type for a, _ in artifacts_with_urls}
        assert ArtifactType.H5AD in artifact_types
        assert ArtifactType.QC_REPORT in artifact_types
        assert ArtifactType.EMBEDDING_PLOT in artifact_types

        # Verify metadata is preserved
        h5ad_artifact = next(
            a for a, _ in artifacts_with_urls if a.artifact_type == ArtifactType.H5AD
        )
        assert h5ad_artifact.extra_metadata["cell_count"] == 1000
        assert h5ad_artifact.extra_metadata["gene_count"] == 2000

    async def test_artifact_organization_isolation(self, async_session, setup_test_data):
        """Test that artifacts are properly isolated by organization."""
        # Arrange
        org1, version1, template1 = setup_test_data

        # Create second organization with its own data
        org2 = Organization(id=uuid4(), name="Org 2")
        async_session.add(org2)
        await async_session.flush()

        dataset2 = Dataset(id=uuid4(), organization_id=org2.id, name="Dataset 2")
        async_session.add(dataset2)
        await async_session.flush()

        version2 = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset2.id,
            version="v1",
            s3_path="s3://bucket/dataset2/file.h5ad",
            file_format="h5ad",
        )
        async_session.add(version2)
        await async_session.flush()

        template2 = PipelineTemplate(
            id=uuid4(),
            organization_id=org2.id,
            name="Template 2",
            version="1.0.0",
            definition={"methods": ["qc_filter"], "dependencies": {}},
        )
        async_session.add(template2)
        await async_session.commit()

        run_service = RunService(db=async_session)

        # Create runs in different organizations
        run1 = await run_service.create_run(
            org_id=org1.id,
            dataset_version_id=version1.id,
            template_id=template1.id,
            parameters={"min_cells": 3},
        )

        run2 = await run_service.create_run(
            org_id=org2.id,
            dataset_version_id=version2.id,
            template_id=template2.id,
            parameters={},
        )

        # Add artifacts to both runs
        artifact1 = Artifact(
            id=uuid4(),
            run_id=run1.id,
            artifact_type=ArtifactType.H5AD,
            s3_path=f"{org1.id}/runs/{run1.id}/output.h5ad",
            size_bytes=1024,
        )
        artifact2 = Artifact(
            id=uuid4(),
            run_id=run2.id,
            artifact_type=ArtifactType.H5AD,
            s3_path=f"{org2.id}/runs/{run2.id}/output.h5ad",
            size_bytes=2048,
        )
        async_session.add(artifact1)
        async_session.add(artifact2)
        await async_session.commit()

        # Act & Assert: Org1 cannot access Org2's artifacts
        with pytest.raises(ValueError, match="not found or does not belong"):
            await run_service.list_artifacts(run2.id, org1.id)

        # Act & Assert: Org2 cannot access Org1's artifacts
        with pytest.raises(ValueError, match="not found or does not belong"):
            await run_service.list_artifacts(run1.id, org2.id)

        # Act & Assert: Each org can access their own artifacts
        artifacts1 = await run_service.list_artifacts(
            run1.id, org1.id, generate_download_urls=False
        )
        artifacts2 = await run_service.list_artifacts(
            run2.id, org2.id, generate_download_urls=False
        )

        assert len(artifacts1) == 1
        assert artifacts1[0][0].size_bytes == 1024

        assert len(artifacts2) == 1
        assert artifacts2[0][0].size_bytes == 2048
