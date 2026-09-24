"""Unit tests for authentication audit logging and rate limiting."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.models import User
from apps.api.models.audit import AuditEvent
from apps.api.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_check_rate_limit_not_locked(async_session, fake_redis):
    """Test rate limit check when user is not locked out."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    is_allowed, seconds_until_unlock = await auth_service.check_rate_limit("test@example.com")

    assert is_allowed is True
    assert seconds_until_unlock is None


@pytest.mark.asyncio
async def test_check_rate_limit_locked(async_session, fake_redis):
    """Test rate limit check when user is locked out."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Manually lock out user
    lockout_key = "auth_lockout:test@example.com"
    await fake_redis.setex(lockout_key, 900, "1")  # 15 minutes

    is_allowed, seconds_until_unlock = await auth_service.check_rate_limit("test@example.com")

    assert is_allowed is False
    assert seconds_until_unlock is not None
    assert seconds_until_unlock > 0


@pytest.mark.asyncio
async def test_record_failed_attempt_increments_counter(async_session, fake_redis):
    """Test that failed attempts are recorded and incremented."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # First attempt
    is_locked, _ = await auth_service.record_failed_attempt("test@example.com")
    assert is_locked is False

    # Check counter
    attempts_key = "auth_attempts:test@example.com"
    attempts = await fake_redis.get(attempts_key)
    assert int(attempts) == 1


@pytest.mark.asyncio
async def test_record_failed_attempt_lockout_after_5_attempts(async_session, fake_redis):
    """Test that user is locked out after 5 failed attempts."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    email = "lockout_test@example.com"

    # Record 4 failed attempts
    for i in range(4):
        is_locked, _ = await auth_service.record_failed_attempt(email)
        assert is_locked is False

    # 5th attempt should trigger lockout
    is_locked, seconds_until_unlock = await auth_service.record_failed_attempt(email)
    assert is_locked is True
    assert seconds_until_unlock == 15 * 60  # 15 minutes

    # Verify lockout key exists
    lockout_key = f"auth_lockout:{email}"
    lockout_value = await fake_redis.get(lockout_key)
    assert lockout_value is not None

    # Verify attempts counter is cleared
    attempts_key = f"auth_attempts:{email}"
    attempts = await fake_redis.get(attempts_key)
    assert attempts is None


@pytest.mark.asyncio
async def test_clear_failed_attempts(async_session, fake_redis):
    """Test clearing failed attempts counter."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    email = "clear_test@example.com"

    # Record some failed attempts
    await auth_service.record_failed_attempt(email)
    await auth_service.record_failed_attempt(email)

    # Verify counter exists
    attempts_key = f"auth_attempts:{email}"
    attempts = await fake_redis.get(attempts_key)
    assert int(attempts) == 2

    # Clear attempts
    await auth_service.clear_failed_attempts(email)

    # Verify counter is cleared
    attempts = await fake_redis.get(attempts_key)
    assert attempts is None


