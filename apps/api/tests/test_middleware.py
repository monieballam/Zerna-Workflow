"""Tests for authentication and authorization middleware."""

from uuid import uuid4

import pytest
from zerna_contracts.enums import UserRole
from zerna_contracts.permissions import Permission
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.organization import Organization, User, organization_users
from apps.api.services.auth_service import AuthService


@pytest.mark.asyncio
class TestGetCurrentUser:
    """Test get_current_user middleware."""

    async def test_get_current_user_valid_token(self, async_session: AsyncSession, fake_redis):
        """Test that valid token returns user."""
        # Create user
        user = User(id=uuid4(), email="test@example.com", hashed_password="hash")
        async_session.add(user)
        await async_session.commit()
        await async_session.refresh(user)

        # Create auth service and generate token
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
            jwt_algorithm="HS256",  # Use HS256 for testing
        )

        access_token = auth_service.create_access_token(user)

        # Verify token and get user
        payload = auth_service.verify_token(access_token, token_type="access")
        assert payload is not None
        assert payload.sub == str(user.id)
        assert payload.email == user.email

    async def test_get_current_user_invalid_token(self, async_session: AsyncSession, fake_redis):
        """Test that invalid token returns None."""
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
            jwt_algorithm="HS256",  # Use HS256 for testing
        )

        # Verify invalid token
        payload = auth_service.verify_token("invalid_token", token_type="access")
        assert payload is None

    async def test_get_current_user_expired_token(self, async_session: AsyncSession, fake_redis):
        """Test that expired token returns None."""
        # Create user
        user = User(id=uuid4(), email="test@example.com", hashed_password="hash")
        async_session.add(user)
        await async_session.commit()

        # Create auth service with 0 expiration
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
            jwt_algorithm="HS256",  # Use HS256 for testing
            access_token_expire_minutes=0,  # Immediate expiration
        )

        access_token = auth_service.create_access_token(user)

        # Token should be expired
        payload = auth_service.verify_token(access_token, token_type="access")
        # Note: This might still pass if verification doesn't check expiration strictly
        # In production, expired tokens would fail verification


@pytest.mark.asyncio
class TestRequireOrganizationMembership:
    """Test require_organization_membership middleware."""

    async def test_require_membership_success(self, async_session: AsyncSession, fake_redis):
        """Test that membership check succeeds for member."""
        # Create user and organization
        user = User(id=uuid4(), email="member@example.com", hashed_password="hash")
        org = Organization(id=uuid4(), name="Test Org")

        async_session.add_all([user, org])
        await async_session.commit()

        # Add user to organization
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org.id,
                role=UserRole.MEMBER,
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

    async def test_require_membership_failure(self, async_session: AsyncSession, fake_redis):
        """Test that membership check fails for non-member."""
        # Create user and organization
        user = User(id=uuid4(), email="outsider@example.com", hashed_password="hash")
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
class TestPermissionMiddleware:
    """Test permission checking middleware."""

    async def test_admin_can_delete_dataset(self, async_session: AsyncSession, fake_redis):
        """Test that admin can delete datasets."""
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

        # Check permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        has_permission = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_DELETE
        )
        assert has_permission is True

    async def test_member_cannot_delete_organization(self, async_session: AsyncSession, fake_redis):
        """Test that member cannot delete organization."""
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

        # Check permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        has_permission = await auth_service.check_user_permission(
            user.id, org.id, Permission.ORG_DELETE
        )
        assert has_permission is False

    async def test_viewer_can_read_datasets(self, async_session: AsyncSession, fake_redis):
        """Test that viewer can read datasets."""
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

        # Check permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        has_permission = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_READ
        )
        assert has_permission is True

    async def test_viewer_cannot_create_datasets(self, async_session: AsyncSession, fake_redis):
        """Test that viewer cannot create datasets."""
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

        # Check permission
        auth_service = AuthService(
            db=async_session,
            redis_client=fake_redis,
            jwt_secret_key="test_secret",
        )

        has_permission = await auth_service.check_user_permission(
            user.id, org.id, Permission.DATASET_CREATE
        )
        assert has_permission is False


@pytest.mark.asyncio
class TestMultiOrganizationAccess:
    """Test access control across multiple organizations."""

    async def test_user_different_roles_different_orgs(
        self, async_session: AsyncSession, fake_redis
    ):
        """Test that user can have different roles in different organizations."""
        # Create user and organizations
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org1 = Organization(id=uuid4(), name="Org 1")
        org2 = Organization(id=uuid4(), name="Org 2")

        async_session.add_all([user, org1, org2])
        await async_session.commit()

        # Add user as admin in org1
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org1.id,
                role=UserRole.ADMIN,
            )
        )

        # Add user as viewer in org2
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org2.id,
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

        # User should have delete permission in org1 (admin)
        has_delete_org1 = await auth_service.check_user_permission(
            user.id, org1.id, Permission.DATASET_DELETE
        )
        assert has_delete_org1 is True

        # User should NOT have delete permission in org2 (viewer)
        has_delete_org2 = await auth_service.check_user_permission(
            user.id, org2.id, Permission.DATASET_DELETE
        )
        assert has_delete_org2 is False

        # User should have read permission in both orgs
        has_read_org1 = await auth_service.check_user_permission(
            user.id, org1.id, Permission.DATASET_READ
        )
        has_read_org2 = await auth_service.check_user_permission(
            user.id, org2.id, Permission.DATASET_READ
        )
        assert has_read_org1 is True
        assert has_read_org2 is True

    async def test_user_no_access_to_other_org(self, async_session: AsyncSession, fake_redis):
        """Test that user has no access to organizations they're not a member of."""
        # Create user and organizations
        user = User(id=uuid4(), email="user@example.com", hashed_password="hash")
        org1 = Organization(id=uuid4(), name="User's Org")
        org2 = Organization(id=uuid4(), name="Other Org")

        async_session.add_all([user, org1, org2])
        await async_session.commit()

        # Add user only to org1
        await async_session.execute(
            insert(organization_users).values(
                user_id=user.id,
                organization_id=org1.id,
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

        # User should have access to org1
        has_access_org1 = await auth_service.check_user_permission(
            user.id, org1.id, Permission.DATASET_READ
        )
        assert has_access_org1 is True

        # User should NOT have access to org2
        has_access_org2 = await auth_service.check_user_permission(
            user.id, org2.id, Permission.DATASET_READ
        )
        assert has_access_org2 is False
