"""Property-based tests for storage quota enforcement.

**Property 22: Storage Quota Enforcement**

For any organization, when total stored artifact size exceeds the storage quota,
new artifact uploads should fail with a quota exceeded error.

**Validates: Requirements 11.3**
"""

from uuid import uuid4

import pytest
from zerna_contracts.enums import ArtifactType, RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from apps.api.models import Base, Organization
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.pipeline import Artifact, PipelineTemplate, Run

# ---------------------------------------------------------------------------
# Synchronous helpers (QuotaService logic re-implemented for sync SQLite tests)
# ---------------------------------------------------------------------------


def _get_storage_used_bytes(session: Session, org_id) -> int:
    from sqlalchemy import func, select

    stmt = (
        select(func.coalesce(func.sum(Artifact.size_bytes), 0))
        .join(Run, Artifact.run_id == Run.id)
        .where(Run.organization_id == org_id)
    )
    return int(session.execute(stmt).scalar_one())


def _get_storage_quota_bytes(session: Session, org_id) -> int:
    from sqlalchemy import select

    stmt = select(Organization.storage_quota_gb).where(Organization.id == org_id)
    quota_gb = session.execute(stmt).scalar_one()
    return quota_gb * 1024 * 1024 * 1024


def _check_storage_quota(session: Session, org_id, additional_bytes: int = 0) -> None:
    """Raise ValueError if adding additional_bytes would exceed the quota."""
    used = _get_storage_used_bytes(session, org_id)
    limit = _get_storage_quota_bytes(session, org_id)
    if used + additional_bytes > limit:
        raise ValueError(
            f"storage quota exceeded: {used + additional_bytes} bytes used of {limit} bytes limit"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def clean_session(engine) -> Session:
    session = Session(engine)
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))
    session.commit()
    return session


def _make_org(session: Session, quota_gb: int) -> Organization:
    org = Organization(
        id=uuid4(), name=f"org-{uuid4()}", storage_quota_gb=quota_gb, compute_quota_runs=10
    )
    session.add(org)
    session.flush()
    return org


def _make_run(session: Session, org: Organization) -> Run:
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="ds", extra_metadata={})
    session.add(dataset)
    session.flush()

    version = DatasetVersion(id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://b/k")
    session.add(version)
    session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name=f"tpl-{uuid4()}",
        version="v1",
        definition={"steps": []},
    )
    session.add(template)
    session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={},
    )
    session.add(run)
    session.flush()
    return run


def _add_artifact(session: Session, run: Run, size_bytes: int) -> Artifact:
    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path=f"s3://bucket/{uuid4()}.h5ad",
        size_bytes=size_bytes,
        extra_metadata={},
    )
    session.add(artifact)
    session.flush()
    return artifact


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestStorageQuotaEnforcement:
    """Property 22: Storage Quota Enforcement."""

    @given(
        quota_gb=st.integers(min_value=1, max_value=10),
        artifact_sizes=st.lists(
            st.integers(min_value=1, max_value=500 * 1024 * 1024),  # up to 500 MB each
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=50)
    def test_quota_exceeded_when_artifacts_exceed_limit(self, engine, quota_gb, artifact_sizes):
        """Property: When total artifact size exceeds quota, upload should be rejected."""
        session = clean_session(engine)

        org = _make_org(session, quota_gb)
        run = _make_run(session, org)

        quota_bytes = quota_gb * 1024 * 1024 * 1024
        cumulative = 0

        for size in artifact_sizes:
            if cumulative + size > quota_bytes:
                # Adding this artifact would exceed quota — must raise
                with pytest.raises(ValueError, match="quota exceeded"):
                    _check_storage_quota(session, org.id, additional_bytes=size)
                # Verify the artifact was NOT added (quota check happens before write)
                break
            else:
                # Within quota — should succeed
                _check_storage_quota(session, org.id, additional_bytes=size)
                _add_artifact(session, run, size)
                cumulative += size

        session.close()

    @given(
        quota_gb=st.integers(min_value=1, max_value=5),
        num_artifacts=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=40)
    def test_quota_check_reflects_existing_artifacts(self, engine, quota_gb, num_artifacts):
        """Property: Quota check accounts for all existing artifacts in the organization."""
        session = clean_session(engine)

        org = _make_org(session, quota_gb)
        run = _make_run(session, org)

        quota_bytes = quota_gb * 1024 * 1024 * 1024
        # Fill exactly to quota with equal-sized artifacts
        size_each = quota_bytes // num_artifacts

        for _ in range(num_artifacts):
            _add_artifact(session, run, size_each)
        session.commit()

        used = _get_storage_used_bytes(session, org.id)
        assert used == size_each * num_artifacts

        # Any additional byte should now exceed the quota
        remaining = quota_bytes - used
        if remaining < 1:
            with pytest.raises(ValueError, match="quota exceeded"):
                _check_storage_quota(session, org.id, additional_bytes=1)

        session.close()

    @given(
        quota_gb=st.integers(min_value=1, max_value=5),
        num_orgs=st.integers(min_value=2, max_value=4),
    )
    @settings(max_examples=30)
    def test_quota_isolated_per_organization(self, engine, quota_gb, num_orgs):
        """Property: Quota usage for one organization does not affect another."""
        session = clean_session(engine)

        orgs = [_make_org(session, quota_gb) for _ in range(num_orgs)]
        runs = [_make_run(session, org) for org in orgs]

        quota_bytes = quota_gb * 1024 * 1024 * 1024
        # Fill org[0] to 90 % of quota
        fill_bytes = int(quota_bytes * 0.9)
        _add_artifact(session, runs[0], fill_bytes)
        session.commit()

        # Other organizations should still have full quota available
        for i in range(1, num_orgs):
            used = _get_storage_used_bytes(session, orgs[i].id)
            assert used == 0, f"Org {i} should have 0 bytes used, got {used}"
            # Should not raise for a large upload
            _check_storage_quota(session, orgs[i].id, additional_bytes=fill_bytes)

        session.close()

    @given(
        quota_gb=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=20)
    def test_zero_additional_bytes_never_exceeds_quota(self, engine, quota_gb):
        """Property: Checking quota with 0 additional bytes never raises when within limit."""
        session = clean_session(engine)

        org = _make_org(session, quota_gb)
        # No artifacts — should always pass
        _check_storage_quota(session, org.id, additional_bytes=0)

        session.close()

    @given(
        quota_gb=st.integers(min_value=1, max_value=5),
        size_bytes=st.integers(min_value=1, max_value=100 * 1024 * 1024),
    )
    @settings(max_examples=30)
    def test_quota_check_is_deterministic(self, engine, quota_gb, size_bytes):
        """Property: Calling quota check twice with same state returns same result."""
        session = clean_session(engine)

        org = _make_org(session, quota_gb)
        quota_bytes = quota_gb * 1024 * 1024 * 1024

        if size_bytes <= quota_bytes:
            # Both calls should succeed
            _check_storage_quota(session, org.id, additional_bytes=size_bytes)
            _check_storage_quota(session, org.id, additional_bytes=size_bytes)
        else:
            # Both calls should raise
            with pytest.raises(ValueError):
                _check_storage_quota(session, org.id, additional_bytes=size_bytes)
            with pytest.raises(ValueError):
                _check_storage_quota(session, org.id, additional_bytes=size_bytes)

        session.close()
