"""Tests for role-based access control (RBAC) system."""

from uuid import uuid4

import pytest
from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import Permission
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.organization import Organization, User, organization_users
from apps.api.services.auth_service import AuthService


@pytest.mark.asyncio
class TestRolePermissions:
    """Test role-based permission checking."""

    async def test_admin_has_all_permissions(self, async_session: AsyncSession, fake_redis):
        """Test that admin role has all permissions."""
        # Create auth service
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Test all permissions for admin role
        admin_permissions = [
            Permission.ORG_READ,
            Permission.ORG_UPDATE,
            Permission.ORG_DELETE,
            Permission.ORG_MANAGE_USERS,
            Permission.DATASET_CREATE,
            Permission.DATASET_READ,
            Permission.DATASET_UPDATE,
            Permission.DATASET_DELETE,
            Permission.RUN_CREATE,
            Permission.RUN_READ,
            Permission.ANNOTATION_APPROVE,
            Permission.USER_DELETE,
        ]

        for permission in admin_permissions:
            assert auth_service.check_permission(UserRole.ADMIN, permission)

    async def test_member_has_limited_permissions(self, async_session: AsyncSession, fake_redis):
        """Test that member role has limited permissions."""
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Member should have these permissions
        member_allowed = [
            Permission.ORG_READ,
            Permission.DATASET_CREATE,
            Permission.DATASET_READ,
            Permission.DATASET_UPDATE,
            Permission.RUN_CREATE,
            Permission.RUN_READ,
        ]

        for permission in member_allowed:
            assert auth_service.check_permission(UserRole.MEMBER, permission)

        # Member should NOT have these permissions
        member_denied = [
            Permission.ORG_DELETE,
            Permission.ORG_MANAGE_USERS,
            Permission.ANNOTATION_APPROVE,
            Permission.USER_DELETE,
        ]

        for permission in member_denied:
            assert not auth_service.check_permission(UserRole.MEMBER, permission)

    async def test_viewer_has_read_only_permissions(self, async_session: AsyncSession, fake_redis):
        """Test that viewer role has read-only permissions."""
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Viewer should have read permissions
        viewer_allowed = [
            Permission.ORG_READ,
            Permission.DATASET_READ,
            Permission.RUN_READ,
            Permission.ARTIFACT_READ,
            Permission.ANNOTATION_READ,
        ]

        for permission in viewer_allowed:
            assert auth_service.check_permission(UserRole.VIEWER, permission)

        # Viewer should NOT have write permissions
        viewer_denied = [
            Permission.DATASET_CREATE,
            Permission.DATASET_UPDATE,
            Permission.DATASET_DELETE,
            Permission.RUN_CREATE,
            Permission.ANNOTATION_CREATE,
            Permission.ANNOTATION_UPDATE,
        ]

        for permission in viewer_denied:
            assert not auth_service.check_permission(UserRole.VIEWER, permission)


@pytest.mark.asyncio
class TestOrganizationMembership:
    """Test organization membership verification."""

    async def test_get_user_organizations(self, async_session: AsyncSession, fake_redis):
        """Test retrieving all organizations a user belongs to."""
        # Create user and organizations
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org1 = Organization(id=uuid4(), name="Org 1")
        org2 = Organization(id=uuid4(), name="Org 2")

        async_session.add_all([user, org1, org2])
        await async_session.commit()

        # Add user to organizations with different roles
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org1.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org2.id,
                role=UserRole.MEMBER,
            )
        )
        await async_session.commit()

        # Get user organizations
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        orgs = await auth_service.get_user_organizations(user.id)

        assert len(orgs) == 2
        org_dict = {org_id: role for org_id, role in orgs}
        assert org_dict[org1.id] == UserRole.ADMIN
        assert org_dict[org2.id] == UserRole.MEMBER

    async def test_get_user_role_in_organization(self, async_session: AsyncSession, fake_redis):
        """Test retrieving user's role in a specific organization."""
        # Create user and organization
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user to organization as member
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.MEMBER,
            )
        )
        await async_session.commit()

        # Get user role
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        role = await auth_service.get_user_role_in_organization(user.id, org.id)
        assert role == UserRole.MEMBER

    async def test_get_user_role_not_member(self, async_session: AsyncSession, fake_redis):
        """Test that None is returned when user is not a member."""
        # Create user and organization
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # User is NOT added to organization

        # Get user role
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        role = await auth_service.get_user_role_in_organization(user.id, org.id)
        assert role is None

    async def test_is_member_of_organization(self, async_session: AsyncSession, fake_redis):
        """Test checking if user is a member of an organization."""
        # Create user and organization
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user to organization
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.VIEWER,
            )
        )
        await async_session.commit()

        # Check membership
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        is_member = await auth_service.is_member_of_organization(user.id, org.id)
        assert is_member is True

    async def test_is_not_member_of_organization(self, async_session: AsyncSession, fake_redis):
        """Test checking membership when user is not a member."""
        # Create user and organization
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # User is NOT added to organization

        # Check membership
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        is_member = await auth_service.is_member_of_organization(user.id, org.id)
        assert is_member is False


