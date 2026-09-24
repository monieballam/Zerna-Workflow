"""Tests for authentication routes."""

import pytest
from sqlalchemy import select

from apps.api.dependencies import get_auth_service
from apps.api.main import app
from apps.api.middleware.auth import get_current_user
from apps.api.models.organization import Organization, User, organization_users
from apps.api.services.auth_service import AuthService


@pytest.mark.asyncio
class TestAuthRoutes:
    """Route tests for auth endpoints beyond login and refresh."""

    async def test_me_requires_auth(self, async_client):
        response = await async_client.get("/v1/auth/me")
        assert response.status_code == 401

    async def test_me_returns_current_user_profile(self, async_client, test_user):
        async def override_get_current_user():
            return test_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        try:
            response = await async_client.get("/v1/auth/me")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(test_user.id)
        assert payload["email"] == test_user.email
        assert "created_at" in payload

    async def test_signup_creates_user_and_default_workspace(
        self, async_client, async_session, fake_redis
    ):
        async def override_get_auth_service():
            return AuthService(
                db=async_session,
                redis_client=fake_redis,
                jwt_secret_key="test_secret_key_for_testing_only",
                jwt_algorithm="HS256",
            )

        app.dependency_overrides[get_auth_service] = override_get_auth_service
        try:
            response = await async_client.post(
                "/v1/auth/signup",
                json={
                    "email": "new.user@example.com",
                    "password": "SuperSecure123!",
                    "organization_name": "New User Lab",
                },
            )
        finally:
            app.dependency_overrides.pop(get_auth_service, None)

        assert response.status_code == 201
        payload = response.json()
        assert payload["user"]["email"] == "new.user@example.com"
        assert payload["access_token"]
        assert payload["refresh_token"]

        user_result = await async_session.execute(
            select(User).where(User.email == "new.user@example.com")
        )
        user = user_result.scalar_one()
        org_result = await async_session.execute(
            select(Organization)
            .join(organization_users, Organization.id == organization_users.c.organization_id)
            .where(organization_users.c.user_id == user.id)
        )
        organization = org_result.scalar_one()
        assert organization.name == "New User Lab"

    async def test_signup_rejects_duplicate_email(self, async_client, async_session, fake_redis):
        async def override_get_auth_service():
            return AuthService(
                db=async_session,
                redis_client=fake_redis,
                jwt_secret_key="test_secret_key_for_testing_only",
                jwt_algorithm="HS256",
            )

        app.dependency_overrides[get_auth_service] = override_get_auth_service
        try:
            first = await async_client.post(
                "/v1/auth/signup",
                json={
                    "email": "duplicate@example.com",
                    "password": "SuperSecure123!",
                },
            )
            second = await async_client.post(
                "/v1/auth/signup",
                json={
                    "email": "duplicate@example.com",
                    "password": "SuperSecure123!",
                },
            )
        finally:
            app.dependency_overrides.pop(get_auth_service, None)

        assert first.status_code == 201
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()
