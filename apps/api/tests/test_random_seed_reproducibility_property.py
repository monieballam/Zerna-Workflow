"""Property-based tests for random seed recording and reproducibility.

**Validates: Requirements 27.2, 27.5**
"""

import shutil
import tempfile
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import anndata as ad
import pytest
import pytest_asyncio
from zerna_contracts.enums import RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base, Organization
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.pipeline import PipelineTemplate, Run
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
    max_size=3,
)

software_versions_strategy = st.dictionaries(
    keys=safe_text,
    values=safe_text,
    min_size=0,
    max_size=3,
)

# Always set (not None) to test seed recording
random_seed_strategy = st.integers(min_value=0, max_value=2**31 - 1)


async def _create_run_with_data(
    session: AsyncSession,
    parameters: dict,
    software_versions: dict,
    random_seed,
) -> tuple[Run, Organization]:
    """Helper to create a run with the given parameters and seed in the DB."""
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
        software_versions=software_versions,
        random_seed=random_seed,
        started_at=datetime(2024, 1, 1, 10, 0),
        completed_at=datetime(2024, 1, 1, 11, 0),
        created_at=datetime(2024, 1, 1, 9, 0),
    )
    session.add(run)
    await session.commit()
    return run, org


@pytest.mark.property
class TestRandomSeedReproducibility:
    """Property 42: Random Seed Recording and Reproducibility

    For any run with a random seed, the seed must be faithfully recorded in the
    exported h5ad and reproducibility report, and must be consistent across
    multiple exports of the same run.
    """

    @pytest.mark.asyncio
    @given(
        random_seed=random_seed_strategy,
        parameters=run_params_strategy,
        software_versions=software_versions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_random_seed_recorded_in_h5ad_export(
        self,
        async_engine,
        random_seed,
        parameters,
        software_versions,
    ):
        """Property: For any run with a random seed, the seed is faithfully recorded in the exported h5ad zerna_run_metadata.

        **Validates: Requirements 27.2, 27.5**
        """
        session = await get_clean_session(async_engine)

        run, org = await _create_run_with_data(
            session,
            parameters=parameters,
            software_versions=software_versions,
            random_seed=random_seed,
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

        exported = ad.read_h5ad(captured_files[0])

        # Property: zerna_run_metadata is present
        assert "zerna_run_metadata" in exported.uns, "zerna_run_metadata must be present in uns"

        meta = exported.uns["zerna_run_metadata"]

        # Property: random_seed key is present
        assert "random_seed" in meta, "random_seed must be present in zerna_run_metadata"

        # Property: the recorded seed matches the run's actual seed
        assert meta["random_seed"] == random_seed, (
            f"random_seed mismatch: expected {random_seed}, got {meta['random_seed']}"
        )

        await session.close()

    @pytest.mark.asyncio
    @given(
        random_seed=random_seed_strategy,
        parameters=run_params_strategy,
        software_versions=software_versions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_random_seed_recorded_in_report(
        self,
        async_engine,
        random_seed,
        parameters,
        software_versions,
    ):
        """Property: For any run with a random seed, the seed value appears in the reproducibility report HTML.

        **Validates: Requirements 27.2, 27.5**
        """
        session = await get_clean_session(async_engine)

        run, org = await _create_run_with_data(
            session,
            parameters=parameters,
            software_versions=software_versions,
            random_seed=random_seed,
        )

        captured_reports = []

        def capture_upload(file_path, bucket, s3_path, content_type=None):
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="wb") as f:
                dest = f.name
            shutil.copy2(str(file_path), dest)
            captured_reports.append(dest)
            return {"etag": "abc", "size": 100, "checksum": "xyz"}

        mock_s3 = _make_mock_s3_service()
        mock_s3.upload_file.side_effect = capture_upload

        svc = ExportService(db=session, s3_service=mock_s3)
        await svc.generate_reproducibility_report(run.id, org.id)

        assert len(captured_reports) == 1

        with open(captured_reports[0], encoding="utf-8") as f:
            html = f.read()

        # Property: the seed value appears in the HTML report
        assert str(random_seed) in html, (
            f"Random seed {random_seed} must appear in the reproducibility report HTML"
        )

        # Property: the "Random Seeds" section is present
        assert "Random Seeds" in html, "Random Seeds section must be present in the report"

        await session.close()

    @pytest.mark.asyncio
    @given(
        random_seed=random_seed_strategy,
        parameters=run_params_strategy,
        software_versions=software_versions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_none_seed_recorded_as_sentinel(
        self,
        async_engine,
        random_seed,
        parameters,
        software_versions,
    ):
        """Property: For runs with no random seed (None), the h5ad export records -1 as the sentinel value.

        **Validates: Requirements 27.2, 27.5**
        """
        session = await get_clean_session(async_engine)

        # Create run with random_seed=None
        run, org = await _create_run_with_data(
            session,
            parameters=parameters,
            software_versions=software_versions,
            random_seed=None,
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

        exported = ad.read_h5ad(captured_files[0])

        assert "zerna_run_metadata" in exported.uns, "zerna_run_metadata must be present in uns"

        meta = exported.uns["zerna_run_metadata"]

        assert "random_seed" in meta, (
            "random_seed must be present in zerna_run_metadata even when None"
        )

        # Property: None seed is stored as -1 sentinel value
        assert meta["random_seed"] == -1, (
            f"None random_seed must be recorded as -1 sentinel, got {meta['random_seed']}"
        )

        await session.close()
