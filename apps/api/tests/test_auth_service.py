"""Unit tests for AuthService."""

from uuid import uuid4

import pytest

from apps.api.models import User
from apps.api.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_password_hashing(async_session, fake_redis):
    """Test password hashing with Argon2id."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",  # Use HS256 for testing (simpler than RS256)
    )

    password = "SecurePassword123!"
    hashed = auth_service.hash_password(password)

    # Verify hash is different from password
    assert hashed != password
    assert hashed.startswith("$argon2id$")

    # Verify password verification works
    assert auth_service.verify_password(password, hashed)
    assert not auth_service.verify_password("WrongPassword", hashed)


@pytest.mark.asyncio
async def test_create_access_token(async_session, fake_redis, test_user):
    """Test JWT access token creation."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
    )

    token = auth_service.create_access_token(test_user)

    # Verify token is a string
    assert isinstance(token, str)
    assert len(token) > 0

    # Verify token can be decoded
    payload = auth_service.verify_token(token, token_type="access")
    assert payload is not None
    assert payload.sub == str(test_user.id)
    assert payload.email == test_user.email
    assert payload.type == "access"


@pytest.mark.asyncio
async def test_create_refresh_token(async_session, fake_redis, test_user):
    """Test JWT refresh token creation."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        refresh_token_expire_days=30,
    )

    token = auth_service.create_refresh_token(test_user)

    # Verify token is a string
    assert isinstance(token, str)
    assert len(token) > 0

    # Verify token can be decoded
    payload = auth_service.verify_token(token, token_type="refresh")
    assert payload is not None
    assert payload.sub == str(test_user.id)
    assert payload.email == test_user.email
    assert payload.type == "refresh"


@pytest.mark.asyncio
async def test_verify_token_invalid(async_session, fake_redis):
    """Test token verification with invalid token."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Invalid token
    payload = auth_service.verify_token("invalid_token")
    assert payload is None


@pytest.mark.asyncio
async def test_verify_token_wrong_type(async_session, fake_redis, test_user):
    """Test token verification with wrong token type."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Create access token
    access_token = auth_service.create_access_token(test_user)

    # Try to verify as refresh token
    payload = auth_service.verify_token(access_token, token_type="refresh")
    assert payload is None


@pytest.mark.asyncio
async def test_store_and_verify_refresh_token(async_session, fake_redis, test_user):
    """Test storing and verifying refresh token in Redis."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        refresh_token_expire_days=30,
    )

    refresh_token = auth_service.create_refresh_token(test_user)

    # Store token
    await auth_service.store_refresh_token(test_user.id, refresh_token)

    # Verify token
    is_valid = await auth_service.verify_refresh_token(test_user.id, refresh_token)
    assert is_valid

    # Verify wrong token fails
    is_valid = await auth_service.verify_refresh_token(test_user.id, "wrong_token")
    assert not is_valid


@pytest.mark.asyncio
async def test_revoke_refresh_token(async_session, fake_redis, test_user):
    """Test revoking refresh token."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        refresh_token_expire_days=30,
    )

    refresh_token = auth_service.create_refresh_token(test_user)

    # Store token
    await auth_service.store_refresh_token(test_user.id, refresh_token)

    # Verify token is valid
    is_valid = await auth_service.verify_refresh_token(test_user.id, refresh_token)
    assert is_valid

    # Revoke token
    await auth_service.revoke_refresh_token(test_user.id)

    # Verify token is no longer valid
    is_valid = await auth_service.verify_refresh_token(test_user.id, refresh_token)
    assert not is_valid


@pytest.mark.asyncio
async def test_authenticate_success(async_session, fake_redis):
    """Test successful user authentication."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Create user with hashed password
    password = "SecurePassword123!"
    hashed_password = auth_service.hash_password(password)

    user = User(
        id=uuid4(),
        email="auth_test@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Authenticate
    authenticated_user = await auth_service.authenticate("auth_test@example.com", password)

    assert authenticated_user is not None
    assert authenticated_user.id == user.id
    assert authenticated_user.email == user.email


@pytest.mark.asyncio
async def test_authenticate_wrong_password(async_session, fake_redis):
    """Test authentication with wrong password."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Create user with hashed password
    password = "SecurePassword123!"
    hashed_password = auth_service.hash_password(password)

    user = User(
        id=uuid4(),
        email="auth_test2@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Authenticate with wrong password
    authenticated_user = await auth_service.authenticate("auth_test2@example.com", "WrongPassword")

    assert authenticated_user is None


@pytest.mark.asyncio
async def test_authenticate_nonexistent_user(async_session, fake_redis):
    """Test authentication with nonexistent user."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Authenticate nonexistent user
    authenticated_user = await auth_service.authenticate("nonexistent@example.com", "password")

    assert authenticated_user is None


@pytest.mark.asyncio
async def test_create_auth_tokens(async_session, fake_redis):
    """Test creating authentication tokens."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        refresh_token_expire_days=30,
    )

    # Create user
    user = User(
        id=uuid4(),
        email="tokens_test@example.com",
        hashed_password="hash",
    )
    async_session.add(user)
    await async_session.commit()

    # Create tokens
    auth_token = await auth_service.create_auth_tokens(user)

    assert auth_token.access_token is not None
    assert auth_token.refresh_token is not None
    assert auth_token.token_type == "bearer"
    assert auth_token.expires_in == 60 * 60  # 60 minutes in seconds

    # Verify tokens are valid
    access_payload = auth_service.verify_token(auth_token.access_token, token_type="access")
    assert access_payload is not None
    assert access_payload.sub == str(user.id)

    refresh_payload = auth_service.verify_token(auth_token.refresh_token, token_type="refresh")
    assert refresh_payload is not None
    assert refresh_payload.sub == str(user.id)

    # Verify refresh token is stored in Redis
    is_valid = await auth_service.verify_refresh_token(user.id, auth_token.refresh_token)
    assert is_valid


@pytest.mark.asyncio
async def test_refresh_access_token(async_session, fake_redis):
    """Test refreshing access token."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        refresh_token_expire_days=30,
    )

    # Create user
    user = User(
        id=uuid4(),
        email="refresh_test@example.com",
        hashed_password="hash",
    )
    async_session.add(user)
    await async_session.commit()

    # Create initial tokens
    initial_tokens = await auth_service.create_auth_tokens(user)

    # Refresh tokens
    new_tokens = await auth_service.refresh_access_token(initial_tokens.refresh_token)

    assert new_tokens is not None
    # Tokens may be the same if generated at the same timestamp (fast test execution)
    # Just verify they are valid
    access_payload = auth_service.verify_token(new_tokens.access_token, token_type="access")
    assert access_payload is not None
    assert access_payload.sub == str(user.id)


