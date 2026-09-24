"""Property-based tests for reproducibility report completeness.

**Validates: Requirements 9.4, 9.5, 27.4**
"""

from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from zerna_contracts.enums import RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base, Organization
from apps.api.models.annotation import AnnotationRevision
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

software_versions_strategy = st.dictionaries(
    keys=safe_text,
    values=safe_text,
    min_size=0,
    max_size=5,
)

run_params_strategy = st.dictionaries(
    keys=safe_text,
    values=safe_text,
    min_size=0,
    max_size=5,
)

random_seed_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1))

num_annotation_revisions_strategy = st.integers(min_value=0, max_value=3)

REQUIRED_SECTIONS = [
    "Software Versions",
    "Pipeline Parameters",
    "Random Seeds",
    "KnowledgePack",
    "Provenance",
    "Annotation History",
]


async def _create_run_with_data(
    session: AsyncSession,
    software_versions: dict,
    parameters: dict,
    random_seed,
    num_annotation_revisions: int,
) -> tuple[Run, Organization]:
    """Helper to create a run with optional annotations in the DB."""
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
    await session.flush()

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

    await session.commit()
    return run, org


def _make_mock_run(
    run_id,
    org_id,
    software_versions: dict,
    parameters: dict,
    random_seed,
) -> MagicMock:
    """Create a mock Run object with required attributes for _generate_html_report."""
    run = MagicMock()
    run.id = run_id
    run.organization_id = org_id
    run.status = RunStatus.COMPLETED
    run.started_at = datetime(2024, 1, 1, 10, 0)
    run.completed_at = datetime(2024, 1, 1, 11, 0)
    run.parameters = parameters
    run.software_versions = software_versions
    run.random_seed = random_seed
    run.created_at = datetime(2024, 1, 1, 9, 0)
    return run


@pytest.mark.property
class TestReproducibilityReportCompleteness:
    """Property 20: Reproducibility Report Completeness

    For any run with any combination of software versions, parameters, random seeds,
    and annotation revisions, the generated HTML reproducibility report must contain
    all required sections and data.
    """

    @pytest.mark.asyncio
    @given(
        software_versions=software_versions_strategy,
        parameters=run_params_strategy,
        random_seed=random_seed_strategy,
        num_annotation_revisions=num_annotation_revisions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_report_always_contains_required_sections(
        self,
        async_engine,
        software_versions,
        parameters,
        random_seed,
        num_annotation_revisions,
    ):
        """Property: For any run, the HTML report always contains all required section headings and the run_id.

        **Validates: Requirements 9.4, 9.5, 27.4**
        """
        run_id = uuid4()
        org_id = uuid4()

        mock_run = _make_mock_run(run_id, org_id, software_versions, parameters, random_seed)

        # Build mock annotation revisions
        mock_revisions = []
        for i in range(num_annotation_revisions):
            rev = MagicMock()
            rev.revision_number = i + 1
            rev.method = f"method_{i}"
            rev.created_at = datetime(2024, 1, 1, 12 + i, 0)
            rev.knowledge_pack_id = None
            mock_revisions.append(rev)

        svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())
        html = svc._generate_html_report(mock_run, [], mock_revisions)

        # Property: output is valid HTML
        assert "<!DOCTYPE html>" in html, "Report must start with <!DOCTYPE html>"
        assert "<html" in html, "Report must contain <html> tag"
        assert "<head" in html, "Report must contain <head> tag"
        assert "<body" in html, "Report must contain <body> tag"

        # Property: run_id is always present
        assert str(run_id) in html, f"run_id {run_id} must appear in the report"

        # Property: all required section headings are always present
        for section in REQUIRED_SECTIONS:
            assert section in html, f"Required section '{section}' missing from report"

    @pytest.mark.asyncio
    @given(
        software_versions=software_versions_strategy,
        parameters=run_params_strategy,
        random_seed=random_seed_strategy,
        num_annotation_revisions=num_annotation_revisions_strategy,
    )
    @settings(max_examples=50)
    async def test_property_report_contains_all_software_versions(
        self,
        async_engine,
        software_versions,
        parameters,
        random_seed,
        num_annotation_revisions,
    ):
        """Property: For any run with software versions, all package names and versions appear in the report.

        **Validates: Requirements 9.4, 9.5, 27.4**
        """
        run_id = uuid4()
        org_id = uuid4()

        mock_run = _make_mock_run(run_id, org_id, software_versions, parameters, random_seed)

        mock_revisions = []
        for i in range(num_annotation_revisions):
            rev = MagicMock()
            rev.revision_number = i + 1
            rev.method = f"method_{i}"
            rev.created_at = datetime(2024, 1, 1, 12 + i, 0)
            rev.knowledge_pack_id = None
            mock_revisions.append(rev)

        svc = ExportService(db=MagicMock(), s3_service=_make_mock_s3_service())
        html = svc._generate_html_report(mock_run, [], mock_revisions)

        # Property: all software version package names appear in the report
        for pkg_name, version_str in software_versions.items():
            assert pkg_name in html, f"Software package name '{pkg_name}' must appear in the report"
            assert version_str in html, (
                f"Software version '{version_str}' for package '{pkg_name}' must appear in the report"
            )

        # Property: all pipeline parameter keys and values appear in the report
        for key, value in parameters.items():
            assert key in html, f"Parameter key '{key}' must appear in the report"
            assert value in html, (
                f"Parameter value '{value}' for key '{key}' must appear in the report"
            )

        # Property: random seed value appears in the report when set
        if random_seed is not None:
            assert str(random_seed) in html, f"Random seed {random_seed} must appear in the report"

        # Property: annotation revision methods appear in the report when revisions exist
        for i in range(num_annotation_revisions):
            method = f"method_{i}"
            assert method in html, (
                f"Annotation revision method '{method}' must appear in the report"
            )
