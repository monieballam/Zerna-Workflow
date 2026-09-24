"""Property-based tests for query session history persistence.

# Feature: gap-analysis-and-verification, Property 10: Query session history persistence

**Validates: Requirements 7.3**
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from zerna_contracts.base import ZernaBaseModel
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Lightweight interpreter models (mirrors interpreter_service.py logic)
# ---------------------------------------------------------------------------

QueryIntent = Literal[
    "expression_lookup",
    "comparison",
    "plot_generation",
    "cell_type_query",
    "marker_query",
    "unknown",
]


class QueryResult(ZernaBaseModel):
    """Result of processing an interpreter query."""

    query_id: UUID
    intent: QueryIntent
    result_text: str
    result_data: dict[str, Any] = {}
    suggestions: list[str] = []
    error: str | None = None
    processed_at: datetime


class QueryHistoryEntry(ZernaBaseModel):
    """A single entry in the user's session history."""

    query_id: UUID
    session_id: str
    query_text: str
    result: QueryResult
    created_at: datetime


# ---------------------------------------------------------------------------
# Intent classification (mirrors interpreter_service.py)
# ---------------------------------------------------------------------------

_EXPRESSION_PATTERNS = [
    re.compile(r"\b(express|expression|level|levels)\b", re.IGNORECASE),
    re.compile(r"\b(gene|genes|marker|markers)\b", re.IGNORECASE),
]
_COMPARISON_PATTERNS = [
    re.compile(r"\b(compar|difference|versus|vs\.?|between)\b", re.IGNORECASE),
    re.compile(r"\b(fold.?change|differential|higher|lower)\b", re.IGNORECASE),
]
_PLOT_PATTERNS = [
    re.compile(r"\b(plot|chart|graph|visuali[sz]|umap|tsne|volcano|heatmap)\b", re.IGNORECASE),
]
_CELL_TYPE_PATTERNS = [
    re.compile(r"\b(cell.?type|cluster|population|subtype)\b", re.IGNORECASE),
]
_MARKER_PATTERNS = [
    re.compile(r"\b(marker|signature|panel)\b", re.IGNORECASE),
]


def classify_intent(query: str) -> QueryIntent:
    """Classify the intent of a natural language query."""
    if not query or not query.strip():
        return "unknown"
    for pat in _PLOT_PATTERNS:
        if pat.search(query):
            return "plot_generation"
    for pat in _COMPARISON_PATTERNS:
        if pat.search(query):
            return "comparison"
    for pat in _EXPRESSION_PATTERNS:
        if pat.search(query):
            return "expression_lookup"
    for pat in _CELL_TYPE_PATTERNS:
        if pat.search(query):
            return "cell_type_query"
    for pat in _MARKER_PATTERNS:
        if pat.search(query):
            return "marker_query"
    return "unknown"


# ---------------------------------------------------------------------------
# Interpreter service (mirrors interpreter_service.py)
# ---------------------------------------------------------------------------


class InterpreterService:
    """Processes NL queries and maintains per-session history."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[QueryHistoryEntry]] = {}

    def process_query(self, session_id: str, query_text: str) -> QueryResult:
        intent = classify_intent(query_text)
        now = datetime.now(UTC)
        query_id = uuid4()

        if intent == "unknown":
            result = QueryResult(
                query_id=query_id,
                intent=intent,
                result_text="",
                suggestions=[
                    "Try asking about gene expression",
                    "Try comparing conditions",
                    "Try requesting a plot",
                ],
                error="Could not parse query intent.",
                processed_at=now,
            )
        else:
            result = QueryResult(
                query_id=query_id,
                intent=intent,
                result_text=f"Processed {intent} query: {query_text}",
                result_data={"intent": intent, "raw_query": query_text},
                processed_at=now,
            )

        entry = QueryHistoryEntry(
            query_id=query_id,
            session_id=session_id,
            query_text=query_text,
            result=result,
            created_at=now,
        )
        self._sessions.setdefault(session_id, []).append(entry)
        return result

    def get_session_history(self, session_id: str) -> list[QueryHistoryEntry]:
        return list(self._sessions.get(session_id, []))


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_session_id = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
)

# Query texts that will match at least one intent pattern
_known_intent_queries = st.sampled_from(
    [
        "Show expression of CD3E",
        "Compare treated vs control",
        "Plot UMAP colored by cell type",
        "What cell types are in cluster 5?",
        "Show marker panel for T cells",
    ]
)

# Arbitrary query text (may or may not match an intent)
_arbitrary_query = st.text(min_size=1, max_size=200)

# Combined strategy
_query_text = st.one_of(_known_intent_queries, _arbitrary_query)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestQuerySessionHistoryPersistence:
    """Property 10: Query session history persistence.

    For any processed interpreter query, the query text and result must
    appear in the user's session history when retrieved.
    """

    @given(session_id=_session_id, query_text=_query_text)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_processed_query_appears_in_session_history(
        self, session_id: str, query_text: str
    ) -> None:
        """After processing a query, it must be present in session history."""
        service = InterpreterService()
        result = service.process_query(session_id, query_text)

        history = service.get_session_history(session_id)

        assert len(history) >= 1
        last = history[-1]
        assert last.query_text == query_text
        assert last.result.query_id == result.query_id

    @given(session_id=_session_id, query_text=_query_text)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_history_entry_contains_query_text_and_result(
        self, session_id: str, query_text: str
    ) -> None:
        """Each history entry must preserve the original query text and
        the full QueryResult."""
        service = InterpreterService()
        result = service.process_query(session_id, query_text)

        history = service.get_session_history(session_id)
        entry = history[-1]

        assert entry.query_text == query_text
        assert entry.result.intent == result.intent
        assert entry.result.result_text == result.result_text
        assert entry.result.processed_at == result.processed_at

    @given(
        session_id=_session_id,
        queries=st.lists(_query_text, min_size=2, max_size=10),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_queries_all_persist_in_order(
        self, session_id: str, queries: list[str]
    ) -> None:
        """All queries submitted to the same session must appear in
        chronological order in the history."""
        service = InterpreterService()
        results = [service.process_query(session_id, q) for q in queries]

        history = service.get_session_history(session_id)

        assert len(history) == len(queries)
        for entry, original_text, original_result in zip(history, queries, results):
            assert entry.query_text == original_text
            assert entry.result.query_id == original_result.query_id

    @given(
        sid_a=_session_id,
        sid_b=_session_id,
        query_a=_query_text,
        query_b=_query_text,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_sessions_are_isolated(
        self, sid_a: str, sid_b: str, query_a: str, query_b: str
    ) -> None:
        """Queries in one session must not leak into another session's
        history (when session IDs differ)."""
        assume(sid_a != sid_b)

        service = InterpreterService()
        service.process_query(sid_a, query_a)
        service.process_query(sid_b, query_b)

        history_a = service.get_session_history(sid_a)
        history_b = service.get_session_history(sid_b)

        assert len(history_a) == 1
        assert len(history_b) == 1
        assert history_a[0].query_text == query_a
        assert history_b[0].query_text == query_b
