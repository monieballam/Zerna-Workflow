"""Property-based tests for export completeness.

**Validates: Requirements 9.1**
"""

import json
import shutil
import tempfile
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import anndata as ad
import pytest
import pytest_asyncio
from zerna_contracts.enums import ArtifactType, RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base, Organization
from apps.api.models.annotation import AnnotationRevision
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run
from apps.api.services.export_service import ExportService


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
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()
        return session


def _make_mock_s3_service(artifacts_bucket: str = "test-artifacts-bucket") -> MagicMock:
    s3 = MagicMock()
    s3.artifacts_bucket = artifacts_bucket
    s3.upload_file = MagicMock(return_value={"etag": "abc", "size": 100, "checksum": "xyz"})
    s3.s3_client = MagicMock()
    return s3


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

run_params_strategy = st.dictionaries(
    keys=safe_text,
    values=safe_text,
    min_size=0,
    max_size=5,
)

random_seed_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1))

num_annotation_revisions_strategy = st.integers(min_value=0, max_value=3)

artifact_types_strategy = st.lists(
    st.sampled_from(list(ArtifactType)),
    min_size=0,
    max_size=3,
)


async def _create_run_with_data(
    session: AsyncSession,
    parameters: dict,
    random_seed,
    num_annotation_revisions: int,
    artifact_types: list,
) -> tuple[Run, Organization]:
    """Helper to create a run with optional annotations and artifacts in the DB."""
    org = Organization(
        id=uuid4(),
        name="Test Org",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    session.add(org)
    await session.flush()

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

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name=f"template-{uuid4()}",
        version=f"v{uuid4().hex[:8]}",
        definition={"steps": ["qc", "normalize"]},
    )
    session.add(template)
    await session.flush()

    from apps.api.models.organization import User

    user = User(id=uuid4(), email=f"user-{uuid4()}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters=parameters,
        random_seed=random_seed,
        started_at=datetime(2024, 1, 1, 10, 0),
        completed_at=datetime(2024, 1, 1, 11, 0),
        created_at=datetime(2024, 1, 1, 9, 0),
    )
    session.add(run)
    await session.flush()

    # Create annotation revisions
    for i in range(num_annotation_revisions):
        rev = AnnotationRevision(
            id=uuid4(),
            run_id=run.id,
            revision_number=i + 1,
            annotations={f"cell_{j}": {"cell_type": f"type_{j}"} for j in range(3)},
            method=f"method_{i}",
            created_by=user.id,
            created_at=datetime(2024, 1, 1, 12 + i, 0),
        )
        session.add(rev)

    # Create artifacts (non-H5AD types to avoid S3 download attempts)
    for i, artifact_type in enumerate(artifact_types):
        if artifact_type == ArtifactType.H5AD:
            # Skip H5AD artifacts to avoid S3 download in tests
            continue
        artifact = Artifact(
            id=uuid4(),
            run_id=run.id,
            artifact_type=artifact_type,
            s3_path=f"{org.id}/runs/{run.id}/{artifact_type.value}/artifact_{i}.dat",
            size_bytes=1024 * (i + 1),
        )
        session.add(artifact)

    await session.commit()
    return run, org


