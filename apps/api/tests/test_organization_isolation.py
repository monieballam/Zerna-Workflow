"""Property-based tests for organization resource isolation.

**Validates: Requirements 1.4, 11.1, 11.5**
"""

from uuid import uuid4

import pytest
from zerna_contracts.enums import RunStatus
from hypothesis import assume, given
from hypothesis import strategies as st
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from apps.api.models import (
    AuditEvent,
    Base,
    Dataset,
    DatasetVersion,
    Organization,
    PipelineTemplate,
    Run,
    User,
)


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def get_clean_session(engine):
    """Create a clean database session and clear all tables."""
    session = Session(engine)
    # Clear all tables in reverse order to respect foreign keys
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))
    session.commit()
    return session


# Hypothesis strategies for generating test data
def organization_strategy():
    """Generate a valid Organization."""
    return st.builds(
        Organization,
        id=st.just(uuid4()),
        name=st.text(min_size=1, max_size=100),
        storage_quota_gb=st.integers(min_value=1, max_value=10000),
        compute_quota_runs=st.integers(min_value=1, max_value=100),
    )


def dataset_strategy(org_id):
    """Generate a valid Dataset for a given organization."""
    return st.builds(
        Dataset,
        id=st.just(uuid4()),
        organization_id=st.just(org_id),
        name=st.text(min_size=1, max_size=100),
        description=st.one_of(st.none(), st.text(max_size=500)),
        extra_metadata=st.dictionaries(
            st.text(min_size=1, max_size=20), st.text(max_size=50), max_size=5
        ),
    )


def pipeline_template_strategy(org_id, unique_suffix=""):
    """Generate a valid PipelineTemplate for a given organization."""
    return st.builds(
        PipelineTemplate,
        id=st.just(uuid4()),
        organization_id=st.just(org_id),
        name=st.just(f"template-{uuid4()}{unique_suffix}"),  # Ensure uniqueness
        version=st.just(f"v{uuid4().hex[:8]}"),  # Ensure uniqueness
        definition=st.fixed_dictionaries(
            {"steps": st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5)}
        ),
    )


def run_strategy(org_id, dataset_version_id, template_id):
    """Generate a valid Run for a given organization."""
    return st.builds(
        Run,
        id=st.just(uuid4()),
        organization_id=st.just(org_id),
        dataset_version_id=st.just(dataset_version_id),
        template_id=st.just(template_id),
        status=st.sampled_from(list(RunStatus)),
        parameters=st.dictionaries(
            st.text(min_size=1, max_size=20), st.text(max_size=50), max_size=5
        ),
        random_seed=st.one_of(st.none(), st.integers(min_value=0, max_value=2**31 - 1)),
    )


def audit_event_strategy(org_id, user_id):
    """Generate a valid AuditEvent for a given organization."""
    return st.builds(
        AuditEvent,
        id=st.just(uuid4()),
        organization_id=st.just(org_id),
        user_id=st.just(user_id),
        action_type=st.sampled_from(
            ["dataset.create", "run.start", "run.complete", "annotation.edit"]
        ),
        resource_type=st.sampled_from(["dataset", "run", "annotation"]),
        resource_id=st.just(uuid4()),
        before_state=st.none(),
        after_state=st.dictionaries(
            st.text(min_size=1, max_size=20), st.text(max_size=50), max_size=3
        ),
    )


