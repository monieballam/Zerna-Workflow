"""Unit tests for PipelineService."""

from uuid import uuid4

import pytest
import pytest_asyncio

from apps.api.models.organization import Organization
from apps.api.services.pipeline_service import PipelineService


@pytest_asyncio.fixture
async def organization(async_session):
    """Create a test organization."""
    org = Organization(
        id=uuid4(),
        name="Test Organization",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    async_session.add(org)
    await async_session.commit()
    await async_session.refresh(org)
    return org


@pytest.fixture
def pipeline_service(async_session):
    """Create a PipelineService."""
    return PipelineService(db=async_session)


@pytest.fixture
def valid_definition():
    """Create a valid pipeline definition."""
    return {
        "methods": ["qc_filter", "normalize", "cluster"],
        "dependencies": {
            "normalize": ["qc_filter"],
            "cluster": ["normalize"],
        },
        "parameter_schema": {
            "type": "object",
            "properties": {
                "min_cells": {"type": "integer", "minimum": 1},
                "min_genes": {"type": "integer", "minimum": 1},
                "resolution": {"type": "number", "minimum": 0.1, "maximum": 2.0},
            },
            "required": ["min_cells", "min_genes"],
        },
    }


@pytest.mark.asyncio
class TestPipelineService:
    """Test suite for PipelineService."""

    async def test_create_template_success(self, pipeline_service, organization, valid_definition):
        """Test successful template creation with valid definition."""
        # Act
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Standard Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        # Assert
        assert template.id is not None
        assert template.organization_id == organization.id
        assert template.name == "Standard Pipeline"
        assert template.version == "1.0.0"
        assert template.definition == valid_definition
        assert template.is_active is True
        assert template.created_at is not None

    async def test_create_template_missing_methods_key(self, pipeline_service, organization):
        """Test template creation fails when 'methods' key is missing."""
        # Arrange
        invalid_definition = {
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="must contain 'methods' key"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_create_template_missing_dependencies_key(self, pipeline_service, organization):
        """Test template creation fails when 'dependencies' key is missing."""
        # Arrange
        invalid_definition = {
            "methods": ["qc_filter"],
        }

        # Act & Assert
        with pytest.raises(ValueError, match="must contain 'dependencies' key"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_create_template_methods_not_list(self, pipeline_service, organization):
        """Test template creation fails when 'methods' is not a list."""
        # Arrange
        invalid_definition = {
            "methods": "qc_filter",
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="'methods' must be a list"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_create_template_dependencies_not_dict(self, pipeline_service, organization):
        """Test template creation fails when 'dependencies' is not a dict."""
        # Arrange
        invalid_definition = {
            "methods": ["qc_filter"],
            "dependencies": ["normalize"],
        }

        # Act & Assert
        with pytest.raises(ValueError, match="'dependencies' must be a dictionary"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_create_template_unknown_method(self, pipeline_service, organization):
        """Test template creation fails when method doesn't exist."""
        # Arrange
        invalid_definition = {
            "methods": ["unknown_method"],
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="Method 'unknown_method' not found"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_create_template_empty_methods(self, pipeline_service, organization):
        """Test template creation fails when methods list is empty."""
        # Arrange
        invalid_definition = {
            "methods": [],
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="must define at least one method"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition=invalid_definition,
            )

    async def test_get_template_by_version(self, pipeline_service, organization, valid_definition):
        """Test getting a template by specific version."""
        # Arrange
        created_template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        # Act
        template = await pipeline_service.get_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
        )

        # Assert
        assert template is not None
        assert template.id == created_template.id
        assert template.version == "1.0.0"

    async def test_get_template_latest_version(
        self, pipeline_service, organization, valid_definition
    ):
        """Test getting latest active version when version not specified."""
        # Arrange - Create multiple versions
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        latest_template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="2.0.0",
            definition=valid_definition,
        )

        # Act
        template = await pipeline_service.get_template(
            org_id=organization.id,
            name="Test Pipeline",
        )

        # Assert
        assert template is not None
        assert template.id == latest_template.id
        assert template.version == "2.0.0"

    async def test_get_template_not_found(self, pipeline_service, organization):
        """Test getting a non-existent template returns None."""
        # Act
        template = await pipeline_service.get_template(
            org_id=organization.id,
            name="Nonexistent Pipeline",
            version="1.0.0",
        )

        # Assert
        assert template is None

    async def test_get_template_wrong_organization(
        self, pipeline_service, organization, valid_definition
    ):
        """Test getting a template from wrong organization returns None."""
        # Arrange
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        # Act
        wrong_org_id = uuid4()
        template = await pipeline_service.get_template(
            org_id=wrong_org_id,
            name="Test Pipeline",
            version="1.0.0",
        )

        # Assert
        assert template is None

    async def test_list_templates_all_active(
        self, pipeline_service, organization, valid_definition
    ):
        """Test listing all active templates."""
        # Arrange
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Pipeline A",
            version="1.0.0",
            definition=valid_definition,
        )
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Pipeline B",
            version="1.0.0",
            definition=valid_definition,
        )

        # Act
        templates = await pipeline_service.list_templates(
            org_id=organization.id,
            is_active=True,
        )

        # Assert
        assert len(templates) == 2
        assert all(t.is_active for t in templates)

    async def test_list_templates_by_name(self, pipeline_service, organization, valid_definition):
        """Test listing templates filtered by name."""
        # Arrange
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Pipeline A",
            version="1.0.0",
            definition=valid_definition,
        )
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Pipeline A",
            version="2.0.0",
            definition=valid_definition,
        )
        await pipeline_service.create_template(
            org_id=organization.id,
            name="Pipeline B",
            version="1.0.0",
            definition=valid_definition,
        )

        # Act
        templates = await pipeline_service.list_templates(
            org_id=organization.id,
            name="Pipeline A",
        )

        # Assert
        assert len(templates) == 2
        assert all(t.name == "Pipeline A" for t in templates)

    async def test_list_templates_organization_isolation(
        self, pipeline_service, async_session, valid_definition
    ):
        """Test that templates are properly isolated by organization."""
        # Arrange - Create two organizations
        org1 = Organization(id=uuid4(), name="Org 1")
        org2 = Organization(id=uuid4(), name="Org 2")
        async_session.add(org1)
        async_session.add(org2)
        await async_session.commit()

        # Create templates in different organizations
        await pipeline_service.create_template(
            org_id=org1.id,
            name="Pipeline 1",
            version="1.0.0",
            definition=valid_definition,
        )
        await pipeline_service.create_template(
            org_id=org2.id,
            name="Pipeline 2",
            version="1.0.0",
            definition=valid_definition,
        )

        # Act
        templates1 = await pipeline_service.list_templates(org_id=org1.id)
        templates2 = await pipeline_service.list_templates(org_id=org2.id)

        # Assert
        assert len(templates1) == 1
        assert templates1[0].name == "Pipeline 1"

        assert len(templates2) == 1
        assert templates2[0].name == "Pipeline 2"

    async def test_validate_parameters_success(
        self, pipeline_service, organization, valid_definition
    ):
        """Test successful parameter validation."""
        # Arrange
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        parameters = {
            "min_cells": 10,
            "min_genes": 200,
            "resolution": 0.5,
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is True
        assert error is None

    async def test_validate_parameters_missing_required(
        self, pipeline_service, organization, valid_definition
    ):
        """Test parameter validation fails when required parameter is missing."""
        # Arrange
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        parameters = {
            "min_cells": 10,
            # missing min_genes
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is False
        assert "min_genes" in error
        assert "missing" in error.lower()

    async def test_validate_parameters_wrong_type(
        self, pipeline_service, organization, valid_definition
    ):
        """Test parameter validation fails when parameter has wrong type."""
        # Arrange
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        parameters = {
            "min_cells": "not_an_integer",
            "min_genes": 200,
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is False
        assert "min_cells" in error
        assert "integer" in error.lower()

    async def test_validate_parameters_below_minimum(
        self, pipeline_service, organization, valid_definition
    ):
        """Test parameter validation fails when value is below minimum."""
        # Arrange
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        parameters = {
            "min_cells": 0,  # minimum is 1
            "min_genes": 200,
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is False
        assert "min_cells" in error
        assert ">=" in error

    async def test_validate_parameters_above_maximum(
        self, pipeline_service, organization, valid_definition
    ):
        """Test parameter validation fails when value is above maximum."""
        # Arrange
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        parameters = {
            "min_cells": 10,
            "min_genes": 200,
            "resolution": 3.0,  # maximum is 2.0
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is False
        assert "resolution" in error
        assert "<=" in error

    async def test_validate_parameters_no_schema(self, pipeline_service, organization):
        """Test parameter validation succeeds when no schema is defined."""
        # Arrange
        definition = {
            "methods": ["qc_filter"],
            "dependencies": {},
            # No parameter_schema
        }

        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=definition,
        )

        parameters = {
            "any_param": "any_value",
        }

        # Act
        is_valid, error = await pipeline_service.validate_parameters(template.id, parameters)

        # Assert
        assert is_valid is True
        assert error is None

    async def test_validate_parameters_template_not_found(self, pipeline_service):
        """Test parameter validation fails when template doesn't exist."""
        # Act
        is_valid, error = await pipeline_service.validate_parameters(uuid4(), {})

        # Assert
        assert is_valid is False
        assert "not found" in error.lower()

    async def test_validate_parameters_enum_validation(self, pipeline_service, organization):
        """Test parameter validation with enum constraints."""
        # Arrange
        definition = {
            "methods": ["cluster"],
            "dependencies": {},
            "parameter_schema": {
                "properties": {
                    "algorithm": {
                        "type": "string",
                        "enum": ["leiden", "louvain"],
                    },
                },
            },
        }

        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=definition,
        )

        # Act - Valid enum value
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"algorithm": "leiden"}
        )
        assert is_valid is True

        # Act - Invalid enum value
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"algorithm": "kmeans"}
        )
        assert is_valid is False
        assert "must be one of" in error

    async def test_validate_parameters_type_validation(self, pipeline_service, organization):
        """Test parameter validation for different types."""
        # Arrange
        definition = {
            "methods": ["qc_filter"],
            "dependencies": {},
            "parameter_schema": {
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                    "ratio": {"type": "number"},
                    "enabled": {"type": "boolean"},
                    "items": {"type": "array"},
                    "config": {"type": "object"},
                },
            },
        }

        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Test Pipeline",
            version="1.0.0",
            definition=definition,
        )

        # Test string type
        is_valid, error = await pipeline_service.validate_parameters(template.id, {"name": 123})
        assert is_valid is False
        assert "string" in error.lower()

        # Test integer type
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"count": "not_int"}
        )
        assert is_valid is False
        assert "integer" in error.lower()

        # Test number type
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"ratio": "not_number"}
        )
        assert is_valid is False
        assert "number" in error.lower()

        # Test boolean type
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"enabled": "not_bool"}
        )
        assert is_valid is False
        assert "boolean" in error.lower()

        # Test array type
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"items": "not_array"}
        )
        assert is_valid is False
        assert "array" in error.lower()

        # Test object type
        is_valid, error = await pipeline_service.validate_parameters(
            template.id, {"config": "not_object"}
        )
        assert is_valid is False
        assert "object" in error.lower()

    async def test_resolve_methods_success(self, pipeline_service, valid_definition):
        """Test successful method resolution."""
        # Act
        methods = await pipeline_service.resolve_methods(valid_definition)

        # Assert
        assert methods == ["qc_filter", "normalize", "cluster"]

    async def test_resolve_methods_with_dict_format(self, pipeline_service):
        """Test method resolution with dict format methods."""
        # Arrange
        definition = {
            "methods": [
                {"name": "qc_filter", "params": {}},
                {"name": "normalize", "params": {}},
            ],
            "dependencies": {},
        }

        # Act
        methods = await pipeline_service.resolve_methods(definition)

        # Assert
        assert len(methods) == 2

    async def test_resolve_methods_ambient_correction_dict_entry(self, pipeline_service):
        """Optional ambient step must resolve (catalog + worker registry alignment)."""
        definition = {
            "methods": [
                {"name": "ambient_correction", "enabled_if": "ambient_correction"},
                "normalize",
            ],
            "dependencies": {},
        }
        methods = await pipeline_service.resolve_methods(definition)
        assert methods[0]["name"] == "ambient_correction"
        assert methods[1] == "normalize"

    async def test_resolve_methods_unknown_method(self, pipeline_service):
        """Test method resolution fails for unknown methods."""
        # Arrange
        definition = {
            "methods": ["unknown_method"],
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="not found in method registry"):
            await pipeline_service.resolve_methods(definition)

    async def test_resolve_methods_empty_list(self, pipeline_service):
        """Test method resolution fails for empty methods list."""
        # Arrange
        definition = {
            "methods": [],
            "dependencies": {},
        }

        # Act & Assert
        with pytest.raises(ValueError, match="must define at least one method"):
            await pipeline_service.resolve_methods(definition)

    async def test_create_template_definition_not_dict(self, pipeline_service, organization):
        """Test template creation fails when definition is not a dict."""
        # Act & Assert
        with pytest.raises(ValueError, match="must be a dictionary"):
            await pipeline_service.create_template(
                org_id=organization.id,
                name="Invalid Pipeline",
                version="1.0.0",
                definition="not_a_dict",
            )

    async def test_validate_parameters_supports_conditional_required_fields(
        self, pipeline_service, organization
    ):
        """Boolean-gated parameters should trigger conditional required fields."""
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Conditional Pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter", "pathway_scoring"],
                "dependencies": {"pathway_scoring": ["qc_filter"]},
                "parameter_schema": {
                    "properties": {
                        "pathway_scoring": {"type": "boolean"},
                        "pathway_net_path": {"type": "string"},
                    },
                    "allOf": [
                        {
                            "if": {"properties": {"pathway_scoring": {"const": True}}},
                            "then": {"required": ["pathway_net_path"]},
                        }
                    ],
                },
            },
        )

        is_valid, error = await pipeline_service.validate_parameters(
            template.id,
            {"pathway_scoring": True},
        )
        assert is_valid is False
        assert error == "Required parameter 'pathway_net_path' is missing"

        is_valid, error = await pipeline_service.validate_parameters(
            template.id,
            {"pathway_scoring": True, "pathway_net_path": "/tmp/pathways.csv"},
        )
        assert is_valid is True
        assert error is None

    async def test_validate_parameters_applies_conditional_const_before_required_checks(
        self, pipeline_service, organization
    ):
        """Forced values should participate in downstream conditional requirements."""
        template = await pipeline_service.create_template(
            org_id=organization.id,
            name="Forced Pipeline",
            version="1.0.0",
            definition={
                "methods": ["qc_filter", "ambient_correction"],
                "dependencies": {"ambient_correction": ["qc_filter"]},
                "parameter_schema": {
                    "properties": {
                        "ambient_correction": {"type": "boolean"},
                        "ambient_method": {
                            "type": "string",
                            "enum": ["off", "identity", "soupx"],
                        },
                        "ambient_counts_layer": {"type": "string"},
                    },
                    "allOf": [
                        {
                            "if": {"properties": {"ambient_correction": {"const": True}}},
                            "then": {
                                "properties": {"ambient_method": {"const": "identity"}},
                            },
                        },
                        {
                            "if": {
                                "properties": {"ambient_method": {"const": "identity"}},
                                "required": ["ambient_method"],
                            },
                            "then": {"required": ["ambient_counts_layer"]},
                        },
                    ],
                },
            },
        )

        is_valid, error = await pipeline_service.validate_parameters(
            template.id,
            {"ambient_correction": True},
        )
        assert is_valid is False
        assert error == "Required parameter 'ambient_counts_layer' is missing"

    async def test_apply_parameter_schema_constraints_forces_const_values(self, pipeline_service):
        """Conditional const values should overwrite invalid user-supplied choices."""
        normalized = pipeline_service.apply_parameter_schema_constraints(
            {
                "allOf": [
                    {
                        "if": {"properties": {"ambient_correction": {"const": True}}},
                        "then": {
                            "properties": {"ambient_method": {"const": "identity"}},
                        },
                    }
                ]
            },
            {"ambient_correction": True, "ambient_method": "soupx"},
        )

        assert normalized["ambient_method"] == "identity"

    async def test_clone_template_creates_new_version_and_deactivates_source(
        self, pipeline_service, organization, valid_definition
    ):
        """Cloning a template should produce a new active version and retire the source."""
        source = await pipeline_service.create_template(
            org_id=organization.id,
            name="Versioned Pipeline",
            version="1.0.0",
            definition=valid_definition,
        )

        cloned = await pipeline_service.clone_template(
            org_id=organization.id,
            source_template_id=source.id,
            version="1.1.0",
            deactivate_source=True,
        )

        assert cloned.id != source.id
        assert cloned.name == source.name
        assert cloned.version == "1.1.0"
        assert cloned.is_active is True

        refreshed_source = await pipeline_service.get_template_by_id(organization.id, source.id)
        assert refreshed_source is not None
        assert refreshed_source.is_active is False

    async def test_sync_default_templates_creates_seeded_versions(
        self, pipeline_service, organization
    ):
        """Seed sync should install the full standard template and legacy parity template."""
        templates = await pipeline_service.sync_default_templates(organization.id)
        template_names = {template.name for template in templates}
        assert template_names == {
            "scRNA-seq Standard",
            "scRNA-seq Legacy Parity",
        }

        standard = next(template for template in templates if template.name == "scRNA-seq Standard")
        methods = standard.definition["methods"]
        assert any(
            method == "doublet_detection"
            or (isinstance(method, dict) and method.get("name") == "doublet_detection")
            for method in methods
        )
        assert any(
            isinstance(method, dict)
            and method.get("name") == "pathway_scoring"
            and method.get("enabled_if") == "pathway_scoring"
            for method in methods
        )

        schema = standard.definition["parameter_schema"]
        min_genes_description = schema["properties"]["min_genes"]["description"]
        batch_method_description = schema["properties"]["batch_method"]["description"]
        assert schema["properties"]["doublet_method"]["default"] == "scrublet"
        assert schema["properties"]["doublet_method"]["enum"] == ["scrublet", "solo"]
        assert schema["properties"]["annotation_method"]["default"] == "celltypist"
        assert schema["properties"]["annotation_model"]["default"] == "auto"
        assert schema["properties"]["annotation_species"]["default"] == "auto"
        assert "celltypist" in schema["properties"]["annotation_method"]["enum"]
        assert "conservative" in schema["properties"]["annotation_method"]["enum"]
        assert "annotation_agent_v3" not in schema["properties"]["annotation_method"]["enum"]
        assert "legacy_pan_prostate_v2_yaml" not in schema["properties"]["annotation_method"]["enum"]
        assert "legacy_zerna_taxonomy" in schema["properties"]["annotation_marker_database"]["enum"]
        assert (
            "legacy_pan_prostate_full"
            not in schema["properties"]["annotation_marker_database"]["enum"]
        )
        assert schema["properties"]["pathway_database"]["enum"] == [
            "PROGENy",
            "DoRothEA",
            "Hallmark",
            "KEGG",
            "Reactome",
            "GO_Biological_Process",
            "Custom",
        ]
        assert "speeds later steps" in min_genes_description
        assert "Harmony" in batch_method_description and "scVI" in batch_method_description
        assert schema["properties"]["integration_mode"]["default"] == "harmony"
