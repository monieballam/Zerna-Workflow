"""Interpreter service for natural language query parsing and session history.

Provides NL query interface for analysts to ask questions about their
analysis results in plain English, with session history persistence.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from zerna_contracts.base import ZernaBaseModel

# ---------------------------------------------------------------------------
# Data models
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
# Query parser
# ---------------------------------------------------------------------------


# Patterns for intent classification
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


def _build_suggestions_for_unknown(query: str) -> list[str]:
    """Return suggested reformulations when a query cannot be parsed."""
    return [
        "Try asking about gene expression, e.g. 'Show expression of CD3E'",
        "Try comparing conditions, e.g. 'Compare treated vs control'",
        "Try requesting a plot, e.g. 'Plot UMAP colored by cell type'",
    ]


# ---------------------------------------------------------------------------
# Interpreter service
# ---------------------------------------------------------------------------


class InterpreterService:
    """Processes NL queries and maintains per-session history.

    This is a stateful service: each instance holds an in-memory session
    store.  For production use the store would be backed by a database;
    the in-memory dict keeps the implementation minimal and testable.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[QueryHistoryEntry]] = {}

    # -- public API ---------------------------------------------------------

    def process_query(self, session_id: str, query_text: str) -> QueryResult:
        """Parse *query_text*, produce a result, and persist to session history.

        Parameters
        ----------
        session_id:
            Opaque session identifier (e.g. user-id or browser session).
        query_text:
            The natural-language query string.

        Returns
        -------
        QueryResult with intent classification and result text.
        """
        intent = classify_intent(query_text)
        now = datetime.now(UTC)
        query_id = uuid4()

        if intent == "unknown":
            suggestions = _build_suggestions_for_unknown(query_text)
            result = QueryResult(
                query_id=query_id,
                intent=intent,
                result_text="",
                suggestions=suggestions,
                error="Could not parse query intent. See suggestions for reformulations.",
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

        # Persist to session history
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
        """Return all history entries for *session_id*, oldest first."""
        return list(self._sessions.get(session_id, []))