@pytest.mark.asyncio
class TestUserPermissionChecking:
    """Test user permission checking in organizations."""

    async def test_check_user_permission_admin(self, async_session: AsyncSession, fake_redis):
        """Test that admin user has all permissions."""
        # Create user and organization
        user = User(id=uuid4(), email="admin@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user as admin
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        # Check permissions
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Admin should have delete permission
        has_delete = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_DELETE
        )
        assert has_delete is True

        # Admin should have manage users permission
        has_manage = await auth_service.check_user_permission(
            user.id, org.id, Permission.ORG_MANAGE_USERS
        )
        assert has_manage is True

    async def test_check_user_permission_member(self, async_session: AsyncSession, fake_redis):
        """Test that member user has limited permissions."""
        # Create user and organization
        user = User(id=uuid4(), email="member@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user as member
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.MEMBER,
            )
        )
        await async_session.commit()

        # Check permissions
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Member should have create permission
        has_create = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_CREATE
        )
        assert has_create is True

        # Member should NOT have manage users permission
        has_manage = await auth_service.check_user_permission(
            user.id, org.id, Permission.ORG_MANAGE_USERS
        )
        assert has_manage is False

    async def test_check_user_permission_viewer(self, async_session: AsyncSession, fake_redis):
        """Test that viewer user has read-only permissions."""
        # Create user and organization
        user = User(id=uuid4(), email="viewer@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user as viewer
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.VIEWER,
            )
        )
        await async_session.commit()

        # Check permissions
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Viewer should have read permission
        has_read = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_READ
        )
        assert has_read is True

        # Viewer should NOT have create permission
        has_create = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_CREATE
        )
        assert has_create is False

    async def test_check_user_permission_not_member(self, async_session: AsyncSession, fake_redis):
        """Test that non-member has no permissions."""
        # Create user and organization
        user = User(id=uuid4(), email="outsider@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # User is NOT added to organization

        # Check permissions
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Non-member should have no permissions
        has_read = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_READ
        )
        assert has_read is False

    async def test_require_permission_success(self, async_session: AsyncSession, fake_redis):
        """Test that require_permission succeeds when user has permission."""
        # Create user and organization
        user = User(id=uuid4(), email="admin@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user as admin
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.ADMIN,
            )
        )
        await async_session.commit()

        # Require permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Should not raise exception
        await auth_service.require_permission(user.id, org.id, Permission.DATASET_DELETE)

    async def test_require_permission_failure(self, async_session: AsyncSession, fake_redis):
        """Test that require_permission raises exception when user lacks permission."""
        # Create user and organization
        user = User(id=uuid4(), email="viewer@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user as viewer
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.VIEWER,
            )
        )
        await async_session.commit()

        # Require permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Should raise PermissionError
        with pytest.raises(PermissionError):
            await auth_service.require_permission(user.id, org.id, Permission.DATASET_DELETE)


@pytest.mark.asyncio
class TestRoleHierarchy:
    """Test role hierarchy implementation."""

    async def test_admin_inherits_member_permissions(self, async_session: AsyncSession, fake_redis):
        """Test that admin role includes all member permissions."""
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Get member permissions
        member_permissions = [
            Permission.DATASET_CREATE,
            Permission.DATASET_READ,
            Permission.RUN_CREATE,
        ]

        # Admin should have all member permissions
        for permission in member_permissions:
            assert auth_service.check_permission(UserRole.ADMIN, permission)

    async def test_member_inherits_viewer_permissions(
        self, async_session: AsyncSession, fake_redis
    ):
        """Test that member role includes all viewer permissions."""
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        # Get viewer permissions
        viewer_permissions = [
            Permission.DATASET_READ,
            Permission.RUN_READ,
            Permission.ARTIFACT_READ,
        ]

        # Member should have all viewer permissions
        for permission in viewer_permissions:
            assert auth_service.check_permission(UserRole.MEMBER, permission)
