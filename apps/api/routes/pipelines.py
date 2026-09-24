"""Pipeline API routes."""

from copy import deepcopy
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User, organization_users
from apps.api.models.pipeline import PipelineTemplate
from apps.api.schemas.pipeline import (
    ClonePipelineTemplateRequest,
    CreatePipelineTemplateRequest,
    PipelineCatalogResponse,
    PipelineMethodCatalogEntry,
    PipelineTemplateResponse,
    ValidateParametersRequest,
    ValidateParametersResponse,
)
from apps.api.services.pipeline_catalog import (
    merge_template_presentation_metadata,
    normalize_pipeline_template_definition,
)
from apps.api.services.pipeline_service import PipelineService

router = APIRouter(prefix="/v1/pipelines", tags=["pipelines"])


def _pipeline_template_response(template: PipelineTemplate) -> PipelineTemplateResponse:
    """Return API template with dependency edges merged from the current catalog (read-time only)."""
    base = PipelineTemplateResponse.model_validate(template)
    norm = normalize_pipeline_template_definition(deepcopy(base.definition))
    norm = merge_template_presentation_metadata(norm, name=template.name, version=template.version)
    meta = norm.get("metadata") or {}
    return base.model_copy(
        update={
            "definition": norm,
            "deprecated": bool(meta.get("deprecated", False)),
            "visible_in_picker": bool(meta.get("visible_in_picker", True)),
            "recommended": bool(meta.get("recommended", False)),
            "template_family": meta.get("template_family")
            if isinstance(meta.get("template_family"), str)
            else None,
        }
    )


async def get_pipeline_service(db: AsyncSession = Depends(get_db)) -> PipelineService:
    """Get PipelineService dependency."""
    return PipelineService(db=db)


async def get_user_organization(user: User, db: AsyncSession) -> UUID:
    """Get user's organization ID.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        Organization ID

    Raises:
        HTTPException: 403 if user not member of any organization
    """
    stmt = select(organization_users.c.organization_id).where(
        organization_users.c.user_id == user.id
    )
    result = await db.execute(stmt)
    org_id = result.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    return UUID(str(org_id))


@router.post(
    "",
    response_model=PipelineTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create pipeline template",
    description="Create a new pipeline template with schema validation",
)
async def create_pipeline_template(
    request: CreatePipelineTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> PipelineTemplateResponse:
    """Create a new pipeline template.

    Args:
        request: Create template request
        user: Current authenticated user
        db: Database session
        pipeline_service: Pipeline service

    Returns:
        Created pipeline template

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 403 if user not member of organization
    """
    org_id = await get_user_organization(user, db)

    try:
        template = await pipeline_service.create_template(
            org_id=org_id,
            name=request.name,
            version=request.version,
            definition=request.definition,
        )

        return _pipeline_template_response(template)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create pipeline template: {str(e)}",
        )


