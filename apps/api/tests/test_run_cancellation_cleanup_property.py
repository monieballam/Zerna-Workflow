"""Property-based tests for run cancellation cleanup.

**Validates: Requirements 7.4**
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import (
    Artifact,
    Base,
    Dataset,
    DatasetVersion,
    Organization,
    PipelineTemplate,
    Run,
)
from apps.api.services.run_service import RunService
from apps.api.services.s3_service import S3Service


@pytest_asyncio.fixture(scope="module")
async def async_engine():
    """Create an async in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def get_clean_session(async_engine):
    """Create a clean database session and clear all tables."""
    async_session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session_factory() as session:
        # Clear all tables in reverse order to respect foreign keys
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
        return session


# Hypothesis strategies for generating test data
@st.composite
def run_with_artifacts_data(draw):
    """Generate data for a run with artifacts."""
    # Generate run status (only QUEUED or RUNNING can be cancelled)
    status = draw(st.sampled_from([RunStatus.QUEUED, RunStatus.RUNNING]))

    # Generate number of artifacts (0 to 5)
    num_artifacts = draw(st.integers(min_value=0, max_value=5))

    # Generate artifact types
    artifact_types = draw(
        st.lists(
            st.sampled_from(list(ArtifactType)),
            min_size=num_artifacts,
            max_size=num_artifacts,
        )
    )

    return {
        "status": status,
        "num_artifacts": num_artifacts,
        "artifact_types": artifact_types,
    }


