"""Property-based tests for API rate limit enforcement.

**Property 43: Rate Limit Enforcement**

For any user, when the number of requests within a 60-second window exceeds
the configured limit, subsequent requests must be rejected with HTTP 429 and
a Retry-After header.

**Validates: Requirements 29.1, 29.2**
"""

import asyncio
from uuid import uuid4

import pytest
from fakeredis import aioredis as fakeredis
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.middleware.rate_limiting import check_rate_limit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_redis():
    redis = fakeredis.FakeRedis(decode_responses=False)
    return redis


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestRateLimitEnforcement:
    """Property 43: Rate Limit Enforcement."""

    @given(
        limit=st.integers(min_value=1, max_value=20),
        num_requests=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=60)
    def test_requests_beyond_limit_are_rejected(self, limit, num_requests):
        """Property: Requests exceeding the limit within the window are rejected."""

        async def run():
            redis = await _make_redis()
            user_id = f"user:{uuid4()}"

            allowed_count = 0
            rejected_count = 0

            for _ in range(num_requests):
                is_allowed, remaining, retry_after = await check_rate_limit(
                    redis, user_id, limit=limit, window_seconds=60
                )
                if is_allowed:
                    allowed_count += 1
                else:
                    rejected_count += 1

            await redis.aclose()

            # Exactly `limit` requests should be allowed
            assert allowed_count == min(num_requests, limit), (
                f"Expected {min(num_requests, limit)} allowed, got {allowed_count}"
            )
            # Remaining requests beyond limit should be rejected
            expected_rejected = max(0, num_requests - limit)
            assert rejected_count == expected_rejected, (
                f"Expected {expected_rejected} rejected, got {rejected_count}"
            )

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        limit=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=30)
    def test_rejected_requests_include_retry_after(self, limit):
        """Property: Rejected requests always include a positive retry_after value."""

        async def run():
            redis = await _make_redis()
            user_id = f"user:{uuid4()}"

            # Exhaust the limit
            for _ in range(limit):
                await check_rate_limit(redis, user_id, limit=limit, window_seconds=60)

            # Next request should be rejected with retry_after > 0
            is_allowed, remaining, retry_after = await check_rate_limit(
                redis, user_id, limit=limit, window_seconds=60
            )

            await redis.aclose()

            assert is_allowed is False
            assert retry_after > 0, "Rejected requests must include positive retry_after"

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        limit=st.integers(min_value=2, max_value=15),
    )
    @settings(max_examples=30)
    def test_remaining_tokens_decrease_monotonically(self, limit):
        """Property: Remaining token count decreases with each allowed request."""

        async def run():
            redis = await _make_redis()
            user_id = f"user:{uuid4()}"

            previous_remaining = limit  # Start with full bucket

            for i in range(limit):
                is_allowed, remaining, _ = await check_rate_limit(
                    redis, user_id, limit=limit, window_seconds=60
                )
                assert is_allowed is True
                assert remaining < previous_remaining, (
                    f"Remaining should decrease: was {previous_remaining}, now {remaining}"
                )
                previous_remaining = remaining

            await redis.aclose()

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        limit=st.integers(min_value=1, max_value=10),
        num_users=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=30)
    def test_rate_limits_are_isolated_per_user(self, limit, num_users):
        """Property: Rate limit buckets are independent per user."""

        async def run():
            redis = await _make_redis()
            user_ids = [f"user:{uuid4()}" for _ in range(num_users)]

            # Exhaust limit for user[0]
            for _ in range(limit):
                await check_rate_limit(redis, user_ids[0], limit=limit, window_seconds=60)

            # user[0] should be at limit
            is_allowed_0, _, _ = await check_rate_limit(
                redis, user_ids[0], limit=limit, window_seconds=60
            )
            assert is_allowed_0 is False, "user[0] should be rate limited"

            # All other users should still have full capacity
            for uid in user_ids[1:]:
                is_allowed, remaining, _ = await check_rate_limit(
                    redis, uid, limit=limit, window_seconds=60
                )
                assert is_allowed is True, f"User {uid} should not be rate limited"
                assert remaining == limit - 1

            await redis.aclose()

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        limit=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=20)
    def test_zero_requests_never_rate_limited(self, limit):
        """Property: A fresh user with no prior requests is never rate limited."""

        async def run():
            redis = await _make_redis()
            user_id = f"user:{uuid4()}"

            # First request should always be allowed
            is_allowed, remaining, retry_after = await check_rate_limit(
                redis, user_id, limit=limit, window_seconds=60
            )

            await redis.aclose()

            assert is_allowed is True
            assert retry_after == 0

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        limit=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20)
    def test_rate_limit_check_is_deterministic(self, limit):
        """Property: Calling check_rate_limit with same state returns consistent results."""

        async def run():
            redis = await _make_redis()
            user_id = f"user:{uuid4()}"

            # Exhaust limit
            for _ in range(limit):
                await check_rate_limit(redis, user_id, limit=limit, window_seconds=60)

            # Both subsequent calls should be rejected
            result1 = await check_rate_limit(redis, user_id, limit=limit, window_seconds=60)
            result2 = await check_rate_limit(redis, user_id, limit=limit, window_seconds=60)

            await redis.aclose()

            assert result1[0] is False
            assert result2[0] is False

        asyncio.get_event_loop().run_until_complete(run())
