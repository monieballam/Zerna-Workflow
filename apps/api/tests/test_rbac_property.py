"""Property-based tests for role-based access control (RBAC).

**Validates: Requirements 1.2, 1.3, 1.4**
"""

from uuid import uuid4

import pytest
from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import ROLE_PERMISSIONS, Permission
from fakeredis import aioredis as fakeredis
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base
from apps.api.models.organization import Organization, User, organization_users
from apps.api.services.auth_service import AuthService

# Role hierarchy: admin > member > viewer
ROLE_HIERARCHY = {
    UserRole.ADMIN: 3,
    UserRole.MEMBER: 2,
    UserRole.VIEWER: 1,
}


async def create_test_db_and_redis():
    """Create test database and Redis instances."""
    # Create async engine
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create fake Redis
    redis = fakeredis.FakeRedis(decode_responses=False)

    return async_session_factory, redis, engine


@st.composite
def role_and_permission(draw):
    """Generate a role and permission combination."""
    role = draw(st.sampled_from([UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER]))
    permission = draw(st.sampled_from(list(Permission)))
    return role, permission


@pytest.mark.asyncio
@given(data=role_and_permission())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
async def test_property_role_hierarchy_permission_inheritance(data):
    """Property: For any role and permission, if a lower role has a permission,
    all higher roles should also have that permission (role hierarchy).

    Role hierarchy: admin > member > viewer

    This property verifies that:
    - If viewer has permission P, then member and admin must also have P
    - If member has permission P, then admin must also have P
    - If admin has permission P, no constraint on lower roles

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    role, permission = data

    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Check if the current role has the permission
            has_permission = auth_service.check_permission(role, permission)

            # Property: If a lower role has a permission, all higher roles must have it
            if role == UserRole.VIEWER and has_permission:
                # If viewer has permission, member and admin must also have it
                member_has = auth_service.check_permission(UserRole.MEMBER, permission)
                admin_has = auth_service.check_permission(UserRole.ADMIN, permission)

                assert member_has, (
                    f"Role hierarchy violation: VIEWER has {permission.value}, but MEMBER does not"
                )
                assert admin_has, (
                    f"Role hierarchy violation: VIEWER has {permission.value}, but ADMIN does not"
                )

            elif role == UserRole.MEMBER and has_permission:
                # If member has permission, admin must also have it
                admin_has = auth_service.check_permission(UserRole.ADMIN, permission)

                assert admin_has, (
                    f"Role hierarchy violation: MEMBER has {permission.value}, but ADMIN does not"
                )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@st.composite
def two_roles(draw):
    """Generate two different roles for comparison."""
    roles = [UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER]
    role1 = draw(st.sampled_from(roles))
    role2 = draw(st.sampled_from(roles))
    # Ensure roles are different
    assume(role1 != role2)
    return role1, role2


@pytest.mark.asyncio
@given(data=two_roles())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20)
async def test_property_higher_role_has_more_permissions(data):
    """Property: For any two roles in the hierarchy, the higher role should have
    at least as many permissions as the lower role (superset property).

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    role1, role2 = data

    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Determine which role is higher
            if ROLE_HIERARCHY[role1] > ROLE_HIERARCHY[role2]:
                higher_role = role1
                lower_role = role2
            else:
                higher_role = role2
                lower_role = role1

            # Get permissions for both roles
            higher_permissions = ROLE_PERMISSIONS.get(higher_role.value, set())
            lower_permissions = ROLE_PERMISSIONS.get(lower_role.value, set())

            # Property: Higher role permissions should be a superset of lower role permissions
            assert lower_permissions.issubset(higher_permissions), (
                f"Role hierarchy violation: {higher_role.value} (higher) does not have "
                f"all permissions of {lower_role.value} (lower). "
                f"Missing permissions: {lower_permissions - higher_permissions}"
            )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@st.composite
def user_org_role_permission(draw):
    """Generate user, organization, role, and permission for testing."""
    role = draw(st.sampled_from([UserRole.ADMIN, UserRole.MEMBER, UserRole.VIEWER]))
    permission = draw(st.sampled_from(list(Permission)))
    return role, permission


@pytest.mark.asyncio
@given(data=user_org_role_permission())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
async def test_property_user_permission_matches_role_permission(data):
    """Property: For any user with a role in an organization, the user should have
    a permission if and only if their role includes that permission.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    role, permission = data

    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Create user and organization
            user = User(id=uuid4(), email="test@example.com", hashed_password="hash")
            org = Organization(id=uuid4(), name="Test Org")

            async_session.add_all([user, org])
            await async_session.commit()

            # Add user to organization with the given role
            await async_session.execute(
                insert(organization_users).values(
                    user_id=user.id,
                    organization_id=org.id,
                    role=role,
                )
            )
            await async_session.commit()

            # Check if role has permission
            role_has_permission = auth_service.check_permission(role, permission)

            # Check if user has permission in organization
            user_has_permission = await auth_service.check_user_permission(
                user.id, org.id, permission
            )

            # Property: User permission should match role permission
            assert user_has_permission == role_has_permission, (
                f"Permission mismatch: Role {role.value} has permission {permission.value}={role_has_permission}, "
                f"but user with that role has permission={user_has_permission}"
            )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@given(permission=st.sampled_from(list(Permission)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
async def test_property_admin_has_all_permissions(permission):
    """Property: For any permission, the admin role should always have that permission.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Property: Admin should have all permissions
            has_permission = auth_service.check_permission(UserRole.ADMIN, permission)

            assert has_permission, (
                f"Admin role should have all permissions, but lacks {permission.value}"
            )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@given(permission=st.sampled_from(list(Permission)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
async def test_property_viewer_only_has_read_permissions(permission):
    """Property: For any permission, if viewer has it, it should be a read-only permission.

    Viewer should only have permissions with 'READ' in the name.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Check if viewer has permission
            has_permission = auth_service.check_permission(UserRole.VIEWER, permission)

            # Property: If viewer has permission, it should be a read permission
            if has_permission:
                # Check if permission is read-only (contains 'READ' in the name)
                is_read_permission = "READ" in permission.value.upper()

                assert is_read_permission, (
                    f"Viewer role should only have read permissions, "
                    f"but has write permission: {permission.value}"
                )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@given(permission=st.sampled_from(list(Permission)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
async def test_property_non_member_has_no_permissions(permission):
    """Property: For any permission, a user who is not a member of an organization
    should not have that permission in that organization.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """
    # Create test database and Redis for this test
    async_session_factory, redis, engine = await create_test_db_and_redis()

    try:
        async with async_session_factory() as async_session:
            # Create AuthService
            auth_service = AuthService(
                db=async_session,
                redis_client=redis,
                jwt_secret_key="test_secret_key_for_property_testing",
            )

            # Create user and organization
            user = User(id=uuid4(), email="outsider@example.com", hashed_password="hash")
            org = Organization(id=uuid4(), name="Test Org")

            async_session.add_all([user, org])
            await async_session.commit()

            # User is NOT added to organization

            # Check if user has permission in organization
            user_has_permission = await auth_service.check_user_permission(
                user.id, org.id, permission
            )

            # Property: Non-member should have no permissions
            assert not user_has_permission, (
                f"Non-member should have no permissions, but has permission: {permission.value}"
            )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()