@pytest.mark.asyncio
async def test_refresh_access_token_invalid(async_session, fake_redis):
    """Test refreshing access token with invalid refresh token."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Try to refresh with invalid token
    new_tokens = await auth_service.refresh_access_token("invalid_token")

    assert new_tokens is None


@pytest.mark.asyncio
async def test_expired_access_token_rejection(async_session, fake_redis, test_user):
    """Test that expired access tokens are rejected.

    **Validates: Requirements 1.1**
    """
    import time

    from jose import jwt

    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Manually create an expired access token (expired 1 hour ago)
    current_timestamp = int(time.time())
    expired_timestamp = current_timestamp - 3600  # 1 hour ago
    issued_timestamp = current_timestamp - 7200  # 2 hours ago

    payload = {
        "sub": str(test_user.id),
        "email": test_user.email,
        "exp": expired_timestamp,
        "iat": issued_timestamp,
        "type": "access",
    }

    expired_token = jwt.encode(payload, "test_secret_key", algorithm="HS256")

    # Try to verify the expired token
    verified_payload = auth_service.verify_token(expired_token, token_type="access")

    # Expired token should be rejected
    assert verified_payload is None


@pytest.mark.asyncio
async def test_expired_refresh_token_rejection(async_session, fake_redis, test_user):
    """Test that expired refresh tokens are rejected.

    **Validates: Requirements 1.1**
    """
    import time

    from jose import jwt

    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Manually create an expired refresh token (expired 1 day ago)
    current_timestamp = int(time.time())
    expired_timestamp = current_timestamp - 86400  # 1 day ago
    issued_timestamp = current_timestamp - (31 * 86400)  # 31 days ago

    payload = {
        "sub": str(test_user.id),
        "email": test_user.email,
        "exp": expired_timestamp,
        "iat": issued_timestamp,
        "type": "refresh",
    }

    expired_refresh_token = jwt.encode(payload, "test_secret_key", algorithm="HS256")

    # Store the expired token in Redis (it would be stored before expiration)
    await auth_service.store_refresh_token(test_user.id, expired_refresh_token)

    # Try to refresh with expired token
    new_tokens = await auth_service.refresh_access_token(expired_refresh_token)

    # Expired refresh token should be rejected
    assert new_tokens is None


@pytest.mark.asyncio
async def test_invalid_credentials_wrong_password(async_session, fake_redis):
    """Test authentication rejection with invalid credentials (wrong password).

    **Validates: Requirements 1.1**
    """
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Create user with hashed password
    correct_password = "CorrectPassword123!"
    hashed_password = auth_service.hash_password(correct_password)

    user = User(
        id=uuid4(),
        email="invalid_creds_test@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Attempt authentication with wrong password
    authenticated_user = await auth_service.authenticate(
        "invalid_creds_test@example.com",
        "WrongPassword123!",
    )

    # Authentication should fail
    assert authenticated_user is None


@pytest.mark.asyncio
async def test_refresh_token_rotation(async_session, fake_redis):
    """Test that old refresh tokens are invalidated after refresh (token rotation).

    **Validates: Requirements 1.1**
    """
    import asyncio

    from jose import jwt

    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
        access_token_expire_minutes=60,
        refresh_token_expire_days=30,
    )

    # Create user
    user = User(
        id=uuid4(),
        email="rotation_test@example.com",
        hashed_password="hash",
    )
    async_session.add(user)
    await async_session.commit()

    # Create initial tokens
    initial_tokens = await auth_service.create_auth_tokens(user)
    old_refresh_token = initial_tokens.refresh_token

    # Verify old token is valid
    is_valid = await auth_service.verify_refresh_token(user.id, old_refresh_token)
    assert is_valid

    # Wait to ensure different timestamp for new token
    await asyncio.sleep(1.1)

    # Refresh tokens (this should rotate the refresh token)
    new_tokens = await auth_service.refresh_access_token(old_refresh_token)
    assert new_tokens is not None

    new_refresh_token = new_tokens.refresh_token

    # Decode both tokens to verify they're different
    old_payload = jwt.decode(
        old_refresh_token, "test_secret_key", algorithms=["HS256"], options={"verify_exp": False}
    )
    new_payload = jwt.decode(
        new_refresh_token, "test_secret_key", algorithms=["HS256"], options={"verify_exp": False}
    )

    # Tokens should have different timestamps (iat and exp)
    assert old_payload["iat"] != new_payload["iat"] or old_payload["exp"] != new_payload["exp"]

    # Verify new token is valid
    is_valid = await auth_service.verify_refresh_token(user.id, new_refresh_token)
    assert is_valid

    # Verify old token is now invalid (rotated out)
    # After refresh, only the new token should be stored in Redis
    is_valid = await auth_service.verify_refresh_token(user.id, old_refresh_token)
    assert not is_valid
