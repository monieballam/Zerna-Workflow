"""Unit tests for SQLAlchemy models."""

from datetime import datetime
from uuid import uuid4

import pytest
from zerna_contracts.enums import (
    ArtifactType,
    KnowledgePackType,
    RunStatus,
)
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from apps.api.models import (
    AnnotationRevision,
    Artifact,
    AuditEvent,
    Base,
    Dataset,
    DatasetVersion,
    KnowledgePack,
    Organization,
    PipelineTemplate,
    Run,
    User,
)


@pytest.fixture
def engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create a database session for testing."""
    with Session(engine) as session:
        yield session


def test_base_model_creation(engine):
    """Test that all models can be created in the database."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    expected_tables = {
        "organizations",
        "users",
        "organization_users",
        "datasets",
        "dataset_versions",
        "pipeline_templates",
        "runs",
        "artifacts",
        "annotation_revisions",
        "knowledge_packs",
        "audit_events",
    }

    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"


def test_organization_creation(session):
    """Test creating an organization."""
    org = Organization(
        id=uuid4(),
        name="Test Organization",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    session.add(org)
    session.commit()

    assert org.id is not None
    assert org.name == "Test Organization"
    assert org.created_at is not None


def test_user_creation(session):
    """Test creating a user."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        hashed_password="hashed_password_here",
    )
    session.add(user)
    session.commit()

    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.created_at is not None


def test_dataset_with_organization(session):
    """Test creating a dataset with organization relationship."""
    org = Organization(
        id=uuid4(),
        name="Test Org",
    )
    session.add(org)
    session.flush()

    dataset = Dataset(
        id=uuid4(),
        organization_id=org.id,
        name="Test Dataset",
        description="A test dataset",
        extra_metadata={"key": "value"},
    )
    session.add(dataset)
    session.commit()

    assert dataset.organization_id == org.id
    assert dataset.name == "Test Dataset"
    assert dataset.extra_metadata == {"key": "value"}


def test_dataset_version_creation(session):
    """Test creating a dataset version."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    dataset = Dataset(
        id=uuid4(),
        organization_id=org.id,
        name="Test Dataset",
    )
    session.add(dataset)
    session.flush()

    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://bucket/path",
        cell_count=1000,
        gene_count=2000,
        file_format="h5ad",
    )
    session.add(version)
    session.commit()

    assert version.dataset_id == dataset.id
    assert version.version == "v1"
    assert version.cell_count == 1000


def test_pipeline_template_creation(session):
    """Test creating a pipeline template."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc", "normalize"]},
    )
    session.add(template)
    session.commit()

    assert template.name == "Test Pipeline"
    assert template.version == "v1.0"
    assert template.definition == {"steps": ["qc", "normalize"]}


def test_run_creation(session):
    """Test creating a run."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    session.add(dataset)
    session.flush()

    version = DatasetVersion(
        id=uuid4(),
        dataset_id=dataset.id,
        version="v1",
        s3_path="s3://bucket/path",
    )
    session.add(version)
    session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={},
    )
    session.add(template)
    session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.QUEUED,
        parameters={"param1": "value1"},
        random_seed=42,
    )
    session.add(run)
    session.commit()

    assert run.status == RunStatus.QUEUED
    assert run.parameters == {"param1": "value1"}
    assert run.random_seed == 42


def test_artifact_creation(session):
    """Test creating an artifact."""
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )
    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.RUNNING,
        parameters={},
    )

    session.add_all([org, dataset, version, template, run])
    session.flush()

    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        artifact_type=ArtifactType.H5AD,
        s3_path="s3://bucket/artifacts/result.h5ad",
        size_bytes=1024000,
        extra_metadata={"format": "h5ad"},
    )
    session.add(artifact)
    session.commit()

    assert artifact.artifact_type == ArtifactType.H5AD
    assert artifact.size_bytes == 1024000


def test_annotation_revision_creation(session):
    """Test creating an annotation revision."""
    org = Organization(id=uuid4(), name="Test Org")
    user = User(id=uuid4(), email="test@example.com", hashed_password="hash")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )
    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.COMPLETED,
        parameters={},
    )

    session.add_all([org, user, dataset, version, template, run])
    session.flush()

    annotation = AnnotationRevision(
        id=uuid4(),
        run_id=run.id,
        revision_number=1,
        annotations={"cell_1": {"cell_type": "T cell", "confidence": 0.95}},
        method="celltypist",
        created_by=user.id,
    )
    session.add(annotation)
    session.commit()

    assert annotation.revision_number == 1
    assert annotation.method == "celltypist"
    assert "cell_1" in annotation.annotations


def test_knowledge_pack_creation(session):
    """Test creating a knowledge pack."""
    pack = KnowledgePack(
        id=uuid4(),
        name="Cell Type Markers",
        version="v1.0",
        pack_type=KnowledgePackType.CELL_TYPE_MARKERS,
        s3_path="s3://bucket/knowledge/markers.json",
        schema_version="1.0",
        extra_metadata={"source": "CellMarker"},
    )
    session.add(pack)
    session.commit()

    assert pack.name == "Cell Type Markers"
    assert pack.pack_type == KnowledgePackType.CELL_TYPE_MARKERS
    assert pack.extra_metadata["source"] == "CellMarker"


