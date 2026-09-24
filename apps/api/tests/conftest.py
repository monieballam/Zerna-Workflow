"""Shared test fixtures for Zerna API tests."""

import asyncio
import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pandas as pd

# Disable Arrow-backed strings (pandas 3.0 default) so anndata can write h5ad
pd.options.future.infer_string = False

import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from apps.api.models import Base, Organization, User

# Set test environment variables BEFORE any app imports that trigger Settings/engine creation
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_for_testing_only")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test_access_key")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test_secret_key")
os.environ.setdefault("S3_DATASETS_BUCKET", "test-datasets-bucket")
os.environ.setdefault("S3_ARTIFACTS_BUCKET", "test-artifacts-bucket")


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create a synchronous database session for testing."""
    with Session(engine) as session:
        yield session


@pytest_asyncio.fixture
async def async_engine():
    """Create an async in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create an async database session for testing."""
    async_session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    """Create a fake Redis client for testing."""
    redis = fakeredis.FakeRedis(decode_responses=False)
    yield redis
    await redis.flushall()
    await redis.aclose()


@pytest_asyncio.fixture
async def test_user(async_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test_hash",  # Placeholder hash
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_organization(async_session: AsyncSession) -> Organization:
    """Create a test organization."""
    org = Organization(
        id=uuid4(),
        name="Test Organization",
        storage_quota_gb=1000,
        compute_quota_runs=10,
    )
    async_session.add(org)
    await async_session.commit()
    await async_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def async_client(async_engine) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing API endpoints."""
    from apps.api.dependencies import get_db
    from apps.api.main import app

    # Override the get_db dependency to use the test database
    async def override_get_db():
        async_session_factory = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Create async client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()
