"""Activities for cross-dataset pathway analysis workflow."""

import logging
from datetime import datetime
from typing import Any

from temporalio import activity

from apps.api.dependencies import _get_session_factory as _get_sf
from apps.api.models.pathway import CrossDatasetAnalysis

logger = logging.getLogger(__name__)


@activity.defn
async def fetch_datasets(input: dict[str, Any]) -> dict[str, Any]:
    """Fetch pathway score summaries for each dataset (privacy-preserving).

    Only aggregated pathway scores are fetched — no raw cell-level data is shared.

    Args:
        input: dict with analysis_id, dataset_ids, pathway_database

    Returns:
        dict with dataset_summaries: list of {dataset_id, pathway_scores: {pathway_id: score}}
    """
    analysis_id = input["analysis_id"]
    dataset_ids: list[str] = input["dataset_ids"]
    pathway_database: str = input.get("pathway_database", "MSigDB")

    activity.logger.info(
        f"Fetching pathway summaries for {len(dataset_ids)} datasets "
        f"(analysis={analysis_id}, db={pathway_database})"
    )

    # Privacy-preserving: only aggregate-level scores per dataset, no raw data
    # In production this would query S3 artifacts for each dataset's pathway scores
    dataset_summaries = []
    for ds_id in dataset_ids:
        # Placeholder: real implementation reads pathway score artifacts from S3
        dataset_summaries.append(
            {
                "dataset_id": ds_id,
                "pathway_database": pathway_database,
                "pathway_scores": {},  # populated from S3 artifact in production
                "cell_count": 0,
            }
        )

    return {"dataset_summaries": dataset_summaries, "pathway_database": pathway_database}


@activity.defn
async def aggregate_pathways(input: dict[str, Any]) -> dict[str, Any]:
    """Aggregate pathway scores across datasets using meta-analysis.

    Computes cross-dataset pathway patterns with statistical significance.

    Args:
        input: dict with dataset_summaries, aggregation_method

    Returns:
        dict with patterns: list of PathwayPattern dicts
    """
    dataset_summaries: list[dict] = input["dataset_summaries"]
    aggregation_method: str = input.get("aggregation_method", "meta-analysis")

    activity.logger.info(
        f"Aggregating pathways across {len(dataset_summaries)} datasets using {aggregation_method}"
    )

    # Collect all pathway IDs present across datasets
    all_pathway_ids: set = set()
    for summary in dataset_summaries:
        all_pathway_ids.update(summary.get("pathway_scores", {}).keys())

    patterns = []
    for pathway_id in all_pathway_ids:
        scores = [
            s["pathway_scores"][pathway_id]
            for s in dataset_summaries
            if pathway_id in s.get("pathway_scores", {})
        ]
        datasets_present = [
            s["dataset_id"] for s in dataset_summaries if pathway_id in s.get("pathway_scores", {})
        ]

        if len(scores) < 2:
            # Require pattern to appear in at least 2 datasets
            continue

        # Simple meta-analysis: mean score + placeholder p-value
        # Production: use stouffer's method or fisher's combined probability
        import statistics

        aggregated_score = statistics.mean(scores)
        # Placeholder p-value — real implementation uses scipy.stats
        p_value = max(0.001, 1.0 / (len(scores) * aggregated_score + 1e-9))
        confidence = min(1.0, len(scores) / len(dataset_summaries))

        patterns.append(
            {
                "pathway_name": pathway_id,  # real impl maps ID → name via KnowledgePack
                "pathway_id": pathway_id,
                "datasets_present": datasets_present,
                "aggregated_score": aggregated_score,
                "p_value": p_value,
                "confidence": confidence,
            }
        )

    # Sort by p-value ascending (most significant first)
    patterns.sort(key=lambda p: p["p_value"])

    activity.logger.info(f"Identified {len(patterns)} cross-dataset pathway patterns")
    return {"patterns": patterns}