@router.get(
    "/catalog/methods",
    response_model=PipelineCatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="Get pipeline catalog",
    description="List canonical pipeline methods for template building",
)
async def get_pipeline_catalog(
    _user: User = Depends(get_current_user),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> PipelineCatalogResponse:
    """Return pipeline method metadata used by the template builder."""
    methods = [
        PipelineMethodCatalogEntry.model_validate(entry) for entry in pipeline_service.get_catalog()
    ]
    return PipelineCatalogResponse(methods=methods)


@router.post(
    "/catalog/sync-defaults",
    response_model=list[PipelineTemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="Sync default templates",
    description="Ensure seeded pipeline templates exist for the current organization",
)
async def sync_default_templates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> list[PipelineTemplateResponse]:
    """Create or activate seeded default templates for the current organization."""
    org_id = await get_user_organization(user, db)
    templates = await pipeline_service.sync_default_templates(org_id)
    return [_pipeline_template_response(t) for t in templates]


@router.get(
    "",
    response_model=list[PipelineTemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="List pipeline templates",
    description="List pipeline templates with optional name filter",
)
async def list_pipeline_templates(
    name: str | None = Query(None, description="Filter by template name"),
    is_active: bool = Query(True, description="Filter by active status"),
    include_hidden_in_picker: bool = Query(
        False,
        description=(
            "When false (default), omit templates with visible_in_picker=false "
            "(e.g. deprecated legacy seeds). Fetch by ID still works. "
            "Set true for admin template management UIs."
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> list[PipelineTemplateResponse]:
    """List pipeline templates.

    Args:
        name: Optional template name filter
        is_active: Filter by active status
        include_hidden_in_picker: Include templates hidden from the run-creation picker
        user: Current authenticated user
        db: Database session
        pipeline_service: Pipeline service

    Returns:
        List of pipeline templates

    Raises:
        HTTPException: 403 if user not member of organization
    """
    org_id = await get_user_organization(user, db)

    templates = await pipeline_service.list_templates(
        org_id=org_id,
        name=name,
        is_active=is_active,
    )

    responses = [_pipeline_template_response(t) for t in templates]
    if not include_hidden_in_picker:
        responses = [r for r in responses if r.visible_in_picker]
    return responses


@router.get(
    "/{template_id}",
    response_model=PipelineTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get pipeline template",
    description="Get pipeline template by ID",
)
async def get_pipeline_template(
    template_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> PipelineTemplateResponse:
    """Get pipeline template by ID.

    Args:
        template_id: Template ID
        user: Current authenticated user
        db: Database session
        pipeline_service: Pipeline service

    Returns:
        Pipeline template

    Raises:
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if template not found
    """
    org_id = await get_user_organization(user, db)

    template = await pipeline_service.get_template_by_id(org_id, template_id)

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline template {template_id} not found",
        )

    return _pipeline_template_response(template)


@router.post(
    "/{template_id}/clone",
    response_model=PipelineTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone pipeline template",
    description="Create a new template version from an existing template",
)
async def clone_pipeline_template(
    template_id: UUID,
    request: ClonePipelineTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> PipelineTemplateResponse:
    """Clone an existing template into a new version."""
    org_id = await get_user_organization(user, db)

    try:
        template = await pipeline_service.clone_template(
            org_id=org_id,
            source_template_id=template_id,
            version=request.version,
            name=request.name,
            definition=request.definition,
            deactivate_source=request.deactivate_source,
        )
        return _pipeline_template_response(template)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clone pipeline template: {str(e)}",
        )


@router.post(
    "/{template_id}/deactivate",
    response_model=PipelineTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate pipeline template",
    description="Deactivate a template version without deleting it",
)
async def deactivate_pipeline_template(
    template_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> PipelineTemplateResponse:
    """Deactivate a specific template version."""
    org_id = await get_user_organization(user, db)

    try:
        template = await pipeline_service.deactivate_template(org_id, template_id)
        return _pipeline_template_response(template)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/{template_id}/validate",
    response_model=ValidateParametersResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate parameters",
    description="Validate run parameters against template schema",
)
async def validate_parameters(
    template_id: UUID,
    request: ValidateParametersRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
) -> ValidateParametersResponse:
    """Validate parameters against template schema.

    Args:
        template_id: Template ID
        request: Validation request with parameters
        user: Current authenticated user
        db: Database session
        pipeline_service: Pipeline service

    Returns:
        Validation result

    Raises:
        HTTPException: 403 if user not member of organization
        HTTPException: 404 if template not found
    """
    org_id = await get_user_organization(user, db)

    # Verify template belongs to user's organization
    from apps.api.models.pipeline import PipelineTemplate

    stmt = select(PipelineTemplate).where(
        PipelineTemplate.id == template_id,
        PipelineTemplate.organization_id == org_id,
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline template {template_id} not found",
        )

    # Validate parameters
    is_valid, error_message = await pipeline_service.validate_parameters(
        template_id=template_id,
        parameters=request.parameters,
    )

    return ValidateParametersResponse(valid=is_valid, error=error_message)