@pytest.mark.asyncio
async def test_create_audit_event(async_session, fake_redis):
    """Test creating an audit event."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    user_id = uuid4()
    org_id = uuid4()
    resource_id = uuid4()

    audit_event = await auth_service.create_audit_event(
        user_id=user_id,
        organization_id=org_id,
        action_type="auth.login.success",
        resource_type="user",
        resource_id=resource_id,
        after_state={
            "email": "test@example.com",
            "ip_address": "192.168.1.1",
            "user_agent": "Mozilla/5.0",
        },
    )

    assert audit_event.id is not None
    assert audit_event.user_id == user_id
    assert audit_event.organization_id == org_id
    assert audit_event.action_type == "auth.login.success"
    assert audit_event.resource_type == "user"
    assert audit_event.resource_id == resource_id
    assert audit_event.after_state["email"] == "test@example.com"
    assert audit_event.after_state["ip_address"] == "192.168.1.1"
    assert audit_event.after_state["user_agent"] == "Mozilla/5.0"

    # Verify event is persisted in database
    stmt = select(AuditEvent).where(AuditEvent.id == audit_event.id)
    result = await async_session.execute(stmt)
    persisted_event = result.scalar_one_or_none()
    assert persisted_event is not None
    assert persisted_event.action_type == "auth.login.success"


@pytest.mark.asyncio
async def test_authenticate_success_creates_audit_event(
    async_session, fake_redis, test_organization
):
    """Test that successful authentication creates an audit event."""
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
        email="audit_success@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Add user to organization
    from apps.api.models.organization import organization_users

    stmt = organization_users.insert().values(
        user_id=user.id,
        organization_id=test_organization.id,
        role="member",
    )
    await async_session.execute(stmt)
    await async_session.commit()

    # Authenticate with IP and user agent
    authenticated_user = await auth_service.authenticate(
        "audit_success@example.com",
        password,
        ip_address="192.168.1.100",
        user_agent="TestAgent/1.0",
    )

    assert authenticated_user is not None

    # Verify audit event was created
    stmt = select(AuditEvent).where(
        AuditEvent.user_id == user.id,
        AuditEvent.action_type == "auth.login.success",
    )
    result = await async_session.execute(stmt)
    audit_event = result.scalar_one_or_none()

    assert audit_event is not None
    assert audit_event.resource_type == "user"
    assert audit_event.resource_id == user.id
    assert audit_event.after_state["email"] == "audit_success@example.com"
    assert audit_event.after_state["ip_address"] == "192.168.1.100"
    assert audit_event.after_state["user_agent"] == "TestAgent/1.0"


@pytest.mark.asyncio
async def test_authenticate_failure_creates_audit_event(
    async_session, fake_redis, test_organization
):
    """Test that failed authentication creates an audit event."""
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
        email="audit_failure@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Add user to organization
    from apps.api.models.organization import organization_users

    stmt = organization_users.insert().values(
        user_id=user.id,
        organization_id=test_organization.id,
        role="member",
    )
    await async_session.execute(stmt)
    await async_session.commit()

    # Authenticate with wrong password
    authenticated_user = await auth_service.authenticate(
        "audit_failure@example.com",
        "WrongPassword",
        ip_address="192.168.1.200",
        user_agent="TestAgent/1.0",
    )

    assert authenticated_user is None

    # Verify audit event was created
    stmt = select(AuditEvent).where(
        AuditEvent.user_id == user.id,
        AuditEvent.action_type == "auth.login.failure",
    )
    result = await async_session.execute(stmt)
    audit_event = result.scalar_one_or_none()

    assert audit_event is not None
    assert audit_event.resource_type == "user"
    assert audit_event.resource_id == user.id
    assert audit_event.after_state["email"] == "audit_failure@example.com"
    assert audit_event.after_state["ip_address"] == "192.168.1.200"
    assert audit_event.after_state["user_agent"] == "TestAgent/1.0"
    assert audit_event.after_state["reason"] == "invalid_password"


@pytest.mark.asyncio
async def test_authenticate_clears_attempts_on_success(
    async_session, fake_redis, test_organization
):
    """Test that successful authentication clears failed attempts counter."""
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
        email="clear_attempts@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Add user to organization
    from apps.api.models.organization import organization_users

    stmt = organization_users.insert().values(
        user_id=user.id,
        organization_id=test_organization.id,
        role="member",
    )
    await async_session.execute(stmt)
    await async_session.commit()

    # Record some failed attempts
    await auth_service.record_failed_attempt("clear_attempts@example.com")
    await auth_service.record_failed_attempt("clear_attempts@example.com")

    # Verify counter exists
    attempts_key = "auth_attempts:clear_attempts@example.com"
    attempts = await fake_redis.get(attempts_key)
    assert int(attempts) == 2

    # Successful authentication
    authenticated_user = await auth_service.authenticate(
        "clear_attempts@example.com",
        password,
    )

    assert authenticated_user is not None

    # Verify counter is cleared
    attempts = await fake_redis.get(attempts_key)
    assert attempts is None


@pytest.mark.asyncio
async def test_authenticate_rate_limit_prevents_login(async_session, fake_redis):
    """Test that rate limit prevents login when locked out."""
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
        email="rate_limit@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Manually lock out user
    lockout_key = "auth_lockout:rate_limit@example.com"
    await fake_redis.setex(lockout_key, 900, "1")  # 15 minutes

    # Try to authenticate (should fail due to rate limit)
    authenticated_user = await auth_service.authenticate(
        "rate_limit@example.com",
        password,
    )

    assert authenticated_user is None


@pytest.mark.asyncio
async def test_authenticate_nonexistent_user_creates_audit_event(async_session, fake_redis):
    """Test that authentication attempt for nonexistent user creates audit event."""
    auth_service = AuthService(
        db=async_session,
        redis_client=fake_redis,
        jwt_secret_key="test_secret_key",
        jwt_algorithm="HS256",
    )

    # Authenticate nonexistent user
    authenticated_user = await auth_service.authenticate(
        "nonexistent@example.com",
        "password",
        ip_address="192.168.1.300",
        user_agent="TestAgent/1.0",
    )

    assert authenticated_user is None

    # Verify audit event was created
    stmt = select(AuditEvent).where(
        AuditEvent.action_type == "auth.login.failure",
    )
    result = await async_session.execute(stmt)
    audit_events = result.scalars().all()

    # Find the event for this email
    matching_event = None
    for event in audit_events:
        if event.after_state and event.after_state.get("email") == "nonexistent@example.com":
            matching_event = event
            break

    assert matching_event is not None
    assert matching_event.resource_type == "user"
    assert matching_event.after_state["ip_address"] == "192.168.1.300"
    assert matching_event.after_state["user_agent"] == "TestAgent/1.0"
    assert matching_event.after_state["reason"] == "user_not_found"


@pytest.mark.asyncio
async def test_rate_limit_5_attempts_then_lockout(async_session, fake_redis, test_organization):
    """Test complete rate limiting flow: 5 failed attempts trigger lockout."""
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
        email="full_flow@example.com",
        hashed_password=hashed_password,
    )
    async_session.add(user)
    await async_session.commit()

    # Add user to organization
    from apps.api.models.organization import organization_users

    stmt = organization_users.insert().values(
        user_id=user.id,
        organization_id=test_organization.id,
        role="member",
    )
    await async_session.execute(stmt)
    await async_session.commit()

    # Attempt 5 failed logins
    for i in range(5):
        result = await auth_service.authenticate(
            "full_flow@example.com",
            "WrongPassword",
        )
        assert result is None

    # Verify user is now locked out
    is_allowed, seconds_until_unlock = await auth_service.check_rate_limit("full_flow@example.com")
    assert is_allowed is False
    assert seconds_until_unlock is not None
    assert seconds_until_unlock > 0

    # Try to authenticate with correct password (should fail due to lockout)
    result = await auth_service.authenticate(
        "full_flow@example.com",
        password,
    )
    assert result is None

    # Verify 5 audit events were created for failed attempts
    stmt = select(AuditEvent).where(
        AuditEvent.user_id == user.id,
        AuditEvent.action_type == "auth.login.failure",
    )
    result = await async_session.execute(stmt)
    audit_events = result.scalars().all()
    assert len(audit_events) == 5