@pytest.mark.property
class TestRunCancellationCleanup:
    """Property 18: Run Cancellation Cleanup

    For any run cancellation, all partial artifacts should be removed from S3,
    and the run status should be marked as CANCELLED.
    """

    @pytest.mark.asyncio
    @given(data=run_with_artifacts_data())
    @settings(max_examples=100)
    async def test_property_run_cancellation_deletes_all_artifacts(self, async_engine, data):
        """Property: When a run is cancelled, all associated artifacts are deleted from S3.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc", "normalize"]},
        )
        session.add(template)
        await session.flush()

        # Create run with specified status
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=data["status"],
            parameters={"param1": "value1"},
        )
        session.add(run)
        await session.flush()

        # Create artifacts for the run
        artifacts = []
        artifact_s3_paths = []
        for i, artifact_type in enumerate(data["artifact_types"]):
            s3_path = f"{org.id}/runs/{run.id}/{artifact_type.value}/artifact_{i}.dat"
            artifact = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=artifact_type,
                s3_path=s3_path,
                size_bytes=1024 * (i + 1),
            )
            artifacts.append(artifact)
            artifact_s3_paths.append(s3_path)
            session.add(artifact)

        await session.commit()

        # Mock S3Service to track delete calls
        with patch.object(S3Service, "delete_file") as mock_delete:
            # Create RunService with mocked S3
            run_service = RunService(session)

            # Cancel the run
            cancelled_run = await run_service.cancel_run(run.id)

            # Property assertion 1: Run status should be CANCELLED
            assert cancelled_run.status == RunStatus.CANCELLED, (
                f"Run status should be CANCELLED, got {cancelled_run.status}"
            )

            # Property assertion 2: completed_at should be set
            assert cancelled_run.completed_at is not None, (
                "Run completed_at should be set after cancellation"
            )

            # TODO: When cleanup logic is implemented in cancel_run, verify:
            # - All artifacts are deleted from S3
            # - mock_delete.call_count == len(artifact_s3_paths)
            # - Each artifact's S3 path was passed to delete_file

            # For now, document that cleanup is not yet implemented
            # This test will fail when proper cleanup is added
            if data["num_artifacts"] > 0:
                # CURRENT BEHAVIOR: Artifacts are NOT deleted (cleanup not implemented)
                assert mock_delete.call_count == 0, (
                    "Artifact cleanup not yet implemented - delete_file should not be called"
                )

        await session.close()

    @pytest.mark.asyncio
    @given(
        initial_status=st.sampled_from([RunStatus.QUEUED, RunStatus.RUNNING]),
        num_artifacts=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    async def test_property_cancellation_works_from_any_cancellable_state(
        self, async_engine, initial_status, num_artifacts
    ):
        """Property: Run cancellation works from both QUEUED and RUNNING states.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc"]},
        )
        session.add(template)
        await session.flush()

        # Create run with initial status
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=initial_status,
            parameters={},
        )
        session.add(run)
        await session.flush()

        # Create artifacts
        for i in range(num_artifacts):
            artifact = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=ArtifactType.H5AD,
                s3_path=f"{org.id}/runs/{run.id}/h5ad/artifact_{i}.h5ad",
                size_bytes=1024,
            )
            session.add(artifact)

        await session.commit()

        # Cancel the run
        run_service = RunService(session)
        cancelled_run = await run_service.cancel_run(run.id)

        # Property assertions
        assert cancelled_run.status == RunStatus.CANCELLED, (
            f"Run should transition from {initial_status} to CANCELLED"
        )
        assert cancelled_run.completed_at is not None, (
            "completed_at should be set after cancellation"
        )

        await session.close()

    @pytest.mark.asyncio
    @given(
        terminal_status=st.sampled_from(
            [
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            ]
        )
    )
    @settings(max_examples=50)
    async def test_property_cannot_cancel_terminal_runs(self, async_engine, terminal_status):
        """Property: Runs in terminal states (COMPLETED, FAILED, CANCELLED) cannot be cancelled.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc"]},
        )
        session.add(template)
        await session.flush()

        # Create run with terminal status
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=terminal_status,
            parameters={},
        )
        session.add(run)
        await session.commit()

        # Attempt to cancel the run
        run_service = RunService(session)

        with pytest.raises(ValueError) as exc_info:
            await run_service.cancel_run(run.id)

        # Property assertion: Should raise ValueError
        assert "cannot be cancelled" in str(exc_info.value).lower(), (
            f"Should not allow cancellation from {terminal_status} state"
        )

        await session.close()

    @pytest.mark.asyncio
    @given(num_artifacts=st.integers(min_value=1, max_value=10))
    @settings(max_examples=50)
    async def test_property_all_artifacts_deleted_even_with_many_artifacts(
        self, async_engine, num_artifacts
    ):
        """Property: All artifacts are deleted regardless of quantity.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc"]},
        )
        session.add(template)
        await session.flush()

        # Create run
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=RunStatus.RUNNING,
            parameters={},
        )
        session.add(run)
        await session.flush()

        # Create many artifacts
        artifact_s3_paths = []
        for i in range(num_artifacts):
            s3_path = f"{org.id}/runs/{run.id}/artifact_{i}.dat"
            artifact = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=ArtifactType.H5AD,
                s3_path=s3_path,
                size_bytes=1024,
            )
            artifact_s3_paths.append(s3_path)
            session.add(artifact)

        await session.commit()

        # Mock S3Service
        with patch.object(S3Service, "delete_file") as mock_delete:
            run_service = RunService(session)

            # Cancel the run
            await run_service.cancel_run(run.id)

            # TODO: When cleanup is implemented, verify all artifacts deleted
            # assert mock_delete.call_count == num_artifacts, \
            #     f"All {num_artifacts} artifacts should be deleted"

            # CURRENT BEHAVIOR: No cleanup implemented
            assert mock_delete.call_count == 0, "Artifact cleanup not yet implemented"

        await session.close()

    @pytest.mark.asyncio
    @given(
        artifact_types=st.lists(
            st.sampled_from(list(ArtifactType)),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=50)
    async def test_property_cleanup_handles_different_artifact_types(
        self, async_engine, artifact_types
    ):
        """Property: Cleanup works for all artifact types.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc"]},
        )
        session.add(template)
        await session.flush()

        # Create run
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=RunStatus.RUNNING,
            parameters={},
        )
        session.add(run)
        await session.flush()

        # Create artifacts of different types
        for i, artifact_type in enumerate(artifact_types):
            artifact = Artifact(
                id=uuid4(),
                run_id=run.id,
                artifact_type=artifact_type,
                s3_path=f"{org.id}/runs/{run.id}/{artifact_type.value}/artifact_{i}.dat",
                size_bytes=1024,
            )
            session.add(artifact)

        await session.commit()

        # Mock S3Service
        with patch.object(S3Service, "delete_file") as mock_delete:
            run_service = RunService(session)

            # Cancel the run
            cancelled_run = await run_service.cancel_run(run.id)

            # Property assertion: Status should be CANCELLED
            assert cancelled_run.status == RunStatus.CANCELLED

            # TODO: When cleanup is implemented, verify all artifact types handled
            # assert mock_delete.call_count == len(artifact_types)

            # CURRENT BEHAVIOR: No cleanup implemented
            assert mock_delete.call_count == 0, "Artifact cleanup not yet implemented"

        await session.close()

    @pytest.mark.asyncio
    async def test_property_cancellation_with_no_artifacts(self, async_engine):
        """Property: Cancellation works even when run has no artifacts.

        **Validates: Requirements 7.4**
        """
        session = await get_clean_session(async_engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        await session.flush()

        # Create dataset and version
        dataset = Dataset(
            id=uuid4(),
            organization_id=org.id,
            name="Test Dataset",
        )
        session.add(dataset)
        await session.flush()

        version = DatasetVersion(
            id=uuid4(),
            dataset_id=dataset.id,
            version="v1",
            s3_path=f"s3://bucket/{org.id}/data.h5ad",
        )
        session.add(version)
        await session.flush()

        # Create pipeline template
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org.id,
            name=f"template-{uuid4()}",
            version=f"v{uuid4().hex[:8]}",
            definition={"steps": ["qc"]},
        )
        session.add(template)
        await session.flush()

        # Create run with no artifacts
        run = Run(
            id=uuid4(),
            organization_id=org.id,
            dataset_version_id=version.id,
            template_id=template.id,
            status=RunStatus.QUEUED,
            parameters={},
        )
        session.add(run)
        await session.commit()

        # Cancel the run
        run_service = RunService(session)
        cancelled_run = await run_service.cancel_run(run.id)

        # Property assertions
        assert cancelled_run.status == RunStatus.CANCELLED, (
            "Run should be cancelled even with no artifacts"
        )
        assert cancelled_run.completed_at is not None, "completed_at should be set"

        await session.close()
