"""Property-based tests for LLM pathway interpretation.

**Property 39: LLM Pathway Interpretation**
**Validates: Requirements 25.9**
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.services.llm_client import LLMClient

# ── Strategies ─────────────────────────────────────────────────────────────────

pathway_pattern_st = st.fixed_dictionaries(
    {
        "pathway_name": st.text(min_size=3, max_size=30),
        "pathway_id": st.text(min_size=3, max_size=20),
        "datasets_present": st.lists(st.uuids().map(str), min_size=2, max_size=5),
        "aggregated_score": st.floats(min_value=0.01, max_value=10.0, allow_nan=False),
        "p_value": st.floats(min_value=0.0001, max_value=0.05, allow_nan=False),
        "confidence": st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    }
)

patterns_st = st.lists(pathway_pattern_st, min_size=1, max_size=20)

model_st = st.sampled_from(["gpt-4", "gpt-4-turbo", "claude-3-opus-20240229"])


# ── Mock LLM response factory ──────────────────────────────────────────────────


def make_mock_llm_response(model: str) -> dict[str, Any]:
    """Build a realistic mock LLM API response."""
    return {
        "interpretation": "These pathways suggest activation of immune response.",
        "hypotheses": [
            "Hypothesis 1: Pathway X drives tumor immune evasion.",
            "Hypothesis 2: Pathway Y correlates with treatment resistance.",
            "Hypothesis 3: Combined activation predicts poor prognosis.",
        ],
        "suggested_experiments": [
            "Perform CRISPR knockout of pathway X in tumor cell lines.",
            "Validate findings in patient cohort with survival data.",
        ],
        "model_used": model,
        "cost_usd": 0.05,
    }


# ── Properties ─────────────────────────────────────────────────────────────────


@pytest.mark.property
class TestLLMPathwayInterpretation:
    """Property 39: LLM Pathway Interpretation

    For any set of pathway patterns, the LLM client should:
    - Return a non-empty interpretation string
    - Return a list of hypotheses
    - Track cost per call
    - Serve identical queries from cache (cost=0)
    - Retry on failure up to 3 times
    - Return empty-pattern response without calling LLM
    """

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=100)
    def test_interpretation_is_non_empty_string(self, patterns, model):
        """Property: LLM response always contains a non-empty interpretation.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)

        async def run():
            with patch.object(LLMClient, "_invoke", new=AsyncMock(return_value=mock_response)):
                client = LLMClient(redis_client=None)
                result = await client.interpret_pathways(patterns=patterns, model=model)
                assert isinstance(result.interpretation, str)
                assert len(result.interpretation) > 0, "Interpretation must be non-empty"

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=100)
    def test_hypotheses_is_list(self, patterns, model):
        """Property: LLM response always returns a list of hypotheses.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)

        async def run():
            with patch.object(LLMClient, "_invoke", new=AsyncMock(return_value=mock_response)):
                client = LLMClient(redis_client=None)
                result = await client.interpret_pathways(patterns=patterns, model=model)
                assert isinstance(result.hypotheses, list), "Hypotheses must be a list"

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=100)
    def test_cost_is_non_negative(self, patterns, model):
        """Property: LLM cost is always non-negative.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)

        async def run():
            with patch.object(LLMClient, "_invoke", new=AsyncMock(return_value=mock_response)):
                client = LLMClient(redis_client=None)
                result = await client.interpret_pathways(patterns=patterns, model=model)
                assert result.cost_usd >= 0.0, f"Cost must be ≥0, got {result.cost_usd}"

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=50)
    def test_cache_hit_returns_zero_cost(self, patterns, model):
        """Property: a cache hit returns cost_usd=0 and from_cache=True.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)
        cached_data = {k: v for k, v in mock_response.items()}

        async def run():
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=json.dumps(cached_data).encode())

            client = LLMClient(redis_client=mock_redis)
            result = await client.interpret_pathways(patterns=patterns, model=model)

            assert result.from_cache is True, "Cache hit must set from_cache=True"
            assert result.cost_usd == 0.0, f"Cache hit must have cost_usd=0, got {result.cost_usd}"

        asyncio.get_event_loop().run_until_complete(run())

    @given(model=model_st)
    @settings(max_examples=50)
    def test_empty_patterns_returns_without_llm_call(self, model):
        """Property: empty pattern list returns immediately without calling LLM.

        **Validates: Requirements 25.9**
        """

        async def run():
            invoke_mock = AsyncMock()
            with patch.object(LLMClient, "_invoke", new=invoke_mock):
                client = LLMClient(redis_client=None)
                result = await client.interpret_pathways(patterns=[], model=model)

                invoke_mock.assert_not_called()
                assert result.cost_usd == 0.0
                assert isinstance(result.interpretation, str)

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=50, deadline=None)
    def test_retry_on_failure_raises_after_max_attempts(self, patterns, model):
        """Property: after MAX_ATTEMPTS failures, RuntimeError is raised.

        **Validates: Requirements 25.9**
        """

        async def run():
            invoke_mock = AsyncMock(side_effect=Exception("API error"))
            with (
                patch.object(LLMClient, "_invoke", new=invoke_mock),
                patch("apps.api.services.llm_client.asyncio.sleep", new=AsyncMock()),
            ):
                client = LLMClient(redis_client=None)
                with pytest.raises(RuntimeError, match="failed after"):
                    await client.interpret_pathways(patterns=patterns, model=model)

                assert invoke_mock.call_count == LLMClient.MAX_ATTEMPTS, (
                    f"Expected {LLMClient.MAX_ATTEMPTS} attempts, got {invoke_mock.call_count}"
                )

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=50)
    def test_successful_response_is_cached(self, patterns, model):
        """Property: a successful LLM response is written to cache.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)

        async def run():
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)  # cache miss
            mock_redis.setex = AsyncMock()

            with patch.object(LLMClient, "_invoke", new=AsyncMock(return_value=mock_response)):
                client = LLMClient(redis_client=mock_redis)
                await client.interpret_pathways(patterns=patterns, model=model)

            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            # Verify TTL is set to CACHE_TTL_SECONDS
            assert call_args[0][1] == LLMClient.CACHE_TTL_SECONDS, (
                f"Cache TTL should be {LLMClient.CACHE_TTL_SECONDS}s"
            )

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st)
    @settings(max_examples=50, deadline=None)
    def test_unsupported_model_raises_value_error(self, patterns):
        """Property: unsupported model names raise ValueError.

        **Validates: Requirements 25.9**
        """

        async def run():
            with patch("apps.api.services.llm_client.asyncio.sleep", new=AsyncMock()):
                client = LLMClient(redis_client=None)
                with pytest.raises((ValueError, RuntimeError)):
                    await client.interpret_pathways(
                        patterns=patterns, model="unsupported-model-xyz"
                    )

        asyncio.get_event_loop().run_until_complete(run())

    @given(patterns=patterns_st, model=model_st)
    @settings(max_examples=50)
    def test_model_used_matches_requested_model(self, patterns, model):
        """Property: model_used in response matches the requested model.

        **Validates: Requirements 25.9**
        """
        mock_response = make_mock_llm_response(model)

        async def run():
            with patch.object(LLMClient, "_invoke", new=AsyncMock(return_value=mock_response)):
                client = LLMClient(redis_client=None)
                result = await client.interpret_pathways(patterns=patterns, model=model)
                assert result.model_used == model, (
                    f"model_used '{result.model_used}' should match requested '{model}'"
                )

        asyncio.get_event_loop().run_until_complete(run())
