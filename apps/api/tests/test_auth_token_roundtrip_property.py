"""Property-based tests for authentication token round trip.

**Validates: Requirements 1.1, 1.3**
"""

from uuid import UUID

import pytest
from fakeredis import aioredis as fakeredis
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.models import Base, User
from apps.api.services.auth_service import AuthService


# Custom strategies for generating valid test data
@st.composite
def valid_email(draw):
    """Generate valid email addresses."""
    username = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Nd"), min_codepoint=97, max_codepoint=122
            ),
            min_size=1,
            max_size=20,
        )
    )
    domain = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll",), min_codepoint=97, max_codepoint=122
            ),
            min_size=2,
            max_size=15,
        )
    )
    tld = draw(st.sampled_from(["com", "org", "net", "edu"]))
    return f"{username}@{domain}.{tld}"


@st.composite
def valid_user(draw):
    """Generate valid User objects for testing."""
    email = draw(valid_email())
    return {
        "email": email,
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


@pytest.mark.asyncio
@given(user_data=valid_user())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=10)
async def test_property_token_round_trip(user_data):
    """Property: For any valid user, creating an access token and verifying it
    should return the original user information (user_id, email).

    **Validates: Requirements 1.1, 1.3**
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
                jwt_algorithm="HS256",
                access_token_expire_minutes=60,
            )

            # Create user in database
            user = User(
                email=user_data["email"],
                hashed_password="placeholder_hash",
            )
            async_session.add(user)
            await async_session.commit()
            await async_session.refresh(user)

            # Create access token
            access_token = auth_service.create_access_token(user)

            # Verify token
            payload = auth_service.verify_token(access_token, token_type="access")

            # Property assertions: Token verification should recover original user information
            assert payload is not None, "Token verification should succeed for valid tokens"
            assert payload.sub == str(user.id), "Token should contain original user ID"
            assert payload.email == user.email, "Token should contain original user email"
            assert payload.type == "access", "Token type should be 'access'"

            # Verify the user_id can be parsed back to UUID
            recovered_user_id = UUID(payload.sub)
            assert recovered_user_id == user.id, "User ID should round-trip correctly"
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@given(user_data=valid_user())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=10)
async def test_property_refresh_token_round_trip(user_data):
    """Property: For any valid user, creating a refresh token and verifying it
    should return the original user information.

    **Validates: Requirements 1.1, 1.3**
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
                jwt_algorithm="HS256",
                refresh_token_expire_days=30,
            )

            # Create user in database
            user = User(
                email=user_data["email"],
                hashed_password="placeholder_hash",
            )
            async_session.add(user)
            await async_session.commit()
            await async_session.refresh(user)

            # Create refresh token
            refresh_token = auth_service.create_refresh_token(user)

            # Verify token
            payload = auth_service.verify_token(refresh_token, token_type="refresh")

            # Property assertions: Token verification should recover original user information
            assert payload is not None, "Token verification should succeed for valid tokens"
            assert payload.sub == str(user.id), "Token should contain original user ID"
            assert payload.email == user.email, "Token should contain original user email"
            assert payload.type == "refresh", "Token type should be 'refresh'"

            # Verify the user_id can be parsed back to UUID
            recovered_user_id = UUID(payload.sub)
            assert recovered_user_id == user.id, "User ID should round-trip correctly"
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@given(user_data=valid_user())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=10)
async def test_property_auth_tokens_round_trip(user_data):
    """Property: For any valid user, creating auth tokens (access + refresh) and
    verifying them should return the original user information for both tokens.

    **Validates: Requirements 1.1, 1.3**
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
                jwt_algorithm="HS256",
                access_token_expire_minutes=60,
                refresh_token_expire_days=30,
            )

            # Create user in database
            user = User(
                email=user_data["email"],
                hashed_password="placeholder_hash",
            )
            async_session.add(user)
            await async_session.commit()
            await async_session.refresh(user)

            # Create auth tokens
            auth_tokens = await auth_service.create_auth_tokens(user)

            # Verify access token
            access_payload = auth_service.verify_token(
                auth_tokens.access_token, token_type="access"
            )
            assert access_payload is not None, "Access token verification should succeed"
            assert access_payload.sub == str(user.id), (
                "Access token should contain original user ID"
            )
            assert access_payload.email == user.email, (
                "Access token should contain original user email"
            )
            assert access_payload.type == "access", "Token type should be 'access'"

            # Verify refresh token
            refresh_payload = auth_service.verify_token(
                auth_tokens.refresh_token, token_type="refresh"
            )
            assert refresh_payload is not None, "Refresh token verification should succeed"
            assert refresh_payload.sub == str(user.id), (
                "Refresh token should contain original user ID"
            )
            assert refresh_payload.email == user.email, (
                "Refresh token should contain original user email"
            )
            assert refresh_payload.type == "refresh", "Token type should be 'refresh'"

            # Verify refresh token is stored in Redis
            is_valid = await auth_service.verify_refresh_token(user.id, auth_tokens.refresh_token)
            assert is_valid, "Refresh token should be stored and verifiable in Redis"

            # Verify both tokens reference the same user
            assert access_payload.sub == refresh_payload.sub, (
                "Both tokens should reference the same user"
            )
            assert access_payload.email == refresh_payload.email, (
                "Both tokens should contain the same email"
            )
    finally:
        await redis.flushall()
        await redis.aclose()
        await engine.dispose()
