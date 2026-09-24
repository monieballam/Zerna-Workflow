"""Pipeline API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PipelineTemplateResponse(BaseModel):
    """Pipeline template response schema."""

    id: UUID
    organization_id: UUID
    name: str
    version: str
    definition: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Presentation (mirrors definition.metadata; convenient for dashboards)
    deprecated: bool = False
    visible_in_picker: bool = True
    recommended: bool = False
    template_family: str | None = None

    class Config:
        from_attributes = True


class CreatePipelineTemplateRequest(BaseModel):
    """Create pipeline template request schema."""

    name: str = Field(..., min_length=1, max_length=255, description="Template name")
    version: str = Field(
        ..., min_length=1, max_length=50, description="Template version (e.g., '1.0.0')"
    )
    definition: dict[str, Any] = Field(
        ..., description="Pipeline definition with methods and dependencies"
    )


class ClonePipelineTemplateRequest(BaseModel):
    """Clone an existing pipeline template into a new version."""

    version: str = Field(..., min_length=1, max_length=50, description="New template version")
    name: str | None = Field(
        None, min_length=1, max_length=255, description="Optional new template name"
    )
    definition: dict[str, Any] | None = Field(
        None, description="Optional replacement definition for the cloned version"
    )
    deactivate_source: bool = Field(
        True,
        description="Deactivate the previous active version after cloning",
    )


class ValidateParametersRequest(BaseModel):
    """Validate parameters request schema."""

    parameters: dict[str, Any] = Field(
        ..., description="Parameters to validate against template schema"
    )


class ValidateParametersResponse(BaseModel):
    """Validate parameters response schema."""

    valid: bool = Field(..., description="Whether parameters are valid")
    error: str | None = Field(None, description="Error message if invalid")


class PipelineMethodCatalogEntry(BaseModel):
    """Method metadata used by the template builder UI."""

    name: str
    label: str
    description: str
    order: int
    default_selected: bool = True
    enabled_if: str | None = None


class PipelineCatalogResponse(BaseModel):
    """Catalog of available pipeline methods."""

    methods: list[PipelineMethodCatalogEntry]