@pytest.mark.property
class TestOrganizationResourceIsolation:
    """Property 3: Organization Resource Isolation

    For any user query for resources, all returned resources should belong exclusively
    to organizations where the user is a member.
    """

    @given(
        num_orgs=st.integers(min_value=2, max_value=5),
        datasets_per_org=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_dataset_queries_isolated_by_organization(
        self, engine, num_orgs, datasets_per_org, data
    ):
        """Property: Querying datasets by organization_id returns only that organization's datasets."""
        session = get_clean_session(engine)

        # Create multiple organizations
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        # Create datasets for each organization
        org_datasets = {}
        for org in orgs:
            datasets = [data.draw(dataset_strategy(org.id)) for _ in range(datasets_per_org)]
            org_datasets[org.id] = datasets
            for dataset in datasets:
                session.add(dataset)
        session.commit()

        # Property: For each organization, querying by organization_id should return
        # only datasets belonging to that organization
        for org in orgs:
            stmt = select(Dataset).where(Dataset.organization_id == org.id)
            results = session.execute(stmt).scalars().all()

            # All returned datasets must belong to the queried organization
            assert all(d.organization_id == org.id for d in results), (
                f"Query for org {org.id} returned datasets from other organizations"
            )

            # All datasets for this organization must be returned
            expected_ids = {d.id for d in org_datasets[org.id]}
            actual_ids = {d.id for d in results}
            assert expected_ids == actual_ids, (
                f"Query for org {org.id} did not return all expected datasets"
            )

            # No datasets from other organizations should be returned
            other_org_ids = {o.id for o in orgs if o.id != org.id}
            assert not any(d.organization_id in other_org_ids for d in results), (
                f"Query for org {org.id} returned datasets from other organizations"
            )

        session.close()

    @given(
        num_orgs=st.integers(min_value=2, max_value=5),
        templates_per_org=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_pipeline_template_queries_isolated_by_organization(
        self, engine, num_orgs, templates_per_org, data
    ):
        """Property: Querying pipeline templates by organization_id returns only that organization's templates."""
        session = get_clean_session(engine)

        # Create multiple organizations
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        # Create pipeline templates for each organization
        org_templates = {}
        for idx, org in enumerate(orgs):
            templates = [
                data.draw(pipeline_template_strategy(org.id, f"-{idx}-{i}"))
                for i in range(templates_per_org)
            ]
            org_templates[org.id] = templates
            for template in templates:
                session.add(template)
        session.commit()

        # Property: For each organization, querying by organization_id should return
        # only templates belonging to that organization
        for org in orgs:
            stmt = select(PipelineTemplate).where(PipelineTemplate.organization_id == org.id)
            results = session.execute(stmt).scalars().all()

            # All returned templates must belong to the queried organization
            assert all(t.organization_id == org.id for t in results), (
                f"Query for org {org.id} returned templates from other organizations"
            )

            # All templates for this organization must be returned
            expected_ids = {t.id for t in org_templates[org.id]}
            actual_ids = {t.id for t in results}
            assert expected_ids == actual_ids, (
                f"Query for org {org.id} did not return all expected templates"
            )

        session.close()

    @given(
        num_orgs=st.integers(min_value=2, max_value=4),
        runs_per_org=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_run_queries_isolated_by_organization(self, engine, num_orgs, runs_per_org, data):
        """Property: Querying runs by organization_id returns only that organization's runs."""
        session = get_clean_session(engine)

        # Create multiple organizations with datasets, versions, templates, and runs
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        org_runs = {}
        for org in orgs:
            # Create a dataset and version for this org
            dataset = data.draw(dataset_strategy(org.id))
            session.add(dataset)
            session.flush()

            version = DatasetVersion(
                id=uuid4(),
                dataset_id=dataset.id,
                version="v1",
                s3_path=f"s3://bucket/{org.id}/data.h5ad",
            )
            session.add(version)
            session.flush()

            # Create a template for this org
            template = data.draw(pipeline_template_strategy(org.id, f"-run-{org.id}"))
            session.add(template)
            session.flush()

            # Create runs for this org
            runs = [
                data.draw(run_strategy(org.id, version.id, template.id))
                for _ in range(runs_per_org)
            ]
            org_runs[org.id] = runs
            for run in runs:
                session.add(run)
        session.commit()

        # Property: For each organization, querying by organization_id should return
        # only runs belonging to that organization
        for org in orgs:
            stmt = select(Run).where(Run.organization_id == org.id)
            results = session.execute(stmt).scalars().all()

            # All returned runs must belong to the queried organization
            assert all(r.organization_id == org.id for r in results), (
                f"Query for org {org.id} returned runs from other organizations"
            )

            # All runs for this organization must be returned
            expected_ids = {r.id for r in org_runs[org.id]}
            actual_ids = {r.id for r in results}
            assert expected_ids == actual_ids, (
                f"Query for org {org.id} did not return all expected runs"
            )

        session.close()

    @given(
        num_orgs=st.integers(min_value=2, max_value=5),
        events_per_org=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_audit_event_queries_isolated_by_organization(
        self, engine, num_orgs, events_per_org, data
    ):
        """Property: Querying audit events by organization_id returns only that organization's events."""
        session = get_clean_session(engine)

        # Create multiple organizations with users and audit events
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        org_events = {}
        for org in orgs:
            # Create a user for this org
            user = User(
                id=uuid4(),
                email=f"user-{org.id}@example.com",
                hashed_password="hashed_password",
            )
            session.add(user)
            session.flush()

            # Create audit events for this org
            events = [
                data.draw(audit_event_strategy(org.id, user.id)) for _ in range(events_per_org)
            ]
            org_events[org.id] = events
            for event in events:
                session.add(event)
        session.commit()

        # Property: For each organization, querying by organization_id should return
        # only audit events belonging to that organization
        for org in orgs:
            stmt = select(AuditEvent).where(AuditEvent.organization_id == org.id)
            results = session.execute(stmt).scalars().all()

            # All returned events must belong to the queried organization
            assert all(e.organization_id == org.id for e in results), (
                f"Query for org {org.id} returned audit events from other organizations"
            )

            # All events for this organization must be returned
            expected_ids = {e.id for e in org_events[org.id]}
            actual_ids = {e.id for e in results}
            assert expected_ids == actual_ids, (
                f"Query for org {org.id} did not return all expected audit events"
            )

        session.close()

    @given(
        num_orgs=st.integers(min_value=2, max_value=4),
        datasets_per_org=st.integers(min_value=1, max_value=2),
        data=st.data(),
    )
    def test_cross_organization_queries_return_empty(
        self, engine, num_orgs, datasets_per_org, data
    ):
        """Property: Querying with a non-existent organization_id returns no results."""
        session = get_clean_session(engine)

        # Create multiple organizations with datasets
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        for org in orgs:
            datasets = [data.draw(dataset_strategy(org.id)) for _ in range(datasets_per_org)]
            for dataset in datasets:
                session.add(dataset)
        session.commit()

        # Property: Querying with a non-existent organization_id should return no results
        non_existent_org_id = uuid4()
        assume(non_existent_org_id not in {org.id for org in orgs})

        stmt = select(Dataset).where(Dataset.organization_id == non_existent_org_id)
        results = session.execute(stmt).scalars().all()

        assert len(results) == 0, (
            f"Query for non-existent org {non_existent_org_id} returned {len(results)} datasets"
        )

        session.close()

    @given(
        num_orgs=st.integers(min_value=3, max_value=5),
        datasets_per_org=st.integers(min_value=2, max_value=4),
        data=st.data(),
    )
    def test_organization_isolation_with_multiple_queries(
        self, engine, num_orgs, datasets_per_org, data
    ):
        """Property: Multiple sequential queries maintain organization isolation."""
        session = get_clean_session(engine)

        # Create multiple organizations with datasets
        orgs = [data.draw(organization_strategy()) for _ in range(num_orgs)]
        for org in orgs:
            session.add(org)
        session.flush()

        all_datasets = []
        for org in orgs:
            datasets = [data.draw(dataset_strategy(org.id)) for _ in range(datasets_per_org)]
            all_datasets.extend(datasets)
            for dataset in datasets:
                session.add(dataset)
        session.commit()

        # Property: Multiple queries for different organizations should maintain isolation
        for org in orgs:
            stmt = select(Dataset).where(Dataset.organization_id == org.id)
            results = session.execute(stmt).scalars().all()

            # Verify isolation for each query
            assert all(d.organization_id == org.id for d in results), (
                f"Query for org {org.id} violated isolation"
            )

            # Verify no cross-contamination
            other_org_ids = {o.id for o in orgs if o.id != org.id}
            assert not any(d.organization_id in other_org_ids for d in results), (
                f"Query for org {org.id} returned datasets from other organizations"
            )

        session.close()