@activity.defn
async def call_llm(input: dict[str, Any]) -> dict[str, Any]:
    """Call LLM API to interpret pathway patterns and generate hypotheses.

    Supports OpenAI GPT-4 and Anthropic Claude. Includes 30s timeout and
    3-attempt retry. Tracks cost per organization.

    Args:
        input: dict with analysis_id, organization_id, patterns, llm_model

    Returns:
        dict with interpretation, hypotheses, model_used, cost_usd
    """
    import asyncio
    import hashlib
    import json

    analysis_id: str = input["analysis_id"]
    organization_id: str = input["organization_id"]
    patterns: list[dict] = input.get("patterns", [])
    llm_model: str = input.get("llm_model", "gpt-4")

    activity.logger.info(
        f"Calling LLM ({llm_model}) for pathway interpretation "
        f"(analysis={analysis_id}, patterns={len(patterns)})"
    )

    if not patterns:
        return {
            "interpretation": "No pathway patterns identified for interpretation.",
            "hypotheses": [],
            "model_used": llm_model,
            "cost_usd": 0.0,
        }

    # Build prompt from top patterns (limit to top 20 to control token usage)
    top_patterns = patterns[:20]
    pattern_summary = "\n".join(
        f"- {p['pathway_name']} (score={p['aggregated_score']:.3f}, "
        f"p={p['p_value']:.4f}, datasets={len(p['datasets_present'])})"
        for p in top_patterns
    )
    prompt = (
        f"The following pathway patterns were identified across {len(set(ds for p in patterns for ds in p['datasets_present']))} "
        f"single-cell RNA-seq datasets:\n\n{pattern_summary}\n\n"
        "Please provide:\n"
        "1. A biological interpretation of these pathway patterns\n"
        "2. Three testable hypotheses based on these findings\n"
        "3. Suggested follow-up experiments"
    )

    # Cache key based on prompt content
    cache_key = f"llm_cache:{hashlib.sha256(prompt.encode()).hexdigest()}"

    # Check Redis cache first
    try:
        from apps.api.dependencies import get_redis

        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            activity.logger.info("LLM response served from cache")
            result = json.loads(cached)
            result["cost_usd"] = 0.0  # cached responses have no cost
            return result
    except Exception as cache_err:
        activity.logger.warning(f"Cache check failed (non-fatal): {cache_err}")

    # Call LLM with retry logic (3 attempts, 30s timeout each)
    last_error = None
    for attempt in range(1, 4):
        try:
            result = await asyncio.wait_for(
                _invoke_llm(prompt, llm_model, organization_id),
                timeout=30.0,
            )

            # Cache successful response (TTL: 1 hour)
            try:
                from apps.api.dependencies import get_redis

                redis = await get_redis()
                await redis.setex(cache_key, 3600, json.dumps(result))
            except Exception:
                pass  # cache write failure is non-fatal

            return result

        except TimeoutError:
            last_error = f"LLM call timed out (attempt {attempt}/3)"
            activity.logger.warning(last_error)
        except Exception as e:
            last_error = f"LLM call failed (attempt {attempt}/3): {e}"
            activity.logger.warning(last_error)

        if attempt < 3:
            await asyncio.sleep(2**attempt)  # exponential backoff

    activity.logger.error(f"LLM interpretation failed after 3 attempts: {last_error}")
    return {
        "interpretation": f"LLM interpretation unavailable: {last_error}",
        "hypotheses": [],
        "model_used": llm_model,
        "cost_usd": 0.0,
    }


async def _invoke_llm(prompt: str, model: str, organization_id: str) -> dict[str, Any]:
    """Invoke the appropriate LLM API based on model name."""

    if model.startswith("gpt"):
        return await _call_openai(prompt, model, organization_id)
    elif model.startswith("claude"):
        return await _call_anthropic(prompt, model, organization_id)
    else:
        raise ValueError(f"Unsupported LLM model: {model}")


async def _call_openai(prompt: str, model: str, organization_id: str) -> dict[str, Any]:
    """Call OpenAI GPT API."""
    import os

    import httpx

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
    # Rough cost estimate: $0.03/1k tokens for GPT-4
    tokens = data.get("usage", {}).get("total_tokens", 0)
    cost_usd = tokens * 0.00003

    hypotheses = _extract_hypotheses(content)
    return {
        "interpretation": content,
        "hypotheses": hypotheses,
        "model_used": model,
        "cost_usd": cost_usd,
    }


async def _call_anthropic(prompt: str, model: str, organization_id: str) -> dict[str, Any]:
    """Call Anthropic Claude API."""
    import os

    import httpx

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
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
    # Rough cost estimate: $0.015/1k tokens for Claude
    input_tokens = data.get("usage", {}).get("input_tokens", 0)
    output_tokens = data.get("usage", {}).get("output_tokens", 0)
    cost_usd = (input_tokens + output_tokens) * 0.000015

    hypotheses = _extract_hypotheses(content)
    return {
        "interpretation": content,
        "hypotheses": hypotheses,
        "model_used": model,
        "cost_usd": cost_usd,
    }


def _extract_hypotheses(text: str) -> list[str]:
    """Extract numbered hypotheses from LLM response text."""
    import re

    lines = text.split("\n")
    hypotheses = []
    for line in lines:
        # Match lines like "1. Hypothesis text" or "- Hypothesis text"
        if re.match(r"^\s*[\d]+\.\s+", line) or re.match(r"^\s*[-*]\s+", line):
            cleaned = re.sub(r"^\s*[\d]+\.\s+|^\s*[-*]\s+", "", line).strip()
            if cleaned and len(cleaned) > 10:
                hypotheses.append(cleaned)
    return hypotheses[:5]  # cap at 5 hypotheses


@activity.defn
async def update_analysis_status(input: dict[str, Any]) -> None:
    """Persist analysis results or failure status to the database.

    Args:
        input: dict with analysis_id, status, patterns, interpretation,
               hypotheses, llm_model_used, llm_cost_usd, error_message
    """
    from uuid import UUID as _UUID

    analysis_id = _UUID(input["analysis_id"])
    status: str = input["status"]

    activity.logger.info(f"Updating analysis {analysis_id} status → {status}")

    async with _get_sf()() as db:
        from sqlalchemy import select

        stmt = select(CrossDatasetAnalysis).where(CrossDatasetAnalysis.id == analysis_id)
        result = await db.execute(stmt)
        analysis = result.scalar_one_or_none()

        if analysis is None:
            activity.logger.error(f"Analysis {analysis_id} not found")
            return

        analysis.status = status
        analysis.completed_at = datetime.utcnow()

        if status == "completed":
            analysis.pathway_patterns = input.get("patterns", [])
            analysis.llm_interpretation = input.get("interpretation")
            analysis.llm_hypotheses = input.get("hypotheses", [])
            analysis.llm_model_used = input.get("llm_model_used")
            analysis.llm_cost_usd = input.get("llm_cost_usd")
        else:
            analysis.error_message = input.get("error_message")

        await db.commit()
        activity.logger.info(f"Analysis {analysis_id} updated to {status}")
