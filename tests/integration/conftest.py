"""Integration test fixtures for Zerna platform.

Connects to real PostgreSQL, Redis, and MinIO services started via
docker-compose.integration.yml. Uses different ports (5433, 6380, 9002)
to avoid conflicts with the dev environment.
"""

import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from zerna_contracts.enums import UserRole
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.models import Base, Organization, User
from apps.api.models.organization import OrganizationUser

# ---------------------------------------------------------------------------
# Environment variables – set before any application code imports Settings
# ---------------------------------------------------------------------------
_INTEGRATION_ENV = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "postgresql+asyncpg://zerna_test:zerna_test@localhost:5433/zerna_integration_test",
    "REDIS_URL": "redis://:zerna_test_redis@localhost:6380/0",
    "S3_ENDPOINT_URL": "http://localhost:9002",
    "S3_ACCESS_KEY_ID": "minioadmin",
    "S3_SECRET_ACCESS_KEY": "minioadmin",
    "S3_DATASETS_BUCKET": "zerna-datasets-test",
    "S3_ARTIFACTS_BUCKET": "zerna-artifacts-test",
    "JWT_SECRET_KEY": "integration-test-secret-key",
    "JWT_ALGORITHM": "HS256",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
}

for key, value in _INTEGRATION_ENV.items():
    os.environ[key] = value

# Clear any cached Settings so the integration env always wins.
try:
    from apps.api.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass


def _sync_cached_app_settings() -> None:
    """Rebind module-level settings handles if app modules were imported early."""
    try:
        from apps.api.config import get_settings
    except Exception:
        return

    settings = get_settings()

    dependencies = sys.modules.get("apps.api.dependencies")
    if dependencies is not None:
        dependencies.settings = settings
        dependencies._engine = None
        dependencies._async_session_factory = None
        dependencies.redis_client = None

    rate_limiting = sys.modules.get("apps.api.middleware.rate_limiting")
    if rate_limiting is not None:
        rate_limiting.settings = settings

    main = sys.modules.get("apps.api.main")
    if main is not None:
        main.settings = settings


# Synchronous DATABASE_URL for Alembic / create_all (without +asyncpg)
SYNC_DATABASE_URL = "postgresql://zerna_test:zerna_test@localhost:5433/zerna_integration_test"
ASYNC_DATABASE_URL = _INTEGRATION_ENV["DATABASE_URL"]


# ---------------------------------------------------------------------------
# Pytest markers
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Event loop (session-scoped for async fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database engine & schema setup (session-scoped)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def integration_engine():
    """Create an async engine pointing at the real PostgreSQL test database.

    Creates all tables at the start and drops them at the end of the session.
    """
    engine = create_async_engine(
        ASYNC_DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        poolclass=NullPool,
    )

    # Create all tables from the ORM metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown – drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test database session with automatic rollback
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_session(integration_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session that rolls back after each test."""
    session_factory = async_sessionmaker(
        integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        # Roll back any uncommitted changes so tests stay isolated
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def reset_database(integration_engine) -> AsyncGenerator[None, None]:
    """Reset all tables before and after each test to keep committed state isolated."""
    table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))

    async def _truncate() -> None:
        if not table_names:
            return
        async with integration_engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))

    await _truncate()
    yield
    await _truncate()


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[aioredis.Redis, None]:
    """Connect to the real Redis instance and flush the test DB after each test."""
    client = aioredis.from_url(
        _INTEGRATION_ENV["REDIS_URL"],
        encoding="utf-8",
        decode_responses=False,
    )
    yield client
    await client.flushdb()
    await client.aclose()


# ---------------------------------------------------------------------------
# S3 / MinIO client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def s3_client():
    """Create a boto3 S3 client pointing at the MinIO test instance."""
    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        endpoint_url=_INTEGRATION_ENV["S3_ENDPOINT_URL"],
        aws_access_key_id=_INTEGRATION_ENV["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=_INTEGRATION_ENV["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4"),
    )
    yield client


# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------
TEST_USER_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$integration_test_hash"


@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession) -> Organization:
    """Create and return a test organization."""
    org = Organization(
        id=uuid4(),
        name="Integration Test Organization",
        storage_quota_gb=100,
        compute_quota_runs=5,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_org: Organization) -> User:
    """Create a test user and associate them with the test organization."""
    user = User(
        id=uuid4(),
        email=f"integration-{uuid4().hex[:12]}@zerna.test",
        hashed_password=TEST_USER_PASSWORD_HASH,
    )
    db_session.add(user)
    await db_session.flush()

    # Associate user with organization as admin
    await db_session.execute(
        insert(OrganizationUser).values(
            organization_id=test_org.id,
            user_id=user.id,
            role=UserRole.ADMIN,
            joined_at=datetime.utcnow(),
        )
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# JWT token helper
# ---------------------------------------------------------------------------
def _make_access_token(user_id, email: str, expires_minutes: int = 60) -> str:
    """Generate a valid JWT access token for integration tests."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    return jwt.encode(
        payload,
        _INTEGRATION_ENV["JWT_SECRET_KEY"],
        algorithm=_INTEGRATION_ENV["JWT_ALGORITHM"],
    )  # python-jose compatible


# ---------------------------------------------------------------------------
# Authenticated HTTP client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def authenticated_client(
    integration_engine,
    test_user: User,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient with a valid Bearer token.

    The client talks to the real FastAPI app but overrides the DB dependency
    to use the integration test engine.
    """
    _sync_cached_app_settings()

    from apps.api.dependencies import get_db
    from apps.api.main import app
    from apps.api.middleware.auth import get_current_user

    # Override get_db to use the integration test engine
    async def _override_get_db():
        session_factory = async_sessionmaker(
            integration_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

    async def _override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    token = _make_access_token(test_user.id, test_user.email)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthenticated_client(
    integration_engine,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient without authentication headers."""
    _sync_cached_app_settings()

    from apps.api.dependencies import get_db
    from apps.api.main import app

    async def _override_get_db():
        session_factory = async_sessionmaker(
            integration_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
