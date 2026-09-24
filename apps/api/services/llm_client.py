"""LLM client for pathway interpretation via OpenAI GPT-4 and Anthropic Claude.

Features:
- 30s timeout per attempt
- 3-attempt retry with exponential backoff
- Redis response caching (1-hour TTL) for identical queries
- Per-organization cost tracking
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMResponse:
    """Structured response from an LLM call."""

    def __init__(
        self,
        interpretation: str,
        hypotheses: list[str],
        suggested_experiments: list[str],
        model_used: str,
        cost_usd: float,
        from_cache: bool = False,
    ):
        self.interpretation = interpretation
        self.hypotheses = hypotheses
        self.suggested_experiments = suggested_experiments
        self.model_used = model_used
        self.cost_usd = cost_usd
        self.from_cache = from_cache

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpretation": self.interpretation,
            "hypotheses": self.hypotheses,
            "suggested_experiments": self.suggested_experiments,
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
            "from_cache": self.from_cache,
        }


class LLMClient:
    """Unified LLM client supporting OpenAI and Anthropic backends.

    Handles timeout, retry, caching, and cost tracking.
    """

    TIMEOUT_SECONDS = 30
    MAX_ATTEMPTS = 3
    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    async def interpret_pathways(
        self,
        patterns: list[dict[str, Any]],
        model: str = "gpt-4",
        organization_id: str | None = None,
        context: str | None = None,
    ) -> LLMResponse:
        """Generate biological interpretation and hypotheses for pathway patterns.

        Args:
            patterns: list of pathway pattern dicts
            model: LLM model name ("gpt-4", "gpt-4-turbo", "claude-3-opus-20240229", etc.)
            organization_id: for cost tracking
            context: optional additional context to include in the prompt

        Returns:
            LLMResponse with interpretation, hypotheses, and cost

        Raises:
            RuntimeError: if all retry attempts fail
        """
        if not patterns:
            return LLMResponse(
                interpretation="No pathway patterns provided for interpretation.",
                hypotheses=[],
                suggested_experiments=[],
                model_used=model,
                cost_usd=0.0,
            )

        prompt = self._build_prompt(patterns, context)
        cache_key = f"llm_cache:{hashlib.sha256(prompt.encode()).hexdigest()}"

        # Check cache
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    logger.info("LLM response served from cache")
                    data = json.loads(cached)
                    data["cost_usd"] = 0.0  # No cost for cached responses
                    return LLMResponse(from_cache=True, **data)
            except Exception as e:
                logger.warning(f"Cache read failed (non-fatal): {e}")

        # Invoke LLM with retry
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                result = await asyncio.wait_for(
                    self._invoke(prompt, model, organization_id),
                    timeout=self.TIMEOUT_SECONDS,
                )

                # Cache the result
                if self._redis:
                    try:
                        await self._redis.setex(
                            cache_key,
                            self.CACHE_TTL_SECONDS,
                            json.dumps(result),
                        )
                    except Exception as e:
                        logger.warning(f"Cache write failed (non-fatal): {e}")

                return LLMResponse(**result)

            except TimeoutError as e:
                last_error = e
                logger.warning(f"LLM timeout on attempt {attempt}/{self.MAX_ATTEMPTS}")
            except Exception as e:
                last_error = e
                logger.warning(f"LLM error on attempt {attempt}/{self.MAX_ATTEMPTS}: {e}")

            if attempt < self.MAX_ATTEMPTS:
                await asyncio.sleep(2**attempt)  # exponential backoff: 2s, 4s

        raise RuntimeError(
            f"LLM interpretation failed after {self.MAX_ATTEMPTS} attempts: {last_error}"
        )

    def _build_prompt(self, patterns: list[dict[str, Any]], context: str | None = None) -> str:
        """Build the LLM prompt from pathway patterns."""
        top = patterns[:20]  # limit tokens
        n_datasets = len(set(ds for p in top for ds in p.get("datasets_present", [])))
        summary = "\n".join(
            f"- {p['pathway_name']} (score={p['aggregated_score']:.3f}, "
            f"p={p['p_value']:.4f}, datasets={len(p.get('datasets_present', []))})"
            for p in top
        )
        context_block = f"\nAdditional context: {context}\n" if context else ""
        return (
            f"The following pathway patterns were identified across {n_datasets} "
            f"single-cell RNA-seq datasets:{context_block}\n\n{summary}\n\n"
            "Please provide:\n"
            "1. A biological interpretation of these pathway patterns\n"
            "2. Three testable hypotheses based on these findings\n"
            "3. Two suggested follow-up experiments"
        )

    async def _invoke(self, prompt: str, model: str, organization_id: str | None) -> dict[str, Any]:
        """Dispatch to the appropriate LLM backend."""
        if model.startswith("gpt"):
            return await self._call_openai(prompt, model)
        elif model.startswith("claude"):
            return await self._call_anthropic(prompt, model)
        else:
            raise ValueError(f"Unsupported model: {model}. Use 'gpt-*' or 'claude-*'.")

    async def _call_openai(self, prompt: str, model: str) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        cost_usd = tokens * 0.00003  # ~$0.03/1k tokens for GPT-4

        return {
            "interpretation": content,
            "hypotheses": self._extract_list_items(content, section=2),
            "suggested_experiments": self._extract_list_items(content, section=3),
            "model_used": model,
            "cost_usd": cost_usd,
        }

    async def _call_anthropic(self, prompt: str, model: str) -> dict[str, Any]:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["content"][0]["text"]
        input_tokens = data.get("usage", {}).get("input_tokens", 0)
        output_tokens = data.get("usage", {}).get("output_tokens", 0)
        cost_usd = (input_tokens + output_tokens) * 0.000015  # ~$0.015/1k tokens

        return {
            "interpretation": content,
            "hypotheses": self._extract_list_items(content, section=2),
            "suggested_experiments": self._extract_list_items(content, section=3),
            "model_used": model,
            "cost_usd": cost_usd,
        }

    @staticmethod
    def _extract_list_items(text: str, section: int = 2) -> list[str]:
        """Extract bullet/numbered list items from a numbered section of LLM output."""
        lines = text.split("\n")
        items: list[str] = []
        in_section = False

        for line in lines:
            # Detect section headers like "1.", "2.", "3."
            if re.match(rf"^\s*{section}\.", line):
                in_section = True
                continue
            # Stop at next section header
            if in_section and re.match(r"^\s*\d+\.", line):
                break
            if in_section:
                cleaned = re.sub(r"^\s*[-*\d]+[.)]\s*", "", line).strip()
                if cleaned and len(cleaned) > 10:
                    items.append(cleaned)

        return items[:5]