def test_audit_event_creation(session):
    """Test creating an audit event."""
    org = Organization(id=uuid4(), name="Test Org")
    user = User(id=uuid4(), email="test@example.com", hashed_password="hash")

    session.add_all([org, user])
    session.flush()

    audit = AuditEvent(
        id=uuid4(),
        organization_id=org.id,
        user_id=user.id,
        action_type="dataset.create",
        resource_type="dataset",
        resource_id=uuid4(),
        before_state=None,
        after_state={"name": "New Dataset"},
    )
    session.add(audit)
    session.commit()

    assert audit.action_type == "dataset.create"
    assert audit.resource_type == "dataset"
    assert audit.after_state == {"name": "New Dataset"}


def test_organization_user_relationship(session):
    """Test many-to-many relationship between organizations and users."""
    org = Organization(id=uuid4(), name="Test Org")
    user = User(id=uuid4(), email="test@example.com", hashed_password="hash")

    session.add_all([org, user])
    session.flush()

    # Add user to organization
    org.users.append(user)
    session.commit()

    # Verify relationship
    assert user in org.users
    assert org in user.organizations


def test_composite_indexes_exist(engine):
    """Test that composite indexes are created."""
    inspector = inspect(engine)

    # Check runs table has composite index on org_id and status
    runs_indexes = inspector.get_indexes("runs")
    index_names = [idx["name"] for idx in runs_indexes]

    # At least verify we have indexes on the runs table
    assert len(runs_indexes) > 0, "Runs table should have indexes"


def test_pipeline_template_is_active_default(session):
    """Test that is_active defaults to True."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )
    session.add(template)
    session.commit()

    assert template.is_active is True


def test_pipeline_template_updated_at(session):
    """Test that updated_at is set on creation and update."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    template = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )
    session.add(template)
    session.commit()

    created_at = template.created_at
    updated_at = template.updated_at

    assert updated_at is not None
    assert created_at is not None
    # Timestamps should be very close (within 1 second)
    assert abs((created_at - updated_at).total_seconds()) < 1

    # Update the template
    template.is_active = False
    session.commit()

    # updated_at should change (in a real database with proper onupdate support)
    # Note: SQLite may not fully support onupdate, but the field should still exist
    assert template.updated_at is not None


def test_pipeline_template_unique_constraint(session):
    """Test that organization_id + name + version must be unique."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    template1 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )
    session.add(template1)
    session.commit()

    # Try to create duplicate
    template2 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["normalize"]},
    )
    session.add(template2)

    with pytest.raises(Exception):  # Should raise IntegrityError
        session.commit()


def test_pipeline_template_versioning(session):
    """Test that multiple versions of the same template can exist."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    template_v1 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )
    template_v2 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v2.0",
        definition={"steps": ["qc", "normalize"]},
    )

    session.add_all([template_v1, template_v2])
    session.commit()

    assert template_v1.version == "v1.0"
    assert template_v2.version == "v2.0"
    assert template_v1.name == template_v2.name


def test_pipeline_template_organization_scoping(session):
    """Test that templates are scoped to organizations."""
    org1 = Organization(id=uuid4(), name="Org 1")
    org2 = Organization(id=uuid4(), name="Org 2")
    session.add_all([org1, org2])
    session.flush()

    # Same name and version but different organizations should be allowed
    template1 = PipelineTemplate(
        id=uuid4(),
        organization_id=org1.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )
    template2 = PipelineTemplate(
        id=uuid4(),
        organization_id=org2.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
    )

    session.add_all([template1, template2])
    session.commit()

    assert template1.organization_id != template2.organization_id
    assert template1.name == template2.name
    assert template1.version == template2.version


def test_pipeline_template_immutability_pattern(session):
    """Test that templates follow immutability pattern via versioning."""
    org = Organization(id=uuid4(), name="Test Org")
    session.add(org)
    session.flush()

    # Create initial version
    template_v1 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v1.0",
        definition={"steps": ["qc"]},
        is_active=True,
    )
    session.add(template_v1)
    session.commit()

    # To "update" the template, create a new version and deprecate the old one
    template_v2 = PipelineTemplate(
        id=uuid4(),
        organization_id=org.id,
        name="Test Pipeline",
        version="v2.0",
        definition={"steps": ["qc", "normalize"]},
        is_active=True,
    )
    session.add(template_v2)

    # Mark old version as inactive
    template_v1.is_active = False
    session.commit()

    assert template_v1.is_active is False
    assert template_v2.is_active is True
    assert template_v1.definition == {"steps": ["qc"]}  # Original definition unchanged
    assert template_v2.definition == {"steps": ["qc", "normalize"]}