@pytest.mark.property
class TestExportCompleteness:
    """Property 19: Export Completeness

    For any run with any combination of annotations and artifacts, the exported
    h5ad file must contain zerna_run_metadata in uns with required keys, and
    zerna_artifacts in uns.
    """

    @pytest.mark.asyncio
    @given(
        parameters=run_params_strategy,
        random_seed=random_seed_strategy,
        num_annotation_revisions=num_annotation_revisions_strategy,
        artifact_types=artifact_types_strategy,
    )
    @settings(max_examples=50)
    async def test_property_export_always_contains_run_metadata(
        self,
        async_engine,
        parameters,
        random_seed,
        num_annotation_revisions,
        artifact_types,
    ):
        """Property: For any run, exported h5ad always has zerna_run_metadata with correct run_id and org_id.

        **Validates: Requirements 9.1**
        """
        session = await get_clean_session(async_engine)

        run, org = await _create_run_with_data(
            session,
            parameters=parameters,
            random_seed=random_seed,
            num_annotation_revisions=num_annotation_revisions,
            artifact_types=artifact_types,
        )

        mock_s3 = _make_mock_s3_service()
        captured_files = []

        def capture_upload(file_path, bucket, s3_path, content_type=None):
            with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
                dest = f.name
            shutil.copy2(str(file_path), dest)
            captured_files.append(dest)
            return {"etag": "abc", "size": 100, "checksum": "xyz"}

        mock_s3.upload_file.side_effect = capture_upload

        svc = ExportService(db=session, s3_service=mock_s3)
        s3_path = await svc.export_h5ad(run.id, org.id)

        # Property: export always succeeds and returns a valid S3 path
        assert s3_path == f"{org.id}/exports/{run.id}/export.h5ad"
        assert len(captured_files) == 1

        # Property: exported h5ad loads successfully (round-trip)
        exported = ad.read_h5ad(captured_files[0])

        # Property: zerna_run_metadata is always present in uns
        assert "zerna_run_metadata" in exported.uns, (
            "zerna_run_metadata must always be present in uns"
        )

        meta = exported.uns["zerna_run_metadata"]

        # Property: required keys are always present
        required_keys = {"run_id", "org_id", "exported_at"}
        for key in required_keys:
            assert key in meta, f"Required key '{key}' missing from zerna_run_metadata"

        # Property: run_id in metadata matches the actual run_id
        assert meta["run_id"] == str(run.id), (
            f"run_id mismatch: expected {run.id}, got {meta['run_id']}"
        )

        # Property: org_id in metadata matches the actual org_id
        assert meta["org_id"] == str(org.id), (
            f"org_id mismatch: expected {org.id}, got {meta['org_id']}"
        )

        # Property: zerna_artifacts is always present in uns (even if empty)
        assert "zerna_artifacts" in exported.uns, "zerna_artifacts must always be present in uns"

        # Property: n_obs >= 0 (can be 0 for runs with no h5ad artifact)
        assert exported.n_obs >= 0

        await session.close()

    @pytest.mark.asyncio
    @given(
        parameters=run_params_strategy,
        random_seed=random_seed_strategy,
        num_annotation_revisions=num_annotation_revisions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_export_metadata_matches_run(
        self,
        async_engine,
        parameters,
        random_seed,
        num_annotation_revisions,
    ):
        """Property: For any run with varying parameters and seeds, the metadata in the exported h5ad matches the run's actual data.

        **Validates: Requirements 9.1**
        """
        session = await get_clean_session(async_engine)

        run, org = await _create_run_with_data(
            session,
            parameters=parameters,
            random_seed=random_seed,
            num_annotation_revisions=num_annotation_revisions,
            artifact_types=[],
        )

        mock_s3 = _make_mock_s3_service()
        captured_files = []

        def capture_upload(file_path, bucket, s3_path, content_type=None):
            with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as f:
                dest = f.name
            shutil.copy2(str(file_path), dest)
            captured_files.append(dest)
            return {"etag": "abc", "size": 100, "checksum": "xyz"}

        mock_s3.upload_file.side_effect = capture_upload

        svc = ExportService(db=session, s3_service=mock_s3)
        await svc.export_h5ad(run.id, org.id)

        assert len(captured_files) == 1

        # Property: exported h5ad loads successfully (round-trip)
        exported = ad.read_h5ad(captured_files[0])
        meta = exported.uns["zerna_run_metadata"]

        # Property: run_id matches
        assert meta["run_id"] == str(run.id), (
            f"run_id mismatch: expected {run.id}, got {meta['run_id']}"
        )

        # Property: org_id matches
        assert meta["org_id"] == str(org.id), (
            f"org_id mismatch: expected {org.id}, got {meta['org_id']}"
        )

        # Property: parameters are preserved faithfully
        assert meta["parameters"] == parameters, (
            f"parameters mismatch: expected {parameters}, got {meta['parameters']}"
        )

        # Property: random_seed is preserved (stored as -1 when None)
        expected_seed = random_seed if random_seed is not None else -1
        assert meta["random_seed"] == expected_seed, (
            f"random_seed mismatch: expected {expected_seed}, got {meta['random_seed']}"
        )

        # Property: exported_at is a non-empty ISO timestamp
        assert meta["exported_at"], "exported_at must be a non-empty string"

        # Property: annotation revisions are recorded when present
        if num_annotation_revisions > 0:
            assert "zerna_annotation_revisions" in exported.uns, (
                "zerna_annotation_revisions must be present when annotations exist"
            )
            revisions = json.loads(exported.uns["zerna_annotation_revisions"])
            assert len(revisions) == num_annotation_revisions, (
                f"Expected {num_annotation_revisions} revisions, got {len(revisions)}"
            )

        await session.close()
