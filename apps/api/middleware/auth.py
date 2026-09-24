"""Authentication and authorization middleware."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import Permission
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.dependencies import get_auth_service, get_db
from apps.api.models.organization import User
from apps.api.services.auth_service import AuthService

# HTTP Bearer token scheme (optional so AUTH_DISABLED can skip credentials)
security = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentOrganizationContext:
    """Current organization context used by the app shell."""

    organization_id: UUID
    organization_name: str
    role: UserRole


async def _resolve_bootstrap_user(db: AsyncSession) -> User:
    """Return the configured bootstrap admin when auth is disabled."""
    settings = get_settings()
    email = (settings.bootstrap_admin_email or "admin@zerna.local").strip().lower()
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AUTH_DISABLED is set but bootstrap admin "
                f"{email} was not found. Restart the API so bootstrap can create it."
            ),
        )
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Get current authenticated user from JWT token.

    When ``AUTH_DISABLED`` is true and no Bearer token is provided, returns the
    bootstrap admin so local visualization workflows can skip sign-in.

    Args:
        credentials: HTTP Bearer credentials
        db: Database session
        auth_service: Authentication service

    Returns:
        User object

    Raises:
        HTTPException: 401 if token is invalid or user not found
    """
    settings = get_settings()

    if credentials is None:
        if settings.auth_disabled:
            return await _resolve_bootstrap_user(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token
    token = credentials.credentials

    # Verify token
    payload = auth_service.verify_token(token, token_type="access")

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    user_id = UUID(payload.sub)
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_permission(
    permission: Permission,
    organization_id_param: str = "organization_id",
) -> Callable[..., Awaitable[None]]:
    """Decorator factory for requiring specific permissions.

    Creates a dependency that checks if the current user has the required
    permission in the specified organization.

    Args:
        permission: Required permission
        organization_id_param: Name of the path/query parameter containing organization_id

    Returns:
        Dependency function that validates permission

    Example:
        @router.post("/v1/datasets")
        async def create_dataset(
            request: CreateDatasetRequest,
            user: User = Depends(get_current_user),
            _: None = Depends(require_permission(Permission.DATASET_CREATE, "organization_id"))
        ):
            ...
    """

    async def permission_checker(
        user: User = Depends(get_current_user),
        auth_service: AuthService = Depends(get_auth_service),
        organization_id: UUID | None = None,
    ) -> None:
        """Check if user has required permission.

        Args:
            user: Current authenticated user
            auth_service: Authentication service
            organization_id: Organization ID from path/query parameter

        Raises:
            HTTPException: 403 if user lacks permission or is not org member
        """
        if organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required parameter: {organization_id_param}",
            )

        # Check if user is member of organization
        is_member = await auth_service.is_member_of_organization(user.id, organization_id)

        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a member of this organization",
            )

        # Check if user has required permission
        has_permission = await auth_service.check_user_permission(
            user.id, organization_id, permission
        )

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have required permission: {permission.value}",
            )

    return permission_checker


async def require_organization_membership(
    organization_id: UUID,
    user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    """Require that user is a member of the specified organization.

    Args:
        organization_id: Organization ID
        user: Current authenticated user
        auth_service: Authentication service

    Raises:
        HTTPException: 403 if user is not a member
    """
    is_member = await auth_service.is_member_of_organization(user.id, organization_id)

    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this organization",
        )


async def get_current_org_context(
    user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> CurrentOrganizationContext:
    """Return the primary organization context used by the current session."""
    membership = await auth_service.get_primary_organization_membership(user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    return CurrentOrganizationContext(
        organization_id=membership.organization_id,
        organization_name=membership.organization_name,
        role=membership.role,
    )


async def require_current_admin(
    org_context: CurrentOrganizationContext = Depends(get_current_org_context),
) -> CurrentOrganizationContext:
    """Require admin role in the current organization context."""
    if org_context.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation",
        )
    return org_context
