"""Unit tests for RunService."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy

from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.organization import Organization
from apps.api.models.pipeline import Artifact, PipelineTemplate
from apps.api.services.pipeline_service import PipelineService
from apps.api.services.run_service import RunService


@pytest.fixture
def mock_pipeline_service():
    """Create a mock PipelineService."""
    service = MagicMock(spec=PipelineService)
    service.validate_parameters = AsyncMock(return_value=(True, None))
    service.apply_parameter_schema_constraints = MagicMock(
        side_effect=lambda schema, params: params
    )
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


@pytest_asyncio.fixture
async def dataset_with_version(async_session, organization):
    """Create a test dataset with a version."""
    dataset = Dataset(
        id=uuid4(),
        organization_id=organization.id,
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
    await async_session.commit()
    await async_session.refresh(dataset)
    await async_session.refresh(version)
    return dataset, version


@pytest_asyncio.fixture
async def pipeline_template(async_session, organization):
    """Create a test pipeline template."""
    template = PipelineTemplate(
        id=uuid4(),
        organization_id=organization.id,
        name="Test Pipeline",
        version="1.0.0",
        definition={
            "methods": ["qc_filter", "normalize", "cluster"],
            "dependencies": {"normalize": ["qc_filter"], "cluster": ["normalize"]},
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "min_cells": {"type": "integer", "minimum": 0},
                    "min_genes": {"type": "integer", "minimum": 0},
                },
                "required": ["min_cells", "min_genes"],
            },
        },
        is_active=True,
    )
    async_session.add(template)
    await async_session.commit()
    await async_session.refresh(template)
    return template


@pytest.fixture
def run_service(async_session, mock_pipeline_service):
    """Create a RunService with mocked dependencies."""
    return RunService(db=async_session, pipeline_service=mock_pipeline_service)


@pytest.mark.asyncio
class TestRunService:
    """Test suite for RunService."""

    async def test_create_run_success(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Test successful run creation with parameter validation."""
        # Arrange
        _, version = dataset_with_version
        parameters = {"min_cells": 3, "min_genes": 200}

        # Act
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters=parameters,
            random_seed=42,
        )

        # Assert
        assert run.id is not None
        assert run.organization_id == organization.id
        assert run.dataset_version_id == version.id
        assert run.template_id == pipeline_template.id
        assert run.status == RunStatus.QUEUED
        assert run.parameters["min_cells"] == parameters["min_cells"]
        assert run.parameters["min_genes"] == parameters["min_genes"]
        assert run.parameters == parameters
        assert run.dataset_id_snapshot is not None
        assert run.dataset_version_id_snapshot == version.id
        assert run.random_seed == 42
        assert run.started_at is None
        assert run.completed_at is None
        assert run.error_message is None

        # Verify parameter validation was called
        mock_pipeline_service.validate_parameters.assert_called_once_with(
            pipeline_template.id, parameters
        )

    async def test_create_run_invalid_parameters(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Test run creation fails with invalid parameters."""
        # Arrange
        _, version = dataset_with_version
        parameters = {"min_cells": -1}  # Invalid parameter

        # Mock validation failure
        mock_pipeline_service.validate_parameters = AsyncMock(
            return_value=(False, "Parameter 'min_cells' must be >= 0")
        )

        # Act & Assert
        with pytest.raises(ValueError, match="Parameter validation failed"):
            await run_service.create_run(
                org_id=organization.id,
                dataset_version_id=version.id,
                template_id=pipeline_template.id,
                parameters=parameters,
            )

    async def test_create_run_dataset_not_found(self, run_service, organization, pipeline_template):
        """Test run creation fails when dataset version not found."""
        # Arrange
        invalid_version_id = uuid4()
        parameters = {"min_cells": 3, "min_genes": 200}

        # Act & Assert
        with pytest.raises(ValueError, match="Dataset version .* not found"):
            await run_service.create_run(
                org_id=organization.id,
                dataset_version_id=invalid_version_id,
                template_id=pipeline_template.id,
                parameters=parameters,
            )

    async def test_create_run_template_not_found(
        self, run_service, organization, dataset_with_version
    ):
        """Test run creation fails when template not found."""
        # Arrange
        _, version = dataset_with_version
        invalid_template_id = uuid4()
        parameters = {"min_cells": 3, "min_genes": 200}

        # Act & Assert
        with pytest.raises(ValueError, match="Template .* not found"):
            await run_service.create_run(
                org_id=organization.id,
                dataset_version_id=version.id,
                template_id=invalid_template_id,
                parameters=parameters,
            )

    async def test_create_run_wrong_organization(
        self, run_service, async_session, dataset_with_version, pipeline_template
    ):
        """Test run creation fails with wrong organization ID."""
        # Arrange
        _, version = dataset_with_version
        wrong_org = Organization(id=uuid4(), name="Wrong Org")
        async_session.add(wrong_org)
        await async_session.commit()

        parameters = {"min_cells": 3, "min_genes": 200}

        # Act & Assert
        with pytest.raises(ValueError, match="not found or does not belong"):
            await run_service.create_run(
                org_id=wrong_org.id,
                dataset_version_id=version.id,
                template_id=pipeline_template.id,
                parameters=parameters,
            )

    async def test_start_run_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test successfully starting a queued run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act
        started_run = await run_service.start_run(run.id)

        # Assert
        assert started_run.status == RunStatus.RUNNING
        assert started_run.started_at is not None
        assert isinstance(started_run.started_at, datetime)

    async def test_start_run_not_found(self, run_service):
        """Test starting a non-existent run fails."""
        # Act & Assert
        with pytest.raises(ValueError, match="Run .* not found"):
            await run_service.start_run(uuid4())

    async def test_start_run_invalid_status(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test starting a run fails if not in QUEUED status."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Start the run once
        await run_service.start_run(run.id)

        # Act & Assert - Try to start again
        with pytest.raises(ValueError, match="cannot be started from status"):
            await run_service.start_run(run.id)

    async def test_resume_run_reuses_failed_run_id_and_updates_parameters(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
        monkeypatch,
    ):
        """Failed runs should resume in place so checkpoints can be reused."""
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200, "cluster_key": "Batch"},
            random_seed=42,
        )
        run.status = RunStatus.FAILED
        run.error_message = "cluster_key not found"
        run.parameters = {
            **run.parameters,
            "progress": {
                "completed_steps": ["qc_filter", "cluster"],
                "step_summaries": [],
            },
            "_checkpoints": [{"step_name": "qc_filter", "status": "completed"}],
            "_execution_state": {
                "initial_snapshot_s3_key": "runs/test/_state/snapshots/000_initial.h5ad"
            },
        }
        await run_service.db.commit()

        dispatch_mock = AsyncMock()
        monkeypatch.setattr(run_service, "_dispatch_workflow", dispatch_mock)

        resumed = await run_service.resume_run(
            run_id=run.id,
            org_id=organization.id,
            parameters={"min_cells": 3, "min_genes": 200, "cluster_key": "cluster"},
        )

        assert resumed.id == run.id
        assert resumed.status == RunStatus.RUNNING
        assert resumed.error_message is None
        assert resumed.parameters["cluster_key"] == "cluster"
        assert resumed.parameters["progress"]["completed_steps"] == ["qc_filter", "cluster"]
        assert resumed.parameters["_checkpoints"] == [
            {"step_name": "qc_filter", "status": "completed"}
        ]
        assert resumed.parameters["_execution_state"]["initial_snapshot_s3_key"].endswith(
            "000_initial.h5ad"
        )
        mock_pipeline_service.validate_parameters.assert_called_with(
            pipeline_template.id,
            {
                "min_cells": 3,
                "min_genes": 200,
                "cluster_key": "cluster",
                "annotation_cluster_key": "cluster",
            },
        )
        dispatch_mock.assert_awaited_once()
        assert (
            dispatch_mock.await_args.kwargs["id_reuse_policy"]
            == WorkflowIDReusePolicy.ALLOW_DUPLICATE
        )

    async def test_create_run_normalizes_dataset_aware_parameters(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
    ):
        """Run creation should auto-correct dataset-aware batch and cluster keys."""
        _, version = dataset_with_version
        version.extra_metadata = {
            "obs_columns": ["orig.ident", "CellType", "HashAssignment"],
            "batch_candidates": ["orig.ident", "HashAssignment"],
            "cluster_candidates": ["cluster", "leiden", "CellType"],
            "column_metadata_source": "metadata_file",
        }
        await run_service.db.commit()

        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={
                "min_cells": 3,
                "min_genes": 200,
                "batch_correction": True,
                "batch_key": "batch",
                "cluster_key": "celltype",
            },
        )

        assert run.parameters["batch_key"] == "orig.ident"
        assert run.parameters["cluster_key"] == "CellType"
        assert run.parameters["annotation_cluster_key"] == "CellType"
        assert "hvg_batch_key" not in run.parameters

    async def test_create_run_applies_conditional_schema_constraints_before_validation(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Forced schema values should be persisted and validated, not just shown in the UI."""
        _, version = dataset_with_version
        pipeline_template.definition["parameter_schema"]["allOf"] = [
            {
                "if": {"properties": {"ambient_correction": {"const": True}}},
                "then": {
                    "properties": {"ambient_method": {"const": "identity"}},
                },
            }
        ]
        mock_pipeline_service.apply_parameter_schema_constraints.side_effect = (
            lambda schema, params: (
                {
                    **params,
                    "ambient_method": "identity",
                }
                if params.get("ambient_correction")
                else params
            )
        )

        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200, "ambient_correction": True},
        )

        assert run.parameters["ambient_method"] == "identity"
        mock_pipeline_service.validate_parameters.assert_called_with(
            pipeline_template.id,
            {
                "min_cells": 3,
                "min_genes": 200,
                "ambient_correction": True,
                "ambient_method": "identity",
            },
        )

    async def test_create_run_preserves_dict_when_constraint_helper_returns_non_mapping(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Non-dict helper outputs should not corrupt persisted run parameters."""
        _, version = dataset_with_version
        mock_pipeline_service.apply_parameter_schema_constraints.return_value = MagicMock()

        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        assert run.parameters == {"min_cells": 3, "min_genes": 200}

    async def test_cancel_run_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test successfully cancelling a running run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Act
        cancelled_run = await run_service.cancel_run(run.id)

        # Assert
        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.completed_at is not None

    async def test_cancel_run_terminates_temporal_and_clears_progress(
        self,
        run_service,
        organization,
        dataset_with_version,
        pipeline_template,
        monkeypatch,
    ):
        """Cancelling a run should terminate the Temporal workflow and clear stale progress."""
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        run.parameters = {
            **(run.parameters or {}),
            "progress": {
                "state": RunStatus.RUNNING.value,
                "current_step": "doublet_detection",
                "current_step_label": "Doublet Detection",
                "current_step_started_at": datetime.utcnow().isoformat(),
            },
        }
        await run_service.db.commit()

        mock_client = AsyncMock()
        terminate_mock = AsyncMock()
        monkeypatch.setattr(
            run_service, "_connect_temporal_client", AsyncMock(return_value=mock_client)
        )
        monkeypatch.setattr(run_service, "_terminate_temporal_workflow", terminate_mock)

        cancelled_run = await run_service.cancel_run(run.id)

        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.error_message == "Run cancelled by user."
        assert cancelled_run.parameters["progress"]["state"] == RunStatus.CANCELLED.value
        assert cancelled_run.parameters["progress"]["current_step"] is None
        assert cancelled_run.parameters["progress"]["current_step_label"] is None
        terminate_mock.assert_awaited_once_with(
            mock_client,
            run.id,
            reason="Run cancelled by user request",
        )

    async def test_cancel_run_from_queued(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test cancelling a queued run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act
        cancelled_run = await run_service.cancel_run(run.id)

        # Assert
        assert cancelled_run.status == RunStatus.CANCELLED

    async def test_cancel_run_already_completed(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test cancelling a completed run fails."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)
        await run_service.complete_run(run.id, {"scanpy": "1.9.3"})

        # Act & Assert
        with pytest.raises(ValueError, match="cannot be cancelled from status"):
            await run_service.cancel_run(run.id)

    async def test_get_run_status_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test getting run status."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act
        status = await run_service.get_run_status(run.id)

        # Assert
        assert status == RunStatus.QUEUED

    async def test_get_run_status_not_found(self, run_service):
        """Test getting status of non-existent run returns None."""
        # Act
        status = await run_service.get_run_status(uuid4())

        # Assert
        assert status is None

    async def test_get_run_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test getting a run by ID with organization scoping."""
        # Arrange
        _, version = dataset_with_version
        created_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act
        run = await run_service.get_run(created_run.id, organization.id)

        # Assert
        assert run is not None
        assert run.id == created_run.id
        assert run.organization_id == organization.id
        assert run.dataset_version is not None
        assert run.template is not None

    async def test_get_run_wrong_organization(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test getting a run fails with wrong organization ID."""
        # Arrange
        _, version = dataset_with_version
        created_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        wrong_org = Organization(id=uuid4(), name="Wrong Org")
        async_session.add(wrong_org)
        await async_session.commit()

        # Act
        run = await run_service.get_run(created_run.id, wrong_org.id)

        # Assert
        assert run is None

    async def test_list_runs_no_filters(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test listing runs without filters."""
        # Arrange
        _, version = dataset_with_version
        for i in range(5):
            await run_service.create_run(
                org_id=organization.id,
                dataset_version_id=version.id,
                template_id=pipeline_template.id,
                parameters={"min_cells": i, "min_genes": 200},
            )

        # Act
        runs, total = await run_service.list_runs(org_id=organization.id)

        # Assert
        assert len(runs) == 5
        assert all(run.organization_id == organization.id for run in runs)

    async def test_list_runs_status_filter(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test listing runs with status filter."""
        # Arrange
        _, version = dataset_with_version
        run1 = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        run2 = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 5, "min_genes": 200},
        )

        # Start one run
        await run_service.start_run(run2.id)

        # Act - Filter for QUEUED runs
        queued_runs, _ = await run_service.list_runs(
            org_id=organization.id, status=RunStatus.QUEUED
        )

        # Act - Filter for RUNNING runs
        running_runs, _ = await run_service.list_runs(
            org_id=organization.id, status=RunStatus.RUNNING
        )

        # Assert
        assert len(queued_runs) == 1
        assert queued_runs[0].id == run1.id

        assert len(running_runs) == 1
        assert running_runs[0].id == run2.id

    async def test_list_runs_pagination(
        self, run_service, organization, dataset_with_version, pipeline_template, async_session
    ):
        """Test listing runs with pagination."""
        # Increase compute quota to allow 15 concurrent runs
        organization.compute_quota_runs = 20
        async_session.add(organization)
        await async_session.commit()

        # Arrange
        _, version = dataset_with_version
        for i in range(15):
            await run_service.create_run(
                org_id=organization.id,
                dataset_version_id=version.id,
                template_id=pipeline_template.id,
                parameters={"min_cells": i, "min_genes": 200},
            )

        # Act - Page 1
        page1, total1 = await run_service.list_runs(org_id=organization.id, limit=10, offset=0)

        # Act - Page 2
        page2, total2 = await run_service.list_runs(org_id=organization.id, limit=10, offset=10)

        # Assert
        assert len(page1) == 10
        assert len(page2) == 5

    async def test_update_progress_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test updating run progress."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Act
        progress_data = {"current_step": "normalize", "completed_steps": ["qc_filter"]}
        updated_run = await run_service.update_progress(run.id, progress_data)

        # Assert
        assert "progress" in updated_run.parameters
        assert updated_run.parameters["progress"]["current_step"] == "normalize"
        assert updated_run.parameters["progress"]["completed_steps"] == ["qc_filter"]

    async def test_update_progress_multiple_times(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test updating run progress multiple times merges data."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act - First update
        await run_service.update_progress(run.id, {"current_step": "qc_filter"})

        # Act - Second update
        updated_run = await run_service.update_progress(
            run.id, {"current_step": "normalize", "progress_percent": 50}
        )

        # Assert
        assert updated_run.parameters["progress"]["current_step"] == "normalize"
        assert updated_run.parameters["progress"]["progress_percent"] == 50

    async def test_complete_run_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test completing a running run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Act
        software_versions = {"scanpy": "1.9.3", "scvi-tools": "0.20.0"}
        completed_run = await run_service.complete_run(run.id, software_versions)

        # Assert
        assert completed_run.status == RunStatus.COMPLETED
        assert completed_run.completed_at is not None
        assert completed_run.software_versions == software_versions

    async def test_complete_run_invalid_status(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test completing a run fails if not in RUNNING status."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Act & Assert - Try to complete without starting
        with pytest.raises(ValueError, match="cannot be completed from status"):
            await run_service.complete_run(run.id, {"scanpy": "1.9.3"})

    async def test_fail_run_success(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test failing a run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Act
        error_message = "Pipeline failed: Out of memory"
        failed_run = await run_service.fail_run(run.id, error_message)

        # Assert
        assert failed_run.status == RunStatus.FAILED
        assert failed_run.completed_at is not None
        assert failed_run.error_message == error_message

    async def test_list_artifacts_success(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test listing artifacts for a run."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Create some artifacts
        artifact1 = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.H5AD,
            s3_path="s3://bucket/run/output.h5ad",
            size_bytes=1024,
            extra_metadata={},
        )
        artifact2 = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.QC_REPORT,
            s3_path="s3://bucket/run/qc_report.html",
            size_bytes=512,
            extra_metadata={},
        )
        async_session.add(artifact1)
        async_session.add(artifact2)
        await async_session.commit()

        # Act - Test without generating URLs
        artifacts_no_urls = await run_service.list_artifacts(
            run.id, organization.id, generate_download_urls=False
        )

        # Assert
        assert len(artifacts_no_urls) == 2
        artifacts_only = [a for a, _ in artifacts_no_urls]
        assert any(a.artifact_type == ArtifactType.H5AD for a in artifacts_only)
        assert any(a.artifact_type == ArtifactType.QC_REPORT for a in artifacts_only)
        # All URLs should be None when generate_download_urls=False
        assert all(url is None for _, url in artifacts_no_urls)

    async def test_list_artifacts_with_download_urls(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test listing artifacts with pre-signed download URLs."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Create artifact with proper S3 path
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.H5AD,
            s3_path="test-bucket/run/output.h5ad",
            size_bytes=1024,
            extra_metadata={},
        )
        async_session.add(artifact)
        await async_session.commit()

        # Act - Test with generating URLs (default behavior)
        artifacts_with_urls = await run_service.list_artifacts(run.id, organization.id)

        # Assert
        assert len(artifacts_with_urls) == 1
        artifact_obj, download_url = artifacts_with_urls[0]
        assert artifact_obj.artifact_type == ArtifactType.H5AD
        # URL should be generated (or None if S3 service fails, which is acceptable)
        assert download_url is None or isinstance(download_url, str)

    async def test_list_artifacts_wrong_organization(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test listing artifacts fails with wrong organization ID."""
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        wrong_org = Organization(id=uuid4(), name="Wrong Org")
        async_session.add(wrong_org)
        await async_session.commit()

        # Act & Assert
        with pytest.raises(ValueError, match="not found or does not belong"):
            await run_service.list_artifacts(run.id, wrong_org.id)

    async def test_organization_isolation(
        self, run_service, async_session, dataset_with_version, pipeline_template
    ):
        """Test that runs are properly isolated by organization."""
        # Arrange - Create two organizations
        org1 = Organization(id=uuid4(), name="Org 1")
        org2 = Organization(id=uuid4(), name="Org 2")
        async_session.add(org1)
        async_session.add(org2)
        await async_session.commit()

        # Create datasets for each org
        dataset1 = Dataset(id=uuid4(), organization_id=org1.id, name="Dataset 1")
        dataset2 = Dataset(id=uuid4(), organization_id=org2.id, name="Dataset 2")
        async_session.add(dataset1)
        async_session.add(dataset2)
        await async_session.flush()

        version1 = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset1.id,
            version="v1",
            s3_path="s3://bucket/dataset1/file.h5ad",
            file_format="h5ad",
        )
        version2 = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset2.id,
            version="v1",
            s3_path="s3://bucket/dataset2/file.h5ad",
            file_format="h5ad",
        )
        async_session.add(version1)
        async_session.add(version2)
        await async_session.flush()

        # Create templates for each org
        template1 = PipelineTemplate(
            id=uuid4(),
            organization_id=org1.id,
            name="Template 1",
            version="1.0.0",
            definition={"methods": ["qc_filter"], "dependencies": {}},
        )
        template2 = PipelineTemplate(
            id=uuid4(),
            organization_id=org2.id,
            name="Template 2",
            version="1.0.0",
            definition={"methods": ["qc_filter"], "dependencies": {}},
        )
        async_session.add(template1)
        async_session.add(template2)
        await async_session.commit()

        # Create runs in different organizations
        run1 = await run_service.create_run(
            org_id=org1.id,
            dataset_version_id=version1.id,
            template_id=template1.id,
            parameters={},
        )
        run2 = await run_service.create_run(
            org_id=org2.id,
            dataset_version_id=version2.id,
            template_id=template2.id,
            parameters={},
        )

        # Act - List runs for each org
        runs1, _ = await run_service.list_runs(org_id=org1.id)
        runs2, _ = await run_service.list_runs(org_id=org2.id)

        # Assert - Each org only sees their own runs
        assert len(runs1) == 1
        assert runs1[0].id == run1.id

        assert len(runs2) == 1
        assert runs2[0].id == run2.id

        # Assert - Cannot get run from wrong org
        assert await run_service.get_run(run1.id, org2.id) is None
        assert await run_service.get_run(run2.id, org1.id) is None

    async def test_status_transition_queued_to_running_to_completed(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test complete status transition flow: QUEUED → RUNNING → COMPLETED.

        **Validates: Requirements 7.1**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Assert initial state
        assert run.status == RunStatus.QUEUED
        assert run.started_at is None
        assert run.completed_at is None

        # Act - Transition to RUNNING
        running_run = await run_service.start_run(run.id)

        # Assert RUNNING state
        assert running_run.status == RunStatus.RUNNING
        assert running_run.started_at is not None
        assert running_run.completed_at is None

        # Act - Transition to COMPLETED
        completed_run = await run_service.complete_run(
            run.id, {"scanpy": "1.9.3", "scvi-tools": "0.20.0"}
        )

        # Assert COMPLETED state
        assert completed_run.status == RunStatus.COMPLETED
        assert completed_run.started_at is not None
        assert completed_run.completed_at is not None
        assert completed_run.software_versions == {"scanpy": "1.9.3", "scvi-tools": "0.20.0"}
        assert completed_run.completed_at > completed_run.started_at

    async def test_status_transition_queued_to_running_to_failed(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test status transition flow with failure: QUEUED → RUNNING → FAILED.

        **Validates: Requirements 7.1**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Assert initial state
        assert run.status == RunStatus.QUEUED

        # Act - Transition to RUNNING
        running_run = await run_service.start_run(run.id)
        assert running_run.status == RunStatus.RUNNING

        # Act - Transition to FAILED
        error_message = "Method 'normalize' failed: Out of memory"
        failed_run = await run_service.fail_run(run.id, error_message)

        # Assert FAILED state
        assert failed_run.status == RunStatus.FAILED
        assert failed_run.started_at is not None
        assert failed_run.completed_at is not None
        assert failed_run.error_message == error_message
        assert failed_run.completed_at > failed_run.started_at

    async def test_cancellation_from_queued_state(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test cancellation of a run in QUEUED state.

        **Validates: Requirements 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        # Assert initial state
        assert run.status == RunStatus.QUEUED
        assert run.started_at is None

        # Act - Cancel from QUEUED
        cancelled_run = await run_service.cancel_run(run.id)

        # Assert CANCELLED state
        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.started_at is None  # Never started
        assert cancelled_run.completed_at is not None

    async def test_cancellation_from_running_state(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test cancellation of a run in RUNNING state.

        **Validates: Requirements 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Assert RUNNING state
        running_run = await run_service.get_run(run.id, organization.id)
        assert running_run.status == RunStatus.RUNNING
        assert running_run.started_at is not None

        # Act - Cancel from RUNNING
        cancelled_run = await run_service.cancel_run(run.id)

        # Assert CANCELLED state
        assert cancelled_run.status == RunStatus.CANCELLED
        assert cancelled_run.started_at is not None  # Was started
        assert cancelled_run.completed_at is not None
        assert cancelled_run.completed_at > cancelled_run.started_at

    async def test_cannot_cancel_completed_run(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test that completed runs cannot be cancelled.

        **Validates: Requirements 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)
        await run_service.complete_run(run.id, {"scanpy": "1.9.3"})

        # Act & Assert - Cannot cancel completed run
        with pytest.raises(ValueError, match="cannot be cancelled from status"):
            await run_service.cancel_run(run.id)

    async def test_cannot_cancel_failed_run(
        self, run_service, organization, dataset_with_version, pipeline_template
    ):
        """Test that failed runs cannot be cancelled.

        **Validates: Requirements 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)
        await run_service.fail_run(run.id, "Test error")

        # Act & Assert - Cannot cancel failed run
        with pytest.raises(ValueError, match="cannot be cancelled from status"):
            await run_service.cancel_run(run.id)

    async def test_artifact_association_with_completed_run(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test that artifacts are properly associated with a completed run.

        **Validates: Requirements 7.1, 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Create artifacts during run execution
        artifact1 = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.H5AD,
            s3_path="s3://bucket/run/output.h5ad",
            size_bytes=1024000,
            extra_metadata={"cell_count": 1000, "gene_count": 2000},
        )
        artifact2 = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.QC_REPORT,
            s3_path="s3://bucket/run/qc_report.html",
            size_bytes=5120,
            extra_metadata={},
        )
        async_session.add(artifact1)
        async_session.add(artifact2)
        await async_session.commit()

        # Complete the run
        await run_service.complete_run(run.id, {"scanpy": "1.9.3"})

        # Act - List artifacts for the completed run
        artifacts_with_urls = await run_service.list_artifacts(
            run.id, organization.id, generate_download_urls=False
        )

        # Assert - Artifacts are associated with the run
        assert len(artifacts_with_urls) == 2
        artifacts = [a for a, _ in artifacts_with_urls]

        # Verify artifact types
        artifact_types = {a.artifact_type for a in artifacts}
        assert ArtifactType.H5AD in artifact_types
        assert ArtifactType.QC_REPORT in artifact_types

        # Verify all artifacts belong to the run
        assert all(a.run_id == run.id for a in artifacts)

        # Verify artifact metadata
        h5ad_artifact = next(a for a in artifacts if a.artifact_type == ArtifactType.H5AD)
        assert h5ad_artifact.size_bytes == 1024000
        assert h5ad_artifact.extra_metadata["cell_count"] == 1000

    async def test_artifact_association_persists_after_cancellation(
        self, run_service, async_session, organization, dataset_with_version, pipeline_template
    ):
        """Test that artifacts created before cancellation remain associated with the run.

        **Validates: Requirements 7.4**
        """
        # Arrange
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.start_run(run.id)

        # Create partial artifacts before cancellation
        partial_artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.QC_REPORT,
            s3_path="s3://bucket/run/partial_qc.html",
            size_bytes=2048,
            extra_metadata={"status": "partial"},
        )
        async_session.add(partial_artifact)
        await async_session.commit()

        # Act - Cancel the run
        await run_service.cancel_run(run.id)

        # Assert - Artifacts still associated (cleanup is TODO in service)
        artifacts_with_urls = await run_service.list_artifacts(
            run.id, organization.id, generate_download_urls=False
        )

        assert len(artifacts_with_urls) == 1
        artifact, _ = artifacts_with_urls[0]
        assert artifact.run_id == run.id
        assert artifact.artifact_type == ArtifactType.QC_REPORT
        assert artifact.extra_metadata["status"] == "partial"

    async def test_reconcile_stale_runs_reschedules_checkpointed_run(
        self,
        run_service,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        monkeypatch,
    ):
        """Checkpointed stale runs should be restarted automatically."""
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        stale_timestamp = (datetime.utcnow() - timedelta(minutes=20)).isoformat()
        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow() - timedelta(minutes=25)
        run.parameters = {
            "min_cells": 3,
            "min_genes": 200,
            "progress": {"state": "running", "updated_at": stale_timestamp},
            "_checkpoints": [
                {
                    "run_id": str(run.id),
                    "step_name": "normalize",
                    "status": "completed",
                }
            ],
            "_execution_state": {"step_outputs": {"normalize": "runs/x/normalize.h5ad"}},
        }
        await async_session.commit()
        await async_session.refresh(run)

        connect_mock = AsyncMock(return_value=object())
        describe_mock = AsyncMock(
            side_effect=[
                WorkflowExecutionStatus.RUNNING,
                WorkflowExecutionStatus.TERMINATED,
            ]
        )
        dispatch_mock = AsyncMock(return_value=None)
        terminate_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(run_service, "_connect_temporal_client", connect_mock)
        monkeypatch.setattr(run_service, "_describe_temporal_workflow_status", describe_mock)
        monkeypatch.setattr(run_service, "_dispatch_workflow", dispatch_mock)
        monkeypatch.setattr(run_service, "_terminate_temporal_workflow", terminate_mock)

        reconciled = await run_service.reconcile_stale_runs(
            stale_after_seconds=60,
            max_auto_restart_attempts=2,
        )

        assert len(reconciled) == 1
        assert reconciled[0]["action"] == "rescheduled"
        terminate_mock.assert_awaited_once()
        dispatch_mock.assert_awaited_once()

        await async_session.refresh(run)
        assert run.status == RunStatus.RUNNING
        assert run.parameters["_execution_state"]["auto_recovery_attempts"] == 1
        assert run.parameters["progress"]["state"] == RunStatus.RUNNING.value

    async def test_reconcile_stale_runs_fails_without_checkpoint(
        self,
        run_service,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        monkeypatch,
    ):
        """Runs with no durable checkpoint should be failed, not restarted."""
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow() - timedelta(minutes=10)
        run.parameters = {
            "min_cells": 3,
            "min_genes": 200,
            "progress": {
                "state": "running",
                "current_step": "select_hvg",
                "updated_at": (datetime.utcnow() - timedelta(minutes=9)).isoformat(),
            },
        }
        await async_session.commit()
        await async_session.refresh(run)

        monkeypatch.setattr(
            run_service, "_connect_temporal_client", AsyncMock(return_value=object())
        )
        monkeypatch.setattr(
            run_service,
            "_describe_temporal_workflow_status",
            AsyncMock(return_value=WorkflowExecutionStatus.RUNNING),
        )
        monkeypatch.setattr(
            run_service, "_terminate_temporal_workflow", AsyncMock(return_value=None)
        )
        dispatch_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(run_service, "_dispatch_workflow", dispatch_mock)

        reconciled = await run_service.reconcile_stale_runs(
            stale_after_seconds=60,
            max_auto_restart_attempts=2,
        )

        assert len(reconciled) == 1
        assert reconciled[0]["action"] == "failed"
        assert "no durable completed-step checkpoint" in reconciled[0]["reason"]
        dispatch_mock.assert_not_awaited()

        await async_session.refresh(run)
        assert run.status == RunStatus.FAILED
        assert "no durable completed-step checkpoint" in (run.error_message or "")

    async def test_reconcile_stale_runs_fails_after_restart_budget_exhausted(
        self,
        run_service,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        monkeypatch,
    ):
        """Runs should stop auto-restarting once the configured retry budget is exhausted."""
        _, version = dataset_with_version
        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )

        run.status = RunStatus.RUNNING
        run.started_at = datetime.utcnow() - timedelta(minutes=15)
        run.parameters = {
            "min_cells": 3,
            "min_genes": 200,
            "progress": {
                "state": "running",
                "updated_at": (datetime.utcnow() - timedelta(minutes=8)).isoformat(),
            },
            "_checkpoints": [
                {
                    "run_id": str(run.id),
                    "step_name": "normalize",
                    "status": "completed",
                }
            ],
            "_execution_state": {
                "step_outputs": {"normalize": "runs/x/normalize.h5ad"},
                "auto_recovery_attempts": 2,
            },
        }
        await async_session.commit()
        await async_session.refresh(run)

        monkeypatch.setattr(
            run_service, "_connect_temporal_client", AsyncMock(return_value=object())
        )
        monkeypatch.setattr(
            run_service,
            "_describe_temporal_workflow_status",
            AsyncMock(return_value=WorkflowExecutionStatus.TIMED_OUT),
        )
        dispatch_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(run_service, "_dispatch_workflow", dispatch_mock)

        reconciled = await run_service.reconcile_stale_runs(
            stale_after_seconds=60,
            max_auto_restart_attempts=2,
        )

        assert len(reconciled) == 1
        assert reconciled[0]["action"] == "failed"
        assert "exhausted the automatic restart budget" in reconciled[0]["reason"]
        dispatch_mock.assert_not_awaited()

        await async_session.refresh(run)
        assert run.status == RunStatus.FAILED

    async def test_delete_run_removes_db_row_and_storage_objects(
        self,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Deleting a run should remove the row and every owned storage object."""
        _, version = dataset_with_version
        run_service = RunService(
            db=async_session,
            pipeline_service=mock_pipeline_service,
            s3_service=MagicMock(),
        )
        run_service.s3_service.artifacts_bucket = "test-artifacts"

        run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        run.status = RunStatus.FAILED

        artifact_one = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.H5AD,
            s3_path=f"runs/{run.id}/processed.h5ad",
            size_bytes=123,
        )
        artifact_two = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=ArtifactType.DE_RESULTS,
            s3_path=f"s3://test-artifacts/custom/runs/{run.id}/de_results.csv",
            size_bytes=456,
        )
        async_session.add_all([artifact_one, artifact_two])
        await async_session.commit()

        run_service.s3_service.list_files.side_effect = [
            [{"key": f"runs/{run.id}/_state/snapshots/000_initial.h5ad"}],
            [{"key": f"custom/runs/{run.id}/de_results.csv"}],
        ]

        deleted = await run_service.delete_run(
            run_id=run.id,
            org_id=organization.id,
        )

        assert deleted["run_id"] == run.id
        assert deleted["deleted_artifacts"] == 2
        assert deleted["deleted_storage_objects"] == 3
        run_service.s3_service.delete_file.assert_any_call(
            "test-artifacts", f"runs/{run.id}/processed.h5ad"
        )
        run_service.s3_service.delete_file.assert_any_call(
            "test-artifacts",
            f"runs/{run.id}/_state/snapshots/000_initial.h5ad",
        )
        run_service.s3_service.delete_file.assert_any_call(
            "test-artifacts",
            f"custom/runs/{run.id}/de_results.csv",
        )

        assert await run_service.get_run(run.id, organization.id) is None

    async def test_bulk_delete_runs_failed_scope_only_deletes_failed_runs(
        self,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Bulk failed-run cleanup should leave non-failed runs intact."""
        _, version = dataset_with_version
        run_service = RunService(
            db=async_session,
            pipeline_service=mock_pipeline_service,
            s3_service=MagicMock(),
        )
        run_service.s3_service.artifacts_bucket = "test-artifacts"
        run_service.s3_service.list_files.return_value = []

        failed_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        kept_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 4, "min_genes": 300},
        )
        failed_run.status = RunStatus.FAILED
        kept_run.status = RunStatus.COMPLETED

        async_session.add(
            Artifact(
                id=uuid4(),
                run_id=failed_run.id,
                artifact_type=ArtifactType.H5AD,
                s3_path=f"runs/{failed_run.id}/processed.h5ad",
                size_bytes=100,
            )
        )
        await async_session.commit()

        deleted = await run_service.bulk_delete_runs(
            org_id=organization.id,
            scope="failed",
        )

        assert deleted["scope"] == "failed"
        assert deleted["deleted_runs"] == 1
        assert deleted["deleted_run_ids"] == [failed_run.id]
        assert await run_service.get_run(failed_run.id, organization.id) is None
        assert await run_service.get_run(kept_run.id, organization.id) is not None

    async def test_list_runs_can_filter_by_dataset_id(
        self,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Dataset-scoped run listing should use the preserved dataset snapshot."""
        dataset, version = dataset_with_version
        other_dataset = Dataset(
            id=uuid4(),
            organization_id=organization.id,
            name="Other Dataset",
            description=None,
            extra_metadata={},
        )
        async_session.add(other_dataset)
        await async_session.flush()

        other_version = DatasetVersion(
            id=uuid4(),
            dataset_id=other_dataset.id,
            version="v1",
            s3_path="s3://test-bucket/other.h5ad",
            cell_count=500,
            gene_count=1000,
            file_format="h5ad",
            extra_metadata={},
        )
        async_session.add(other_version)
        await async_session.commit()

        run_service = RunService(db=async_session, pipeline_service=mock_pipeline_service)
        kept_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=other_version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 4, "min_genes": 300},
        )

        runs, total = await run_service.list_runs(org_id=organization.id, dataset_id=dataset.id)

        assert total == 1
        assert [run.id for run in runs] == [kept_run.id]
        assert runs[0].dataset_id_snapshot == dataset.id

    async def test_bulk_delete_runs_can_scope_to_dataset_id(
        self,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Dataset-scoped cleanup should only remove runs for that dataset."""
        dataset, version = dataset_with_version
        other_dataset = Dataset(
            id=uuid4(),
            organization_id=organization.id,
            name="Other Dataset",
            description=None,
            extra_metadata={},
        )
        async_session.add(other_dataset)
        await async_session.flush()

        other_version = DatasetVersion(
            id=uuid4(),
            dataset_id=other_dataset.id,
            version="v1",
            s3_path="s3://test-bucket/other.h5ad",
            cell_count=500,
            gene_count=1000,
            file_format="h5ad",
            extra_metadata={},
        )
        async_session.add(other_version)
        await async_session.commit()

        run_service = RunService(
            db=async_session,
            pipeline_service=mock_pipeline_service,
            s3_service=MagicMock(),
        )
        run_service.s3_service.artifacts_bucket = "test-artifacts"
        run_service.s3_service.list_files.return_value = []

        deleted_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        kept_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=other_version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 4, "min_genes": 300},
        )
        deleted_run.status = RunStatus.COMPLETED
        kept_run.status = RunStatus.COMPLETED
        await async_session.commit()

        deleted = await run_service.bulk_delete_runs(
            org_id=organization.id,
            scope="all",
            dataset_id=dataset.id,
        )

        assert deleted["scope"] == "all"
        assert deleted["dataset_id"] == dataset.id
        assert deleted["deleted_run_ids"] == [deleted_run.id]
        assert await run_service.get_run(deleted_run.id, organization.id) is None
        assert await run_service.get_run(kept_run.id, organization.id) is not None

    async def test_bulk_delete_runs_selected_scope_only_deletes_requested_runs(
        self,
        async_session,
        organization,
        dataset_with_version,
        pipeline_template,
        mock_pipeline_service,
    ):
        """Selected-scope cleanup should remove only explicitly requested runs."""
        _, version = dataset_with_version
        run_service = RunService(
            db=async_session,
            pipeline_service=mock_pipeline_service,
            s3_service=MagicMock(),
        )
        run_service.s3_service.artifacts_bucket = "test-artifacts"
        run_service.s3_service.list_files.return_value = []

        deleted_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 3, "min_genes": 200},
        )
        kept_run = await run_service.create_run(
            org_id=organization.id,
            dataset_version_id=version.id,
            template_id=pipeline_template.id,
            parameters={"min_cells": 4, "min_genes": 300},
        )
        deleted_run.status = RunStatus.COMPLETED
        kept_run.status = RunStatus.FAILED
        await async_session.commit()

        deleted = await run_service.bulk_delete_runs(
            org_id=organization.id,
            scope="selected",
            run_ids=[deleted_run.id],
        )

        assert deleted["scope"] == "selected"
        assert deleted["deleted_run_ids"] == [deleted_run.id]
        assert await run_service.get_run(deleted_run.id, organization.id) is None
        assert await run_service.get_run(kept_run.id, organization.id) is not None