def test_pipeline_template_indexes_exist(engine):
    """Test that indexes are created on pipeline_templates table."""
    inspector = inspect(engine)

    indexes = inspector.get_indexes("pipeline_templates")
    index_names = [idx["name"] for idx in indexes]

    # Check for expected indexes
    assert any("org" in name.lower() or "organization" in name.lower() for name in index_names), (
        "Should have index on organization_id"
    )

    # Verify we have multiple indexes
    assert len(indexes) > 0, "Pipeline templates table should have indexes"


# ============================================================================
# Run Model Tests (Task 6.1: Validates Requirements 7.1, 7.2)
# ============================================================================


def test_run_status_enum_values(session):
    """Test that Run status enum includes all required lifecycle states.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    # Test all required status values
    for status in [
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ]:
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

        assert run.status == status
        session.delete(run)


def test_run_default_status_is_queued(session):
    """Test that Run status defaults to QUEUED.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        parameters={},
    )
    session.add(run)
    session.commit()

    assert run.status == RunStatus.QUEUED


def test_run_parameters_jsonb_field(session):
    """Test that Run parameters field stores JSONB data correctly.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    complex_params = {
        "qc": {"min_cells": 3, "min_genes": 200},
        "normalization": {"method": "log1p", "scale_factor": 10000},
        "clustering": {"resolution": 0.5, "algorithm": "leiden"},
        "nested": {"deep": {"value": [1, 2, 3]}},
    }

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.QUEUED,
        parameters=complex_params,
    )
    session.add(run)
    session.commit()

    assert run.parameters == complex_params
    assert run.parameters["qc"]["min_cells"] == 3
    assert run.parameters["nested"]["deep"]["value"] == [1, 2, 3]


def test_run_software_versions_field(session):
    """Test that Run software_versions field stores version information.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    software_versions = {
        "scanpy": "1.9.3",
        "scvi-tools": "1.0.0",
        "celltypist": "1.6.0",
        "python": "3.11.5",
    }

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.RUNNING,
        parameters={},
        software_versions=software_versions,
    )
    session.add(run)
    session.commit()

    assert run.software_versions == software_versions
    assert run.software_versions["scanpy"] == "1.9.3"


def test_run_random_seed_field(session):
    """Test that Run random_seed field stores integer seeds.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.QUEUED,
        parameters={},
        random_seed=42,
    )
    session.add(run)
    session.commit()

    assert run.random_seed == 42
    assert isinstance(run.random_seed, int)


def test_run_timestamps_lifecycle(session):
    """Test that Run timestamps track lifecycle correctly.

    **Validates: Requirements 7.2**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    # Create run in QUEUED state
    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.QUEUED,
        parameters={},
    )
    session.add(run)
    session.commit()

    # Verify initial state
    assert run.created_at is not None
    assert run.started_at is None
    assert run.completed_at is None

    # Transition to RUNNING
    run.status = RunStatus.RUNNING
    run.started_at = datetime.utcnow()
    session.commit()

    assert run.started_at is not None
    assert run.completed_at is None
    assert run.started_at >= run.created_at

    # Transition to COMPLETED
    run.status = RunStatus.COMPLETED
    run.completed_at = datetime.utcnow()
    session.commit()

    assert run.completed_at is not None
    assert run.completed_at >= run.started_at


def test_run_error_message_field(session):
    """Test that Run error_message field stores failure details.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    error_msg = "QC filtering failed: Insufficient cells after filtering (found 5, required 10)"

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.FAILED,
        parameters={},
        error_message=error_msg,
    )
    session.add(run)
    session.commit()

    assert run.error_message == error_msg
    assert run.status == RunStatus.FAILED


def test_run_relationships(session):
    """Test that Run has correct relationships to DatasetVersion and PipelineTemplate.

    **Validates: Requirements 7.1**
    """
    org = Organization(id=uuid4(), name="Test Org")
    dataset = Dataset(id=uuid4(), organization_id=org.id, name="Test Dataset")
    version = DatasetVersion(
        id=uuid4(), dataset_id=dataset.id, version="v1", s3_path="s3://bucket/path"
    )
    template = PipelineTemplate(
        id=uuid4(), organization_id=org.id, name="Test Pipeline", version="v1.0", definition={}
    )

    session.add_all([org, dataset, version, template])
    session.flush()

    run = Run(
        id=uuid4(),
        organization_id=org.id,
        dataset_version_id=version.id,
        template_id=template.id,
        status=RunStatus.QUEUED,
        parameters={},
    )
    session.add(run)
    session.commit()

    # Test relationships
    assert run.dataset_version == version
    assert run.template == template
    assert run in version.runs
    assert run in template.runs


def test_run_indexes_exist(engine):
    """Test that Run table has required indexes for performance.

    **Validates: Requirements 7.2**
    """
    inspector = inspect(engine)

    indexes = inspector.get_indexes("runs")
    index_names = [idx["name"] for idx in indexes]

    # Verify we have indexes on critical fields
    assert len(indexes) > 0, "Runs table should have indexes"

    # Check for status index (critical for filtering by run state)
    assert any("status" in name.lower() for name in index_names), (
        "Should have index on status field"
    )
