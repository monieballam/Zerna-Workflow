"""FastAPI dependencies for database, Redis, and services."""

from collections.abc import AsyncGenerator
from typing import cast

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.config import get_settings
from apps.api.services.auth_service import AuthService
from apps.api.services.cache_service import CacheService

# Database engine and session factory (lazy initialization)
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Lazily create the async database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.async_database_url,
            echo=settings.sql_echo,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily create the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


# Redis client
redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get Redis client instance."""
    global redis_client
    if redis_client is None:
        settings = get_settings()
        redis_client = await aioredis.from_url(
            settings.resolved_redis_url,
            encoding="utf-8",
            decode_responses=False,  # We'll handle decoding manually
        )
    return cast(aioredis.Redis, redis_client)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    session_factory = _get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_cache_service() -> CacheService:
    """Get CacheService dependency backed by the shared Redis client."""
    redis = await get_redis()
    return CacheService(redis)


async def get_auth_service(
    db: AsyncSession = Depends(get_db),
) -> AuthService:
    """Get AuthService dependency.

    Args:
        db: Database session from get_db dependency

    Returns:
        AuthService instance
    """
    settings = get_settings()
    redis = await get_redis()

    return AuthService(
        db=db,
        redis_client=redis,
        jwt_secret_key=settings.jwt_secret_key,
        jwt_algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
    )
