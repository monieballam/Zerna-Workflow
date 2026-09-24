"""Permission decorators for endpoint authorization."""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any
from uuid import UUID

from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import Permission
from fastapi import HTTPException, status

from apps.api.models.organization import User
from apps.api.services.auth_service import AuthService


def require_org_permission(
    permission: Permission,
    org_id_key: str = "organization_id",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to require a specific permission in an organization.

    Args:
        permission: Required permission
        org_id_key: Key in kwargs to extract organization_id from

    Returns:
        Decorator function

    Example:
        @require_org_permission(Permission.DATASET_CREATE)
        async def create_dataset(organization_id: UUID, ...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract dependencies from kwargs
            user: User | None = kwargs.get("user")
            auth_service: AuthService | None = kwargs.get("auth_service")
            organization_id: UUID | None = kwargs.get(org_id_key)

            if user is None or auth_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Missing required dependencies (user, auth_service)",
                )

            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required parameter: {org_id_key}",
                )

            # Check permission
            has_permission = await auth_service.check_user_permission(
                user.id, organization_id, permission
            )

            if not has_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User does not have required permission: {permission.value}",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_admin(
    org_id_key: str = "organization_id",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to require admin role in an organization.

    Args:
        org_id_key: Key in kwargs to extract organization_id from

    Returns:
        Decorator function

    Example:
        @require_admin()
        async def delete_organization(organization_id: UUID, ...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract dependencies from kwargs
            user: User | None = kwargs.get("user")
            auth_service: AuthService | None = kwargs.get("auth_service")
            organization_id: UUID | None = kwargs.get(org_id_key)

            if user is None or auth_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Missing required dependencies (user, auth_service)",
                )

            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required parameter: {org_id_key}",
                )

            # Check role
            role = await auth_service.get_user_role_in_organization(user.id, organization_id)

            if role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin role required for this operation",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_member(
    org_id_key: str = "organization_id",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to require at least member role in an organization.

    Args:
        org_id_key: Key in kwargs to extract organization_id from

    Returns:
        Decorator function

    Example:
        @require_member()
        async def create_dataset(organization_id: UUID, ...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract dependencies from kwargs
            user: User | None = kwargs.get("user")
            auth_service: AuthService | None = kwargs.get("auth_service")
            organization_id: UUID | None = kwargs.get(org_id_key)

            if user is None or auth_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Missing required dependencies (user, auth_service)",
                )

            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required parameter: {org_id_key}",
                )

            # Check role
            role = await auth_service.get_user_role_in_organization(user.id, organization_id)

            if role not in [UserRole.ADMIN, UserRole.MEMBER]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Member role or higher required for this operation",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_viewer(
    org_id_key: str = "organization_id",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to require at least viewer role (any member) in an organization.

    Args:
        org_id_key: Key in kwargs to extract organization_id from

    Returns:
        Decorator function

    Example:
        @require_viewer()
        async def get_dataset(organization_id: UUID, ...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract dependencies from kwargs
            user: User | None = kwargs.get("user")
            auth_service: AuthService | None = kwargs.get("auth_service")
            organization_id: UUID | None = kwargs.get(org_id_key)

            if user is None or auth_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Missing required dependencies (user, auth_service)",
                )

            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required parameter: {org_id_key}",
                )

            # Check if user is member of organization (any role)
            is_member = await auth_service.is_member_of_organization(user.id, organization_id)

            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not a member of this organization",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
