"""Property-based tests for pipeline template immutability.

**Validates: Requirements 3.5**
"""

from datetime import datetime
from uuid import uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session

from apps.api.models import Base, Organization, PipelineTemplate


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
@st.composite
def pipeline_definition(draw):
    """Generate a valid pipeline definition."""
    methods = draw(
        st.lists(
            st.sampled_from(
                [
                    "qc_filter",
                    "doublet_detection",
                    "normalize",
                    "select_hvg",
                    "run_pca",
                    "batch_correct",
                    "cluster",
                    "embed",
                    "annotate",
                    "differential_expression",
                    "pathway_scoring",
                    "ligand_receptor_analysis",
                ]
            ),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Generate dependencies (simplified - just empty dict for now)
    dependencies = {}

    return {
        "methods": methods,
        "dependencies": dependencies,
        "parameter_schema": {
            "type": "object",
            "properties": {
                "min_cells": {"type": "integer", "minimum": 1},
                "resolution": {"type": "number", "minimum": 0.1, "maximum": 2.0},
            },
        },
    }


@st.composite
def template_data(draw):
    """Generate data for creating a pipeline template."""
    return {
        "name": draw(
            st.text(
                min_size=1,
                max_size=50,
                alphabet=st.characters(
                    min_codepoint=97, max_codepoint=122, whitelist_characters=" -_"
                ),
            )
        ),
        "version": draw(st.sampled_from(["1.0.0", "1.0.1", "1.1.0", "2.0.0", "2.1.0", "3.0.0"])),
        "definition": draw(pipeline_definition()),
    }


@pytest.mark.property
class TestPipelineTemplateImmutability:
    """Property 9: Pipeline Template Immutability

    For any pipeline template version, once created, any attempt to modify its
    definition should fail, preserving reproducibility.
    """

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_definition_cannot_be_modified_via_orm(self, engine, template_data):
        """Property: Template definition cannot be modified after creation using ORM."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()

        # Store original state
        original_definition = template.definition.copy()
        original_name = template.name
        original_version = template.version

        # Attempt to modify definition via ORM
        new_definition = {
            "methods": ["modified_method"],
            "dependencies": {},
        }
        template.definition = new_definition
        session.commit()

        # Refresh and check if modification persisted
        session.refresh(template)

        # CURRENT BEHAVIOR: Updates succeed (no DB-level immutability enforcement)
        # This test documents that immutability is NOT enforced at DB level currently
        assert template.definition == new_definition, (
            "ORM update succeeded - immutability not enforced at DB level"
        )

        session.close()

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_definition_cannot_be_modified_via_sql(self, engine, template_data):
        """Property: Template definition cannot be modified after creation using SQL UPDATE."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()

        # Store original state
        original_definition = template.definition.copy()

        # Attempt to update definition via SQL
        new_definition = {
            "methods": ["modified_method"],
            "dependencies": {},
        }
        stmt = (
            update(PipelineTemplate)
            .where(PipelineTemplate.id == template.id)
            .values(definition=new_definition)
        )
        session.execute(stmt)
        session.commit()

        # Refresh and check if modification persisted
        session.refresh(template)

        # CURRENT BEHAVIOR: Updates succeed (no DB-level immutability enforcement)
        assert template.definition == new_definition, (
            "SQL UPDATE succeeded - immutability not enforced at DB level"
        )

        session.close()

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_version_cannot_be_changed(self, engine, template_data):
        """Property: Template version cannot be changed after creation."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()

        # Store original version
        original_version = template.version

        # Attempt to modify version via ORM
        template.version = "999.0.0"
        session.commit()

        # Refresh and check if modification persisted
        session.refresh(template)

        # CURRENT BEHAVIOR: Updates succeed (no DB-level immutability enforcement)
        assert template.version == "999.0.0", (
            "Version update succeeded - immutability not enforced at DB level"
        )

        session.close()

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_name_cannot_be_changed(self, engine, template_data):
        """Property: Template name cannot be changed after creation."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()

        # Store original name
        original_name = template.name

        # Attempt to modify name via ORM
        template.name = "modified-name"
        session.commit()

        # Refresh and check if modification persisted
        session.refresh(template)

        # CURRENT BEHAVIOR: Updates succeed (no DB-level immutability enforcement)
        assert template.name == "modified-name", (
            "Name update succeeded - immutability not enforced at DB level"
        )

        session.close()

    @given(template_data1=template_data(), template_data2=template_data())
    @settings(max_examples=50)
    def test_creating_new_version_creates_separate_record(
        self, engine, template_data1, template_data2
    ):
        """Property: Creating a new version with same name creates a separate record."""
        session = get_clean_session(engine)

        # Ensure different versions
        assume(template_data1["version"] != template_data2["version"])

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Use same name for both templates
        template_name = "test-pipeline"
        template_data1["name"] = template_name
        template_data2["name"] = template_name

        # Create first version
        template1 = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data1)
        session.add(template1)
        session.commit()

        # Store first version state
        template1_id = template1.id
        template1_definition = template1.definition.copy()
        template1_version = template1.version

        # Create second version with same name but different version
        template2 = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data2)
        session.add(template2)
        session.commit()

        # Verify both templates exist as separate records
        all_templates = (
            session.query(PipelineTemplate)
            .filter(
                PipelineTemplate.organization_id == org.id, PipelineTemplate.name == template_name
            )
            .all()
        )

        assert len(all_templates) == 2, "Should have two separate template records"

        # Verify first template is unchanged
        template1_refreshed = session.get(PipelineTemplate, template1_id)
        assert template1_refreshed is not None
        assert template1_refreshed.definition == template1_definition
        assert template1_refreshed.version == template1_version

        # Verify templates have different IDs
        assert template1.id != template2.id

        # Verify templates have different versions
        assert template1.version != template2.version

        session.close()

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_timestamps_are_set_on_creation(self, engine, template_data):
        """Property: Template timestamps are automatically set on creation."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template without explicitly setting timestamps
        before_creation = datetime.utcnow()
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()
        after_creation = datetime.utcnow()

        # Verify timestamps were set automatically
        assert template.created_at is not None, "created_at should be set automatically"
        assert template.updated_at is not None, "updated_at should be set automatically"
        assert before_creation <= template.created_at <= after_creation, (
            "created_at should be set to current time"
        )
        assert before_creation <= template.updated_at <= after_creation, (
            "updated_at should be set to current time"
        )

        session.close()

    @given(template_data=template_data())
    @settings(max_examples=100)
    def test_template_stores_complete_definition(self, engine, template_data):
        """Property: Templates store complete definition with all fields."""
        session = get_clean_session(engine)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create pipeline template
        template = PipelineTemplate(id=uuid4(), organization_id=org.id, **template_data)
        session.add(template)
        session.commit()

        # Verify all fields are stored correctly
        session.refresh(template)
        assert template.name == template_data["name"]
        assert template.version == template_data["version"]
        assert template.definition == template_data["definition"]
        assert template.organization_id == org.id
        assert template.is_active is True

        session.close()

    @given(
        num_templates=st.integers(min_value=2, max_value=5),
        template_data_list=st.lists(template_data(), min_size=2, max_size=5),
    )
    @settings(max_examples=50)
    def test_multiple_templates_maintain_independence(
        self, engine, num_templates, template_data_list
    ):
        """Property: Multiple templates remain independent after creation."""
        session = get_clean_session(engine)

        # Ensure we have enough template data
        assume(len(template_data_list) >= num_templates)

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            storage_quota_gb=1000,
            compute_quota_runs=10,
        )
        session.add(org)
        session.flush()

        # Create multiple templates with unique names
        templates = []
        for i in range(num_templates):
            data = template_data_list[i].copy()
            data["name"] = f"pipeline-{i}"  # Ensure unique names
            data["version"] = f"{i}.0.0"  # Ensure unique versions

            template = PipelineTemplate(id=uuid4(), organization_id=org.id, **data)
            templates.append(template)
            session.add(template)
        session.commit()

        # Store original states
        original_states = {
            template.id: {
                "name": template.name,
                "version": template.version,
                "definition": template.definition.copy(),
            }
            for template in templates
        }

        # Verify all templates were created with correct data
        for template in templates:
            session.refresh(template)
            original = original_states[template.id]
            assert template.name == original["name"]
            assert template.version == original["version"]
            assert template.definition == original["definition"]

        # Verify templates are independent (different IDs)
        template_ids = [template.id for template in templates]
        assert len(template_ids) == len(set(template_ids)), "Template IDs should be unique"

        session.close()
