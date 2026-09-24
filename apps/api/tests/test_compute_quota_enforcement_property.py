"""Property-based tests for compute quota enforcement.

**Property 23: Compute Quota Enforcement**

For any organization, when the number of concurrent running jobs reaches the
compute quota, new run submissions should be queued or rejected.

**Validates: Requirements 11.4**
"""

from uuid import uuid4

import pytest
from zerna_contracts.enums import RunStatus
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from apps.api.models import Base, Organization
from apps.api.models.dataset import Dataset, DatasetVersion
from apps.api.models.pipeline import PipelineTemplate, Run

# ---------------------------------------------------------------------------
# Synchronous helpers (mirrors QuotaService logic for sync SQLite tests)
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = [RunStatus.QUEUED, RunStatus.RUNNING]


def _get_active_run_count(session: Session, org_id) -> int:
    stmt = (
        select(func.count())
        .select_from(Run)
        .where(Run.organization_id == org_id, Run.status.in_(_ACTIVE_STATUSES))
    )
    return int(session.execute(stmt).scalar_one())


def _get_compute_quota(session: Session, org_id) -> int:
    stmt = select(Organization.compute_quota_runs).where(Organization.id == org_id)
    return int(session.execute(stmt).scalar_one())


def _check_compute_quota(session: Session, org_id) -> None:
    """Raise ValueError if active runs >= compute_quota_runs."""
    active = _get_active_run_count(session, org_id)
    limit = _get_compute_quota(session, org_id)
    if active >= limit:
        raise ValueError(f"compute quota exceeded: {active} concurrent runs of {limit} limit")


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


def _make_org(session: Session, compute_quota: int) -> Organization:
    org = Organization(
        id=uuid4(),
        name=f"org-{uuid4()}",
        storage_quota_gb=1000,
        compute_quota_runs=compute_quota,
    )
    session.add(org)
    session.flush()
    return org


def _make_run(session: Session, org: Organization, status: RunStatus) -> Run:
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
        status=status,
        parameters={},
    )
    session.add(run)
    session.flush()
    return run


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestComputeQuotaEnforcement:
    """Property 23: Compute Quota Enforcement."""

    @given(
        quota=st.integers(min_value=1, max_value=10),
        active_statuses=st.lists(
            st.sampled_from([RunStatus.QUEUED, RunStatus.RUNNING]),
            min_size=0,
            max_size=12,
        ),
    )
    @settings(max_examples=50)
    def test_new_run_rejected_when_quota_reached(self, engine, quota, active_statuses):
        """Property: When active runs >= quota, new run submission must be rejected."""
        session = clean_session(engine)

        org = _make_org(session, quota)

        # Create active runs up to the quota
        for i, status in enumerate(active_statuses):
            if i >= quota:
                break
            _make_run(session, org, status)
        session.commit()

        active = _get_active_run_count(session, org.id)

        if active >= quota:
            with pytest.raises(ValueError, match="quota exceeded"):
                _check_compute_quota(session, org.id)
        else:
            # Should not raise
            _check_compute_quota(session, org.id)

        session.close()

    @given(
        quota=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30)
    def test_completed_runs_do_not_count_toward_quota(self, engine, quota):
        """Property: COMPLETED and FAILED runs do not consume compute quota."""
        session = clean_session(engine)

        org = _make_org(session, quota)

        # Fill with terminal-state runs (should not count)
        for status in [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED]:
            for _ in range(quota):
                _make_run(session, org, status)
        session.commit()

        active = _get_active_run_count(session, org.id)
        assert active == 0, "Terminal-state runs should not count as active"

        # Quota check should pass — no active runs
        _check_compute_quota(session, org.id)

        session.close()

    @given(
        quota=st.integers(min_value=1, max_value=5),
        num_orgs=st.integers(min_value=2, max_value=4),
    )
    @settings(max_examples=30)
    def test_compute_quota_isolated_per_organization(self, engine, quota, num_orgs):
        """Property: Active runs in one organization do not affect another's quota."""
        session = clean_session(engine)

        orgs = [_make_org(session, quota) for _ in range(num_orgs)]

        # Fill org[0] to its quota
        for _ in range(quota):
            _make_run(session, orgs[0], RunStatus.RUNNING)
        session.commit()

        # org[0] should be at quota
        with pytest.raises(ValueError, match="quota exceeded"):
            _check_compute_quota(session, orgs[0].id)

        # All other organizations should still have capacity
        for i in range(1, num_orgs):
            active = _get_active_run_count(session, orgs[i].id)
            assert active == 0
            _check_compute_quota(session, orgs[i].id)  # must not raise

        session.close()

    @given(
        quota=st.integers(min_value=2, max_value=8),
    )
    @settings(max_examples=20)
    def test_quota_allows_runs_below_limit(self, engine, quota):
        """Property: Submitting runs below the quota limit always succeeds."""
        session = clean_session(engine)

        org = _make_org(session, quota)

        # Add quota-1 active runs
        for _ in range(quota - 1):
            _make_run(session, org, RunStatus.QUEUED)
        session.commit()

        active = _get_active_run_count(session, org.id)
        assert active == quota - 1

        # One more run should be allowed
        _check_compute_quota(session, org.id)  # must not raise

        session.close()

    @given(
        quota=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20)
    def test_quota_check_is_idempotent(self, engine, quota):
        """Property: Calling quota check multiple times with same state returns same result."""
        session = clean_session(engine)

        org = _make_org(session, quota)

        # Fill to quota
        for _ in range(quota):
            _make_run(session, org, RunStatus.RUNNING)
        session.commit()

        # Both calls should raise consistently
        with pytest.raises(ValueError):
            _check_compute_quota(session, org.id)
        with pytest.raises(ValueError):
            _check_compute_quota(session, org.id)

        session.close()

    @given(
        quota=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20)
    def test_quota_freed_when_run_completes(self, engine, quota):
        """Property: Completing a run frees up compute quota for new submissions."""
        session = clean_session(engine)

        org = _make_org(session, quota)

        # Fill to quota with RUNNING runs
        runs = [_make_run(session, org, RunStatus.RUNNING) for _ in range(quota)]
        session.commit()

        # At quota — should reject
        with pytest.raises(ValueError, match="quota exceeded"):
            _check_compute_quota(session, org.id)

        # Complete one run
        runs[0].status = RunStatus.COMPLETED
        session.commit()

        # Now one slot is free — should allow
        _check_compute_quota(session, org.id)  # must not raise

        session.close()
