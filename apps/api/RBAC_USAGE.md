# Role-Based Access Control (RBAC) Usage Guide

This document explains how to use the RBAC system implemented in the Zerna API.

## Overview

The RBAC system provides:

- **Role hierarchy**: admin > member > viewer
- **Permission checking**: Fine-grained permissions for different resource types
- **Organization membership verification**: Ensures users can only access resources in their organizations
- **Middleware and decorators**: Easy-to-use authentication and authorization

## Components

### 1. Permission Definitions (`zerna_contracts.permissions`)

```python
from zerna_contracts.permissions import Permission, ResourceType, Action

# Example permissions
Permission.DATASET_CREATE  # Create datasets
Permission.DATASET_READ    # Read datasets
Permission.DATASET_DELETE  # Delete datasets
Permission.RUN_CREATE      # Create runs
Permission.ANNOTATION_APPROVE  # Approve annotations
```

### 2. Role Permissions (`ROLE_PERMISSIONS`)

Each role has a set of permissions:

- **Admin**: All permissions (create, read, update, delete, approve, manage users)
- **Member**: Create and manage own resources (datasets, runs, annotations)
- **Viewer**: Read-only access to all resources

### 3. Middleware (`apps.api.middleware.auth`)

#### `get_current_user`

Extracts and validates JWT token, returns authenticated user.

```python
from fastapi import Depends
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User

@router.get("/v1/datasets")
async def list_datasets(
    user: User = Depends(get_current_user),
):
    # user is authenticated
    pass
```

#### `require_organization_membership`

Verifies user is a member of the specified organization.

```python
from fastapi import Depends
from uuid import UUID
from apps.api.middleware.auth import get_current_user, require_organization_membership

@router.get("/v1/organizations/{organization_id}/datasets")
async def list_datasets(
    organization_id: UUID,
    user: User = Depends(get_current_user),
    _: None = Depends(require_organization_membership),
):
    # user is a member of organization_id
    pass
```

### 4. AuthService Methods

#### `check_permission(role, permission)`

Check if a role has a specific permission.

```python
from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import Permission

# Check if member can create datasets
has_permission = auth_service.check_permission(
    UserRole.MEMBER,
    Permission.DATASET_CREATE
)
# Returns: True
```

#### `check_user_permission(user_id, organization_id, permission)`

Check if a user has a specific permission in an organization.

```python
has_permission = await auth_service.check_user_permission(
    user.id,
    organization_id,
    Permission.DATASET_DELETE
)
```

#### `is_member_of_organization(user_id, organization_id)`

Check if user is a member of an organization.

```python
is_member = await auth_service.is_member_of_organization(
    user.id,
    organization_id
)
```

#### `get_user_role_in_organization(user_id, organization_id)`

Get user's role in a specific organization.

```python
role = await auth_service.get_user_role_in_organization(
    user.id,
    organization_id
)
# Returns: UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER, or None
```

## Usage Examples

### Example 1: Simple Authentication

```python
from fastapi import APIRouter, Depends
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])

@router.get("/")
async def list_datasets(
    user: User = Depends(get_current_user),
):
    """List all datasets accessible to the user."""
    # User is authenticated
    # Implement dataset listing logic
    return {"datasets": []}
```

### Example 2: Organization Membership Check

```python
from fastapi import APIRouter, Depends
from uuid import UUID
from apps.api.middleware.auth import get_current_user, require_organization_membership
from apps.api.models.organization import User

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])

@router.get("/{organization_id}/datasets")
async def list_org_datasets(
    organization_id: UUID,
    user: User = Depends(get_current_user),
    _: None = Depends(require_organization_membership),
):
    """List datasets in a specific organization."""
    # User is authenticated AND is a member of organization_id
    return {"datasets": []}
```

### Example 3: Permission-Based Authorization

```python
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from apps.api.dependencies import get_auth_service
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.services.auth_service import AuthService
from zerna_contracts.permissions import Permission

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])

@router.delete("/{organization_id}/datasets/{dataset_id}")
async def delete_dataset(
    organization_id: UUID,
    dataset_id: UUID,
    user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Delete a dataset (requires delete permission)."""
    # Check if user has delete permission
    has_permission = await auth_service.check_user_permission(
        user.id,
        organization_id,
        Permission.DATASET_DELETE
    )

    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission to delete datasets"
        )

    # Implement dataset deletion logic
    return {"message": "Dataset deleted"}
```

### Example 4: Role-Based Authorization

```python
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from apps.api.dependencies import get_auth_service
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.services.auth_service import AuthService
from zerna_contracts.enums import UserRole

router = APIRouter(prefix="/v1/organizations", tags=["organizations"])

@router.post("/{organization_id}/users")
async def add_user_to_organization(
    organization_id: UUID,
    user_email: str,
    user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Add a user to an organization (admin only)."""
    # Check if user is admin in organization
    role = await auth_service.get_user_role_in_organization(
        user.id,
        organization_id
    )

    if role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can add users to organizations"
        )

    # Implement user addition logic
    return {"message": "User added"}
```

### Example 5: Multi-Organization Access

```python
from fastapi import APIRouter, Depends
from apps.api.dependencies import get_auth_service
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import User
from apps.api.services.auth_service import AuthService

router = APIRouter(prefix="/v1/users", tags=["users"])

@router.get("/me/organizations")
async def get_my_organizations(
    user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """Get all organizations the current user belongs to."""
    orgs = await auth_service.get_user_organizations(user.id)

    return {
        "organizations": [
            {
                "organization_id": str(org_id),
                "role": role.value
            }
            for org_id, role in orgs
        ]
    }
```

## Permission Matrix

| Resource            | Admin | Member | Viewer |
| ------------------- | ----- | ------ | ------ |
| Organization Read   | ✓     | ✓      | ✓      |
| Organization Update | ✓     | ✗      | ✗      |
| Organization Delete | ✓     | ✗      | ✗      |
| Manage Users        | ✓     | ✗      | ✗      |
| Dataset Create      | ✓     | ✓      | ✗      |
| Dataset Read        | ✓     | ✓      | ✓      |
| Dataset Update      | ✓     | ✓      | ✗      |
| Dataset Delete      | ✓     | ✓      | ✗      |
| Run Create          | ✓     | ✓      | ✗      |
| Run Read            | ✓     | ✓      | ✓      |
| Run Cancel          | ✓     | ✓      | ✗      |
| Annotation Create   | ✓     | ✓      | ✗      |
| Annotation Read     | ✓     | ✓      | ✓      |
| Annotation Update   | ✓     | ✓      | ✗      |
| Annotation Approve  | ✓     | ✗      | ✗      |
| Artifact Read       | ✓     | ✓      | ✓      |
| Audit Read          | ✓     | ✓      | ✓      |

## Best Practices

1. **Always authenticate first**: Use `get_current_user` as the first dependency
2. **Check organization membership**: Use `require_organization_membership` or manual checks
3. **Verify permissions**: Use `check_user_permission` for fine-grained access control
4. **Return appropriate HTTP status codes**:
   - 401 Unauthorized: Invalid or missing token
   - 403 Forbidden: Valid token but insufficient permissions
   - 404 Not Found: Resource doesn't exist or user has no access
5. **Log authorization failures**: For security auditing
6. **Use role hierarchy**: Leverage the fact that admin > member > viewer

## Testing

See `apps/api/tests/test_rbac.py` and `apps/api/tests/test_middleware.py` for comprehensive test examples.
