"""Property-based tests for agentic annotation.

# Feature: gap-analysis-and-verification, Property 31: Agentic suggestion metadata invariants
# Feature: gap-analysis-and-verification, Property 32: LLM fallback to rule-based annotation

**Validates: Requirements 16.2, 16.3, 16.4**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from methods.annotation.agentic import (
    AgenticSuggestion,
    AnnotationContext,
    LLMUnavailableError,
    UncertainLabel,
    suggest,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_cluster_id_st = st.text(
    min_size=1,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() != "")

_label_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip() != "")

_gene_st = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("Lu",)),
).filter(lambda s: s.strip() != "")

_expression_st = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


@st.composite
def _marker_evidence_st(draw):
    """Strategy for marker evidence dict."""
    n = draw(st.integers(min_value=0, max_value=5))
    return {draw(_gene_st): draw(_expression_st) for _ in range(n)}


@st.composite
def _uncertain_label_st(draw):
    """Strategy for a single UncertainLabel."""
    return UncertainLabel(
        cluster_id=draw(_cluster_id_st),
        label=draw(_label_st),
        marker_evidence=draw(_marker_evidence_st()),
    )


@st.composite
def _uncertain_labels_list_st(draw, min_size=1, max_size=10):
    """Strategy for a list of UncertainLabel with unique cluster_ids."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    seen_ids: set[str] = set()
    labels: list[UncertainLabel] = []
    for _ in range(n + 5):
        if len(labels) >= n:
            break
        ul = draw(_uncertain_label_st())
        if ul.cluster_id not in seen_ids:
            seen_ids.add(ul.cluster_id)
            labels.append(ul)
    assume(len(labels) >= min_size)
    return labels


@st.composite
def _context_st(draw):
    """Strategy for AnnotationContext."""
    tissue = draw(
        st.text(min_size=0, max_size=20, alphabet=st.characters(whitelist_categories=("L",)))
    )
    organism = draw(st.sampled_from(["human", "mouse", "rat"]))
    n_known = draw(st.integers(min_value=0, max_value=5))
    known = [draw(_label_st) for _ in range(n_known)]
    return AnnotationContext(
        tissue_type=tissue,
        organism=organism,
        known_cell_types=known,
    )


# ---------------------------------------------------------------------------
# Fake LLM clients for testing
# ---------------------------------------------------------------------------


class _WorkingLLMClient:
    """A fake LLM client that returns well-formatted responses."""

    def __init__(self, version: str = "test-llm-v1"):
        self._version = version

    def complete(self, prompt: str) -> str:
        # Parse cluster ids from the prompt and return a valid response
        lines = []
        for line in prompt.splitlines():
            stripped = line.strip()
            if stripped.startswith("Cluster "):
                parts = stripped.split(":")
                cid = parts[0].replace("Cluster ", "").strip()
                lines.append(f"{cid} | Refined_Label | 0.85 | LLM reasoning for {cid}")
        return "\n".join(lines)

    @property
    def model_version(self) -> str:
        return self._version


class _FailingLLMClient:
    """A fake LLM client that always raises an error."""

    def complete(self, prompt: str) -> str:
        raise LLMUnavailableError("LLM service is down")

    @property
    def model_version(self) -> str:
        return "failing-v0"


class _ExceptionLLMClient:
    """A fake LLM client that raises a generic exception."""

    def complete(self, prompt: str) -> str:
        raise ConnectionError("Connection refused")

    @property
    def model_version(self) -> str:
        return "exception-v0"


