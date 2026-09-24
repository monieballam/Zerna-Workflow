"""Tests for pipeline service and routes."""

from uuid import uuid4

import pytest
from zerna_contracts.enums import UserRole
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import Organization, organization_users
from apps.api.models.pipeline import PipelineTemplate
from apps.api.services.pipeline_service import PipelineService


@pytest.mark.asyncio
class TestCreatePipelineTemplate:
    """Test create_template functionality."""

    async def test_create_template_success(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test successful pipeline template creation."""
        pipeline_service = PipelineService(db=async_session)

        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter", "normalize"],
                "dependencies": {"normalize": ["qc_filter"]},
            },
        )

        assert template.name == "test-pipeline"
        assert template.version == "1.0.0"
        assert template.organization_id == test_organization.id
        assert template.is_active is True
        assert template.definition["methods"] == ["qc_filter", "normalize"]

    async def test_create_template_invalid_definition_missing_methods(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test creating template with missing methods key."""
        pipeline_service = PipelineService(db=async_session)

        with pytest.raises(ValueError, match="methods"):
            await pipeline_service.create_template(
                org_id=test_organization.id,
                name="test-pipeline",
                version="1.0.0",
                definition={
                    "dependencies": {},
                },
            )

    async def test_create_template_invalid_definition_missing_dependencies(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test creating template with missing dependencies key."""
        pipeline_service = PipelineService(db=async_session)

        with pytest.raises(ValueError, match="dependencies"):
            await pipeline_service.create_template(
                org_id=test_organization.id,
                name="test-pipeline",
                version="1.0.0",
                definition={
                    "methods": ["qc_filter"],
                },
            )

    async def test_create_template_invalid_method(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test creating template with non-existent method."""
        pipeline_service = PipelineService(db=async_session)

        with pytest.raises(ValueError, match="invalid_method"):
            await pipeline_service.create_template(
                org_id=test_organization.id,
                name="test-pipeline",
                version="1.0.0",
                definition={
                    "methods": ["invalid_method"],
                    "dependencies": {},
                },
            )


@pytest.mark.asyncio
class TestListPipelineTemplates:
    """Test list_templates functionality."""

    async def test_list_templates_success(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test successful template listing."""
        pipeline_service = PipelineService(db=async_session)

        # Create test templates
        template1 = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="pipeline-1",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
        )

        template2 = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="pipeline-2",
            version="1.0.0",
            definition={
                "methods": ["normalize"],
                "dependencies": {},
            },
        )

        # List templates
        templates = await pipeline_service.list_templates(
            org_id=test_organization.id,
        )

        assert len(templates) == 2
        assert any(t.id == template1.id for t in templates)
        assert any(t.id == template2.id for t in templates)

    async def test_list_templates_with_name_filter(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test template listing with name filter."""
        pipeline_service = PipelineService(db=async_session)

        # Create test templates
        await pipeline_service.create_template(
            org_id=test_organization.id,
            name="pipeline-1",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
        )

        await pipeline_service.create_template(
            org_id=test_organization.id,
            name="pipeline-2",
            version="1.0.0",
            definition={
                "methods": ["normalize"],
                "dependencies": {},
            },
        )

        # List templates with filter
        templates = await pipeline_service.list_templates(
            org_id=test_organization.id,
            name="pipeline-1",
        )

        assert len(templates) == 1
        assert templates[0].name == "pipeline-1"

    async def test_list_templates_inactive(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test listing inactive templates."""
        pipeline_service = PipelineService(db=async_session)

        # Create inactive template directly
        inactive_template = PipelineTemplate(
            id=uuid4(),
            organization_id=test_organization.id,
            name="inactive-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
            is_active=False,
        )
        async_session.add(inactive_template)
        await async_session.commit()

        # List inactive templates
        templates = await pipeline_service.list_templates(
            org_id=test_organization.id,
            is_active=False,
        )

        assert len(templates) >= 1
        assert any(t.id == inactive_template.id for t in templates)
        assert all(not t.is_active for t in templates)


@pytest.mark.asyncio
class TestGetPipelineTemplate:
    """Test get_template functionality."""

    async def test_get_template_by_name_and_version(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test getting template by name and version."""
        pipeline_service = PipelineService(db=async_session)

        # Create template
        created_template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
        )

        # Get template
        template = await pipeline_service.get_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
        )

        assert template is not None
        assert template.id == created_template.id
        assert template.name == "test-pipeline"
        assert template.version == "1.0.0"

    async def test_get_template_latest_version(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test getting latest version of template."""
        pipeline_service = PipelineService(db=async_session)

        # Create multiple versions
        await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
        )

        latest_template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="2.0.0",
            definition={
                "methods": ["qc_filter", "normalize"],
                "dependencies": {"normalize": ["qc_filter"]},
            },
        )

        # Get latest version (no version specified)
        template = await pipeline_service.get_template(
            org_id=test_organization.id,
            name="test-pipeline",
        )

        assert template is not None
        assert template.id == latest_template.id
        assert template.version == "2.0.0"

    async def test_get_template_not_found(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test getting non-existent template."""
        pipeline_service = PipelineService(db=async_session)

        template = await pipeline_service.get_template(
            org_id=test_organization.id,
            name="non-existent",
            version="1.0.0",
        )

        assert template is None


@pytest.mark.asyncio
class TestPipelineApiRoutes:
    """Test API routes for pipeline-specific auxiliary endpoints."""

    async def test_get_pipeline_catalog_route(
        self,
        async_client,
        async_session: AsyncSession,
        test_user,
        test_organization: Organization,
    ):
        """The catalog route should resolve without colliding with template UUID routes."""
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        async def override_get_current_user():
            return test_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        try:
            response = await async_client.get("/v1/pipelines/catalog/methods")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        payload = response.json()
        assert "methods" in payload
        assert any(entry["name"] == "batch_correct" for entry in payload["methods"])

    async def test_sync_default_templates_route(
        self,
        async_client,
        async_session: AsyncSession,
        test_user,
        test_organization: Organization,
    ):
        """The default-sync route should resolve without colliding with template UUID routes."""
        await async_session.execute(
            insert(organization_users).values(
                organization_id=test_organization.id,
                user_id=test_user.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        async def override_get_current_user():
            return test_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        try:
            response = await async_client.post("/v1/pipelines/catalog/sync-defaults")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        payload = response.json()
        assert any(template["name"] == "scRNA-seq Standard" for template in payload)


@pytest.mark.asyncio
class TestValidateParameters:
    """Test validate_parameters functionality."""

    async def test_validate_parameters_success(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test successful parameter validation."""
        pipeline_service = PipelineService(db=async_session)

        # Create template with parameter schema
        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
                "parameter_schema": {
                    "required": ["min_cells"],
                    "properties": {
                        "min_cells": {"type": "integer", "minimum": 1},
                        "max_genes": {"type": "integer", "maximum": 10000},
                    },
                },
            },
        )

        # Validate parameters
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=template.id,
            parameters={"min_cells": 10, "max_genes": 5000},
        )

        assert is_valid is True
        assert error is None

    async def test_validate_parameters_missing_required(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test validation with missing required parameter."""
        pipeline_service = PipelineService(db=async_session)

        # Create template with parameter schema
        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
                "parameter_schema": {
                    "required": ["min_cells"],
                    "properties": {
                        "min_cells": {"type": "integer"},
                    },
                },
            },
        )

        # Validate parameters (missing min_cells)
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=template.id,
            parameters={"max_genes": 5000},
        )

        assert is_valid is False
        assert "min_cells" in error

    async def test_validate_parameters_invalid_type(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test validation with invalid parameter type."""
        pipeline_service = PipelineService(db=async_session)

        # Create template with parameter schema
        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
                "parameter_schema": {
                    "required": ["min_cells"],
                    "properties": {
                        "min_cells": {"type": "integer"},
                    },
                },
            },
        )

        # Validate parameters (wrong type)
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=template.id,
            parameters={"min_cells": "not_an_integer"},
        )

        assert is_valid is False
        assert "integer" in error

    async def test_validate_parameters_out_of_range(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test validation with out-of-range values."""
        pipeline_service = PipelineService(db=async_session)

        # Create template with parameter schema
        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
                "parameter_schema": {
                    "required": ["min_cells"],
                    "properties": {
                        "min_cells": {"type": "integer", "minimum": 1},
                        "max_genes": {"type": "integer", "maximum": 10000},
                    },
                },
            },
        )

        # Validate parameters (exceeds maximum)
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=template.id,
            parameters={"min_cells": 10, "max_genes": 20000},
        )

        assert is_valid is False
        assert "max_genes" in error

    async def test_validate_parameters_no_schema(
        self, async_session: AsyncSession, test_organization: Organization
    ):
        """Test validation for template without parameter schema."""
        pipeline_service = PipelineService(db=async_session)

        # Create template without parameter schema
        template = await pipeline_service.create_template(
            org_id=test_organization.id,
            name="test-pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter"],
                "dependencies": {},
            },
        )

        # Validate parameters (should accept any)
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=template.id,
            parameters={"any_param": "any_value"},
        )

        assert is_valid is True
        assert error is None

    async def test_validate_parameters_template_not_found(self, async_session: AsyncSession):
        """Test validation for non-existent template."""
        pipeline_service = PipelineService(db=async_session)

        non_existent_id = uuid4()
        is_valid, error = await pipeline_service.validate_parameters(
            template_id=non_existent_id,
            parameters={"min_cells": 10},
        )

        assert is_valid is False
        assert str(non_existent_id) in error
