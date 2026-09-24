"""Pipeline service for template management and validation."""

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from zerna_contracts.pipeline_methods import METHOD_ALIASES, METHOD_REGISTRY
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.pipeline import PipelineTemplate
from apps.api.services.pipeline_catalog import (
    METHOD_CATALOG_BY_NAME,
    get_method_catalog,
    get_seed_template_specs,
)


class PipelineService:
    """Service for pipeline template management with schema validation."""

    def __init__(self, db: AsyncSession):
        """Initialize PipelineService.

        Args:
            db: Database session
        """
        self.db = db

    async def _validate_definition(self, definition: dict[str, Any]) -> None:
        """Validate the structure and referenced methods of a template definition."""
        if not isinstance(definition, dict):
            raise ValueError("Definition must be a dictionary")

        if "methods" not in definition:
            raise ValueError("Definition must contain 'methods' key")

        if "dependencies" not in definition:
            raise ValueError("Definition must contain 'dependencies' key")

        if not isinstance(definition["methods"], list):
            raise ValueError("'methods' must be a list")

        if not isinstance(definition["dependencies"], dict):
            raise ValueError("'dependencies' must be a dictionary")

        await self.resolve_methods(definition)

    async def _create_template_record(
        self,
        org_id: UUID,
        name: str,
        version: str,
        definition: dict[str, Any],
        *,
        is_active: bool = True,
        commit: bool = True,
    ) -> PipelineTemplate:
        """Persist a validated template record."""
        template = PipelineTemplate(
            id=uuid4(),
            organization_id=org_id,
            name=name,
            version=version,
            definition=definition,
            is_active=is_active,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        self.db.add(template)
        if commit:
            await self.db.commit()
            await self.db.refresh(template)

        return template

    async def get_template_by_id(
        self,
        org_id: UUID,
        template_id: UUID,
    ) -> PipelineTemplate | None:
        """Get a pipeline template by ID scoped to an organization."""
        stmt = select(PipelineTemplate).where(
            and_(
                PipelineTemplate.id == template_id,
                PipelineTemplate.organization_id == org_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_template(
        self,
        org_id: UUID,
        name: str,
        version: str,
        definition: dict,
        *,
        is_active: bool = True,
    ) -> PipelineTemplate:
        """Create a new pipeline template with schema validation.

        Args:
            org_id: Organization ID
            name: Template name
            version: Template version (e.g., "1.0.0")
            definition: Pipeline definition with methods and dependencies

        Returns:
            Created PipelineTemplate

        Raises:
            ValueError: If definition is invalid or methods don't exist
        """
        await self._validate_definition(definition)

        return await self._create_template_record(
            org_id=org_id,
            name=name,
            version=version,
            definition=definition,
            is_active=is_active,
        )

    async def deactivate_template(
        self,
        org_id: UUID,
        template_id: UUID,
    ) -> PipelineTemplate:
        """Deactivate an existing template version."""
        template = await self.get_template_by_id(org_id, template_id)
        if template is None:
            raise ValueError(f"Template {template_id} not found")

        template.is_active = False
        template.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def clone_template(
        self,
        org_id: UUID,
        source_template_id: UUID,
        version: str,
        *,
        name: str | None = None,
        definition: dict[str, Any] | None = None,
        deactivate_source: bool = True,
    ) -> PipelineTemplate:
        """Create a new template version from an existing template."""
        source = await self.get_template_by_id(org_id, source_template_id)
        if source is None:
            raise ValueError(f"Template {source_template_id} not found")

        new_name = name or source.name
        new_definition = deepcopy(definition if definition is not None else source.definition)
        await self._validate_definition(new_definition)

        template = await self._create_template_record(
            org_id=org_id,
            name=new_name,
            version=version,
            definition=new_definition,
            is_active=True,
            commit=False,
        )

        if deactivate_source:
            if new_name == source.name:
                stmt = select(PipelineTemplate).where(
                    and_(
                        PipelineTemplate.organization_id == org_id,
                        PipelineTemplate.name == new_name,
                        PipelineTemplate.id != template.id,
                        PipelineTemplate.is_active,
                    )
                )
                result = await self.db.execute(stmt)
                for existing in result.scalars().all():
                    existing.is_active = False
                    existing.updated_at = datetime.utcnow()
            else:
                source.is_active = False
                source.updated_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def sync_default_templates(self, org_id: UUID) -> list[PipelineTemplate]:
        """Ensure seeded default templates exist and are active for an organization."""
        synced: list[PipelineTemplate] = []

        for spec in get_seed_template_specs():
            stmt = select(PipelineTemplate).where(
                and_(
                    PipelineTemplate.organization_id == org_id,
                    PipelineTemplate.name == spec["name"],
                    PipelineTemplate.version == spec["version"],
                )
            )
            result = await self.db.execute(stmt)
            template = result.scalar_one_or_none()

            if template is None:
                await self._validate_definition(spec["definition"])
                template = await self._create_template_record(
                    org_id=org_id,
                    name=spec["name"],
                    version=spec["version"],
                    definition=deepcopy(spec["definition"]),
                    is_active=True,
                    commit=False,
                )
            else:
                template.is_active = True
                template.updated_at = datetime.utcnow()
                # Refresh seeded definition so metadata (e.g. deprecation flags) stays current.
                await self._validate_definition(spec["definition"])
                template.definition = deepcopy(spec["definition"])

            stmt = select(PipelineTemplate).where(
                and_(
                    PipelineTemplate.organization_id == org_id,
                    PipelineTemplate.name == spec["name"],
                    PipelineTemplate.id != template.id,
                    PipelineTemplate.is_active,
                )
            )
            other_versions = await self.db.execute(stmt)
            for existing in other_versions.scalars().all():
                existing.is_active = False
                existing.updated_at = datetime.utcnow()

            synced.append(template)

        await self.db.commit()
        for template in synced:
            await self.db.refresh(template)
        return synced

    def get_catalog(self) -> list[dict[str, Any]]:
        """Return the canonical method catalog for UI/template builders."""
        return get_method_catalog()

    def get_seed_template_definitions(self) -> list[dict[str, Any]]:
        """Return seeded template specs for display/debugging."""
        return get_seed_template_specs()

    @staticmethod
    def _parameter_value_provided(value: Any) -> bool:
        """Return whether a schema value should count as present."""
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    def apply_parameter_schema_constraints(
        self,
        parameter_schema: dict[str, Any] | None,
        parameters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Apply conditional schema-enforced const values until the parameter set stabilizes."""
        normalized = dict(parameters or {})
        if not isinstance(parameter_schema, dict):
            return normalized

        for _ in range(8):
            changed = False
            for conditional_rule in parameter_schema.get("allOf", []):
                if not isinstance(conditional_rule, dict):
                    continue
                if_schema = conditional_rule.get("if")
                then_schema = conditional_rule.get("then")
                if not isinstance(if_schema, dict) or not isinstance(then_schema, dict):
                    continue
                if not self._matches_schema_condition(if_schema, normalized):
                    continue

                then_properties = then_schema.get("properties", {})
                if not isinstance(then_properties, dict):
                    continue

                for param_name, param_spec in then_properties.items():
                    if not isinstance(param_spec, dict) or "const" not in param_spec:
                        continue
                    forced_value = deepcopy(param_spec["const"])
                    if normalized.get(param_name) != forced_value:
                        normalized[param_name] = forced_value
                        changed = True
            if not changed:
                break

        return normalized

    def _collect_required_parameters(
        self,
        parameter_schema: dict[str, Any],
        parameters: dict[str, Any],
    ) -> list[str]:
        """Collect required parameters after conditional rules are applied."""
        required_params = list(parameter_schema.get("required", []))
        for conditional_rule in parameter_schema.get("allOf", []):
            if not isinstance(conditional_rule, dict):
                continue
            if_schema = conditional_rule.get("if")
            then_schema = conditional_rule.get("then")
            if not isinstance(if_schema, dict) or not isinstance(then_schema, dict):
                continue
            if self._matches_schema_condition(if_schema, parameters):
                for param in then_schema.get("required", []):
                    if param not in required_params:
                        required_params.append(param)
        return required_params

    async def get_template(
        self,
        org_id: UUID,
        name: str,
        version: str | None = None,
    ) -> PipelineTemplate | None:
        """Get a pipeline template by name and version.

        If version is not specified, returns the latest active version.

        Args:
            org_id: Organization ID for scoping
            name: Template name
            version: Template version (optional, defaults to latest active)

        Returns:
            PipelineTemplate if found, None otherwise
        """
        if version is not None:
            # Get specific version
            stmt = select(PipelineTemplate).where(
                and_(
                    PipelineTemplate.organization_id == org_id,
                    PipelineTemplate.name == name,
                    PipelineTemplate.version == version,
                )
            )
        else:
            # Get latest active version
            stmt = (
                select(PipelineTemplate)
                .where(
                    and_(
                        PipelineTemplate.organization_id == org_id,
                        PipelineTemplate.name == name,
                        PipelineTemplate.is_active,
                    )
                )
                .order_by(desc(PipelineTemplate.created_at))
                .limit(1)
            )

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        org_id: UUID,
        name: str | None = None,
        is_active: bool = True,
    ) -> list[PipelineTemplate]:
        """List pipeline templates with optional filtering.

        Args:
            org_id: Organization ID for scoping
            name: Optional template name filter
            is_active: Filter by active status (default: True)

        Returns:
            List of PipelineTemplates
        """
        stmt = select(PipelineTemplate).where(
            and_(
                PipelineTemplate.organization_id == org_id,
                PipelineTemplate.is_active == is_active,
            )
        )

        if name is not None:
            stmt = stmt.where(PipelineTemplate.name == name)

        stmt = stmt.order_by(desc(PipelineTemplate.created_at))

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def validate_parameters(
        self,
        template_id: UUID,
        parameters: dict,
    ) -> tuple[bool, str | None]:
        """Validate run parameters against template schema.

        Args:
            template_id: Template ID
            parameters: Parameters to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get template
        stmt = select(PipelineTemplate).where(PipelineTemplate.id == template_id)
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()

        if template is None:
            return False, f"Template {template_id} not found"

        # Get parameter schema from definition
        definition = template.definition
        parameter_schema = definition.get("parameter_schema", {})

        # If no schema defined, accept any parameters
        if not parameter_schema:
            return True, None

        parameters = self.apply_parameter_schema_constraints(parameter_schema, parameters)

        # Validate required parameters
        required_params = self._collect_required_parameters(parameter_schema, parameters)
        for param in required_params:
            if not self._parameter_value_provided(parameters.get(param)):
                return False, f"Required parameter '{param}' is missing"

        # Validate parameter types
        properties = parameter_schema.get("properties", {})
        for param_name, param_value in parameters.items():
            if param_name in properties:
                param_spec = properties[param_name]
                expected_type = param_spec.get("type")

                if expected_type:
                    # Basic type validation
                    if expected_type == "string" and not isinstance(param_value, str):
                        return False, f"Parameter '{param_name}' must be a string"
                    elif expected_type == "number" and not isinstance(param_value, (int, float)):
                        return False, f"Parameter '{param_name}' must be a number"
                    elif expected_type == "integer" and not isinstance(param_value, int):
                        return False, f"Parameter '{param_name}' must be an integer"
                    elif expected_type == "boolean" and not isinstance(param_value, bool):
                        return False, f"Parameter '{param_name}' must be a boolean"
                    elif expected_type == "array" and not isinstance(param_value, list):
                        return False, f"Parameter '{param_name}' must be an array"
                    elif expected_type == "object" and not isinstance(param_value, dict):
                        return False, f"Parameter '{param_name}' must be an object"

                # Validate min/max for numbers
                if expected_type in ("number", "integer"):
                    if "minimum" in param_spec and param_value < param_spec["minimum"]:
                        return (
                            False,
                            f"Parameter '{param_name}' must be >= {param_spec['minimum']}",
                        )
                    if "maximum" in param_spec and param_value > param_spec["maximum"]:
                        return (
                            False,
                            f"Parameter '{param_name}' must be <= {param_spec['maximum']}",
                        )

                # Validate enum values
                if "enum" in param_spec and param_value not in param_spec["enum"]:
                    return (
                        False,
                        f"Parameter '{param_name}' must be one of {param_spec['enum']}",
                    )

        return True, None

    def _matches_schema_condition(
        self,
        if_schema: dict[str, Any],
        parameters: dict[str, Any],
    ) -> bool:
        """Evaluate a narrow subset of JSONSchema if/then conditions."""
        properties = if_schema.get("properties", {})
        if not isinstance(properties, dict):
            return False

        required = if_schema.get("required", [])
        if isinstance(required, list):
            for param_name in required:
                if not isinstance(param_name, str):
                    return False
                if not self._parameter_value_provided(parameters.get(param_name)):
                    return False

        for param_name, param_spec in properties.items():
            if not isinstance(param_spec, dict):
                return False
            if "const" in param_spec and parameters.get(param_name) != param_spec["const"]:
                return False

        return True

    async def resolve_methods(self, template_definition: dict) -> list[str]:
        """Resolve and validate that all methods in the template exist.

        Args:
            template_definition: Pipeline definition with methods list

        Returns:
            List of method names

        Raises:
            ValueError: If any method doesn't exist in the registry
        """
        methods = template_definition.get("methods", [])

        if not methods:
            raise ValueError("Template must define at least one method")

        # Catalog (UI / templates) plus worker-executable registry and aliases so validation
        # matches Temporal step resolution (see zerna_contracts.pipeline_methods).
        known_methods = set(METHOD_CATALOG_BY_NAME)
        known_methods.update(METHOD_REGISTRY)
        known_methods.update(METHOD_ALIASES)
        known_methods.update(METHOD_ALIASES.values())

        # Validate each method exists
        resolved_methods: list[str] = []
        for method in methods:
            method_name = method if isinstance(method, str) else method.get("name")
            if not isinstance(method_name, str):
                raise ValueError(f"Invalid method entry in template: {method!r}")

            if method_name not in known_methods:
                raise ValueError(
                    f"Method '{method_name}' not found in method registry. "
                    f"Available methods: {sorted(known_methods)}"
                )
            resolved_methods.append(method_name)

        return resolved_methods
