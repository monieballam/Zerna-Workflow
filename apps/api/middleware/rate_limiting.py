"""Token bucket rate limiting middleware for Zerna API.

Implements per-user rate limiting using a token bucket algorithm stored in Redis.
Admin users are exempt from rate limits per Requirement 29.4.

Requirements: 29.1, 29.2, 29.3, 29.4
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from apps.api.config import get_settings
from apps.api.metrics import increment_error

logger = logging.getLogger(__name__)

# Redis key prefix for rate limit buckets
_RATE_LIMIT_KEY_PREFIX = "rate_limit:"

# Paths exempt from rate limiting (health checks, etc.)
_EXEMPT_PATHS = {"/health", "/v1/health", "/docs", "/openapi.json", "/redoc"}

# Auth routes use their own throttling (failed-login lockout in AuthService). Counting them
# toward the global per-IP bucket causes 429s from the Next.js server (one shared IP).
_AUTH_PATH_PREFIX = "/v1/auth"


def _extract_user_id_from_token(token: str) -> str | None:
    """Extract user ID from JWT token without full verification (for rate limiting only).

    We do a lightweight decode here — full verification happens in the auth middleware.
    Returns None if the token cannot be decoded.
    """
    try:
        settings = get_settings()
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        sub = payload.get("sub")
        return sub if isinstance(sub, str) else None
    except (JWTError, Exception):
        return None


def _extract_user_role_from_token(token: str) -> str | None:
    """Extract user role from JWT token for admin exemption check."""
    try:
        settings = get_settings()
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        role = payload.get("role")
        return role if isinstance(role, str) else None
    except (JWTError, Exception):
        return None


async def check_rate_limit(
    redis_client: Any,
    user_id: str,
    limit: int,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """Token bucket rate limit check using Redis sliding window.

    Uses a sorted set where each member is a unique request ID scored by timestamp.
    The window is [now - window_seconds, now].

    Args:
        redis_client: Async Redis client
        user_id: User identifier for the bucket key
        limit: Maximum requests allowed per window
        window_seconds: Window duration in seconds

    Returns:
        Tuple of (is_allowed, remaining_tokens, retry_after_seconds)
    """
    import uuid as _uuid

    key = f"{_RATE_LIMIT_KEY_PREFIX}{user_id}"
    now = int(time.time())
    window_start = now - window_seconds

    # Remove expired entries first
    await redis_client.zremrangebyscore(key, 0, window_start)

    # Count current requests in window
    current_count = await redis_client.zcard(key)

    if current_count >= limit:
        retry_after = window_seconds
        return False, 0, retry_after

    # Add current request with unique member to avoid collisions at same second
    member = f"{now}:{_uuid.uuid4().hex}"
    await redis_client.zadd(key, {member: now})
    await redis_client.expire(key, window_seconds + 1)

    remaining = limit - current_count - 1
    return True, remaining, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-user token bucket rate limits.

    - Reads the Bearer token from Authorization header
    - Extracts user_id for bucket keying
    - Admin users (role=admin) are exempt
    - Returns HTTP 429 with Retry-After header when limit exceeded
    - Falls back to IP-based limiting for unauthenticated requests
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        settings = get_settings()

        # Skip exempt paths
        path = request.url.path
        if path in _EXEMPT_PATHS or path.startswith(_AUTH_PATH_PREFIX):
            return await call_next(request)

        # Get Redis client — gracefully degrade if Redis is unavailable
        try:
            from apps.api.dependencies import get_redis

            redis_client = await get_redis()
        except Exception:
            logger.warning("Redis unavailable, skipping rate limiting")
            return await call_next(request)

        limit = settings.rate_limit_per_minute

        # Extract token and user identity
        auth_header = request.headers.get("Authorization", "")
        user_key: str | None = None
        is_admin = False

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = _extract_user_id_from_token(token)
            role = _extract_user_role_from_token(token)

            if user_id:
                user_key = f"user:{user_id}"
                # Admin users are exempt from rate limits (Requirement 29.4)
                if role == "admin":
                    is_admin = True

        if is_admin:
            return await call_next(request)

        # Fall back to IP-based limiting for unauthenticated requests
        if user_key is None:
            client_ip = request.client.host if request.client else "unknown"
            user_key = f"ip:{client_ip}"

        try:
            is_allowed, remaining, retry_after = await check_rate_limit(
                redis_client,
                user_key,
                limit=limit,
                window_seconds=60,
            )
        except Exception:
            logger.warning("Redis error during rate limit check, allowing request")
            return await call_next(request)

        if not is_allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"user_key": user_key, "path": request.url.path},
            )
            increment_error("rate_limit_exceeded", request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "error_type": "user_error",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests. Please slow down.",
                    "details": {"retry_after_seconds": retry_after},
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
