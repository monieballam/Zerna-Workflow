"""Shared fixtures for Zerna User Acceptance Tests.

Provides an API client configured for the target environment,
test user authentication, test dataset creation, and cleanup.

These fixtures support running UAT against a live or staging deployment.
Set the following environment variables before running:

    UAT_API_URL       — Base URL for the API (e.g. https://api.staging.zerna.io)
    UAT_USER_EMAIL    — Test user email
    UAT_USER_PASSWORD — Test user password

For local testing against the ASGI app (no live server required), leave
UAT_API_URL unset and the fixtures will use httpx + ASGITransport.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------
UAT_API_URL = os.environ.get("UAT_API_URL", "")
UAT_USER_EMAIL = os.environ.get("UAT_USER_EMAIL", "uat@zerna.test")
UAT_USER_PASSWORD = os.environ.get("UAT_USER_PASSWORD", "uat-test-password")

_UAT_ENV = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://zerna_test:zerna_test@localhost:5433/zerna_integration_test",
    ),
    "REDIS_URL": os.environ.get("REDIS_URL", "redis://:zerna_test_redis@localhost:6380/0"),
    "S3_ENDPOINT_URL": os.environ.get("S3_ENDPOINT_URL", "http://localhost:9002"),
    "S3_ACCESS_KEY_ID": os.environ.get("S3_ACCESS_KEY_ID", "minioadmin"),
    "S3_SECRET_ACCESS_KEY": os.environ.get("S3_SECRET_ACCESS_KEY", "minioadmin"),
    "S3_DATASETS_BUCKET": os.environ.get("S3_DATASETS_BUCKET", "zerna-datasets-test"),
    "S3_ARTIFACTS_BUCKET": os.environ.get("S3_ARTIFACTS_BUCKET", "zerna-artifacts-test"),
    "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY", "uat-test-secret-key"),
    "JWT_ALGORITHM": "HS256",
    "OTEL_EXPORTER_OTLP_ENDPOINT": os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    ),
}

for key, value in _UAT_ENV.items():
    os.environ.setdefault(key, value)

try:
    from apps.api.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass

pytestmark = [pytest.mark.uat, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Tracking list for cleanup
# ---------------------------------------------------------------------------
_created_resource_ids: dict[str, list[str]] = {
    "datasets": [],
    "runs": [],
    "annotations": [],
    "knowledge_packs": [],
    "exports": [],
}


# ---------------------------------------------------------------------------
# JWT helper (local mode)
# ---------------------------------------------------------------------------
def _make_uat_token(
    user_id=None,
    email: str = UAT_USER_EMAIL,
    expires_minutes: int = 120,
) -> str:
    """Generate a JWT for local UAT testing."""
    from jose import jwt as jose_jwt

    uid = user_id or uuid4()
    now = datetime.utcnow()
    payload = {
        "sub": str(uid),
        "email": email,
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    return jose_jwt.encode(
        payload,
        _UAT_ENV["JWT_SECRET_KEY"],
        algorithm=_UAT_ENV["JWT_ALGORITHM"],
    )


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Local ASGI engine + seed data (used when UAT_API_URL is empty)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def _local_engine():
    """Create an async engine for local UAT testing."""
    if UAT_API_URL:
        yield None
        return

    from sqlalchemy.ext.asyncio import create_async_engine

    from apps.api.models import Base

    engine = create_async_engine(
        _UAT_ENV["DATABASE_URL"],
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def _local_seed_data(_local_engine):
    """Seed a test org + user for local UAT."""
    if UAT_API_URL or _local_engine is None:
        yield {"org_id": None, "user_id": None}
        return

    from zerna_contracts.enums import UserRole
    from sqlalchemy import insert
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from apps.api.models import Organization, User
    from apps.api.models.organization import OrganizationUser

    sf = async_sessionmaker(_local_engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        org_id, user_id = uuid4(), uuid4()
        org = Organization(
            id=org_id,
            name="UAT Test Org",
            storage_quota_gb=100,
            compute_quota_runs=10,
        )
        user = User(
            id=user_id,
            email=UAT_USER_EMAIL,
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$uat_hash",
        )
        session.add(org)
        session.add(user)
        await session.flush()
        await session.execute(
            insert(OrganizationUser).values(
                organization_id=org_id,
                user_id=user_id,
                role=UserRole.ADMIN,
                joined_at=datetime.utcnow(),
            )
        )
        await session.commit()
        yield {"org_id": org_id, "user_id": user_id}


# ---------------------------------------------------------------------------
# API client fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def api_client(
    _local_engine,
    _local_seed_data,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an authenticated AsyncClient for UAT.

    When UAT_API_URL is set, the client targets the remote server.
    Otherwise it uses ASGITransport against the local FastAPI app.
    """
    if UAT_API_URL:
        # Remote mode — authenticate via login endpoint
        async with AsyncClient(base_url=UAT_API_URL, timeout=30.0) as login_client:
            resp = await login_client.post(
                "/v1/auth/login",
                json={"email": UAT_USER_EMAIL, "password": UAT_USER_PASSWORD},
            )
            token = resp.json().get("access_token", "")

        async with AsyncClient(
            base_url=UAT_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        ) as client:
            yield client
    else:
        # Local mode — ASGI transport with generated JWT
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from apps.api.dependencies import get_db
        from apps.api.main import app

        async def _override_get_db():
            sf = async_sessionmaker(
                _local_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with sf() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        token = _make_uat_token(user_id=_local_seed_data["user_id"])
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://uat-test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        ) as client:
            yield client
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test dataset fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_dataset(api_client: AsyncClient):
    """Create a test dataset and return its metadata. Cleaned up after test."""
    resp = await api_client.post(
        "/v1/datasets",
        params={"name": f"UAT-Dataset-{uuid4().hex[:8]}", "description": "UAT test dataset"},
    )
    if resp.status_code == 201:
        data = resp.json()
        _created_resource_ids["datasets"].append(data["id"])
        yield data
    else:
        yield {"id": str(uuid4()), "name": "fallback-dataset", "_created": False}


# ---------------------------------------------------------------------------
# Cleanup fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(autouse=True)
async def _cleanup_resources(api_client: AsyncClient):
    """Delete resources created during each test."""
    yield
    for ds_id in _created_resource_ids["datasets"]:
        try:
            await api_client.delete(f"/v1/datasets/{ds_id}")
        except Exception:
            pass
    for key in _created_resource_ids:
        _created_resource_ids[key].clear()
