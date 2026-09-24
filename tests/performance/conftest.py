"""Shared fixtures for performance testing.

Provides mock DB sessions, mock Redis, mock S3, and a FastAPI test client
configured for measuring API-side performance without external dependencies.
"""

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Environment variables — set before any application code imports Settings
# ---------------------------------------------------------------------------
_PERF_ENV = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "postgresql+asyncpg://perf:perf@localhost:5432/perf",
    "REDIS_URL": "redis://localhost:6379/15",
    "S3_ENDPOINT_URL": "http://localhost:19000",
    "S3_ACCESS_KEY_ID": "minioadmin",
    "S3_SECRET_ACCESS_KEY": "minioadmin",
    "S3_DATASETS_BUCKET": "zerna-datasets-perf",
    "S3_ARTIFACTS_BUCKET": "zerna-artifacts-perf",
    "JWT_SECRET_KEY": "perf-test-secret-key",
    "JWT_ALGORITHM": "HS256",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
}

# Force env vars BEFORE any app code is imported (dependencies.py creates
# the engine at module level, so the DATABASE_URL must already be set).
for key, value in _PERF_ENV.items():
    os.environ[key] = value

# Clear any cached Settings so our env vars take effect
try:
    from apps.api.config import get_settings

    get_settings.cache_clear()
except Exception:
    pass


pytestmark = [pytest.mark.slow, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fake DB session that returns empty results
# ---------------------------------------------------------------------------
class FakeResult:
    """Minimal SQLAlchemy result stand-in."""

    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value if self._value is not None else 0

    def scalars(self):
        return self

    def all(self):
        return []

    def unique(self):
        return self


class FakeDBSession:
    """Lightweight async DB session mock for performance tests."""

    async def execute(self, *args, **kwargs):
        return FakeResult()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass

    def add(self, obj):
        pass


@pytest_asyncio.fixture
async def fake_db() -> FakeDBSession:
    return FakeDBSession()


# ---------------------------------------------------------------------------
# Mock Redis
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=[])
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=-2)
    redis.ping = AsyncMock(return_value=True)
    # Sorted set ops used by rate limiter
    redis.zremrangebyscore = AsyncMock(return_value=0)
    redis.zcard = AsyncMock(return_value=0)
    redis.zadd = AsyncMock(return_value=1)
    return redis


# ---------------------------------------------------------------------------
# Mock S3
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_s3() -> MagicMock:
    s3 = MagicMock()
    s3.upload_file = MagicMock(return_value={"ETag": '"abc123"'})
    s3.generate_presigned_url = MagicMock(return_value="https://s3.example.com/file")
    s3.head_object = MagicMock(return_value={"ContentLength": 1024})
    return s3


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------
def make_perf_token(user_id: UUID | None = None, email: str = "perf@zerna.test") -> str:
    """Generate a valid JWT for performance tests."""
    from jose import jwt as jose_jwt

    uid = user_id or uuid4()
    now = datetime.utcnow()
    payload = {
        "sub": str(uid),
        "email": email,
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
    }
    return jose_jwt.encode(
        payload, _PERF_ENV["JWT_SECRET_KEY"], algorithm=_PERF_ENV["JWT_ALGORITHM"]
    )


# ---------------------------------------------------------------------------
# FastAPI test client with mocked dependencies
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def perf_client(mock_redis: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient with all external deps mocked.

    This measures pure API-layer performance: routing, middleware,
    serialization, and validation — without DB/Redis/S3 latency.
    """
    import apps.api.dependencies as deps
    from apps.api.dependencies import get_db, get_redis
    from apps.api.main import app

    async def _override_get_db():
        yield FakeDBSession()

    async def _override_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis

    # The rate-limiting middleware calls get_redis() directly (not via Depends),
    # so we also patch the module-level redis_client.
    original_redis_client = deps.redis_client
    deps.redis_client = mock_redis

    token = make_perf_token()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://perf-test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client

    deps.redis_client = original_redis_client
    app.dependency_overrides.clear()