# ---------------------------------------------------------------------------
# Property 31: Agentic suggestion metadata invariants
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestAgenticSuggestionMetadataInvariants:
    """Property 31: For any agentic annotation suggestion, is_authoritative
    must be False, and the suggestion must include non-null model_version,
    prompt_context_hash, and reasoning fields.
    """

    @given(
        labels=_uncertain_labels_list_st(min_size=1, max_size=8),
        context=_context_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_llm_suggestions_metadata_invariants(
        self,
        labels: list[UncertainLabel],
        context: AnnotationContext,
    ) -> None:
        """Suggestions from the LLM path satisfy metadata invariants."""
        # Feature: gap-analysis-and-verification, Property 31: Agentic suggestion metadata invariants
        client = _WorkingLLMClient(version="test-llm-v1")
        suggestions = suggest(labels, context, llm_client=client)

        assert len(suggestions) == len(labels)
        for s in suggestions:
            assert s.is_authoritative is False
            assert s.model_version and len(s.model_version) > 0
            assert s.prompt_context_hash and len(s.prompt_context_hash) > 0
            assert s.reasoning and len(s.reasoning) > 0
            assert 0.0 <= s.confidence <= 1.0

    @given(
        labels=_uncertain_labels_list_st(min_size=1, max_size=8),
        context=_context_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_rule_based_suggestions_metadata_invariants(
        self,
        labels: list[UncertainLabel],
        context: AnnotationContext,
    ) -> None:
        """Suggestions from the rule-based path satisfy metadata invariants."""
        # Feature: gap-analysis-and-verification, Property 31: Agentic suggestion metadata invariants
        suggestions = suggest(labels, context, llm_client=None)

        assert len(suggestions) == len(labels)
        for s in suggestions:
            assert s.is_authoritative is False
            assert s.model_version and len(s.model_version) > 0
            assert s.prompt_context_hash and len(s.prompt_context_hash) > 0
            assert s.reasoning and len(s.reasoning) > 0
            assert 0.0 <= s.confidence <= 1.0


# ---------------------------------------------------------------------------
# Property 32: LLM fallback to rule-based annotation
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestLLMFallbackToRuleBased:
    """Property 32: For any annotation request where the LLM service is
    unavailable, the system must produce valid annotations using rule-based
    methods without raising an error.
    """

    @given(
        labels=_uncertain_labels_list_st(min_size=1, max_size=8),
        context=_context_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fallback_on_llm_unavailable_error(
        self,
        labels: list[UncertainLabel],
        context: AnnotationContext,
    ) -> None:
        """When LLMUnavailableError is raised, rule-based fallback produces valid results."""
        # Feature: gap-analysis-and-verification, Property 32: LLM fallback to rule-based annotation
        client = _FailingLLMClient()
        suggestions = suggest(labels, context, llm_client=client)

        # Must not raise and must produce one suggestion per label
        assert len(suggestions) == len(labels)
        cluster_ids = {s.cluster_id for s in suggestions}
        expected_ids = {ul.cluster_id for ul in labels}
        assert cluster_ids == expected_ids

        for s in suggestions:
            assert isinstance(s, AgenticSuggestion)
            assert s.is_authoritative is False
            assert s.model_version and len(s.model_version) > 0
            assert s.prompt_context_hash and len(s.prompt_context_hash) > 0
            assert s.reasoning and len(s.reasoning) > 0

    @given(
        labels=_uncertain_labels_list_st(min_size=1, max_size=8),
        context=_context_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fallback_on_generic_exception(
        self,
        labels: list[UncertainLabel],
        context: AnnotationContext,
    ) -> None:
        """When any generic exception is raised, rule-based fallback produces valid results."""
        # Feature: gap-analysis-and-verification, Property 32: LLM fallback to rule-based annotation
        client = _ExceptionLLMClient()
        suggestions = suggest(labels, context, llm_client=client)

        assert len(suggestions) == len(labels)
        for s in suggestions:
            assert isinstance(s, AgenticSuggestion)
            assert s.is_authoritative is False

    @given(
        labels=_uncertain_labels_list_st(min_size=1, max_size=8),
        context=_context_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fallback_when_no_client_provided(
        self,
        labels: list[UncertainLabel],
        context: AnnotationContext,
    ) -> None:
        """When llm_client is None, rule-based fallback produces valid results."""
        # Feature: gap-analysis-and-verification, Property 32: LLM fallback to rule-based annotation
        suggestions = suggest(labels, context, llm_client=None)

        assert len(suggestions) == len(labels)
        for s in suggestions:
            assert isinstance(s, AgenticSuggestion)
            assert s.is_authoritative is False
            assert s.model_version == "rule-based-v1"
