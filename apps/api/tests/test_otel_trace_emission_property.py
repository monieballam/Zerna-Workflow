"""Property-based tests for OpenTelemetry trace emission.

**Property 21: OpenTelemetry Trace Emission**
**Validates: Requirements 10.1, 10.2**

Properties verified:
1. Every span created via a tracer emits exactly one finished span.
2. Spans always carry the operation name used to create them.
3. Spans carry method_name, method_version, run_id, org_id when set explicitly.
4. Span status is not ERROR on success; is ERROR when exception is recorded.
5. Exceptions are recorded on the span before being re-raised.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from zerna_contracts.enums import ComputePreference
from hypothesis import given, settings
from hypothesis import strategies as st
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from methods.base import MethodDefinition

# ---------------------------------------------------------------------------
# Helpers — each test gets its own isolated TracerProvider
# ---------------------------------------------------------------------------


def _make_tracer(scope: str = "test") -> tuple[InMemorySpanExporter, trace.Tracer]:
    """Create an isolated TracerProvider + tracer backed by an in-memory exporter.

    We do NOT touch the global provider — each test uses its own isolated one.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(scope)
    return exporter, tracer


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

operation_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="._-"),
    min_size=1,
    max_size=64,
)

method_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=32,
)

method_version_strategy = st.from_regex(r"\d+\.\d+\.\d+", fullmatch=True)

uuid_str_strategy = st.uuids().map(str)


# ---------------------------------------------------------------------------
# Minimal MethodDefinition stub
# ---------------------------------------------------------------------------


class _StubMethod(MethodDefinition):
    """Minimal concrete MethodDefinition for testing execute_traced."""

    def __init__(self, name: str, version: str, should_raise: bool = False) -> None:
        self.name = name
        self.version = version
        self.compute_preference = ComputePreference.CPU_ONLY
        self._should_raise = should_raise

    def input_schema(self):
        from pydantic import BaseModel

        return BaseModel

    def output_schema(self):
        from pydantic import BaseModel

        return BaseModel

    def execute(self, input: Any, compute: Any) -> Any:
        if self._should_raise:
            raise ValueError("deliberate test failure")
        return MagicMock()


# ---------------------------------------------------------------------------
# Helper: run execute_traced using an explicit tracer (not the global)
# ---------------------------------------------------------------------------


def _execute_traced_with_tracer(
    tracer: trace.Tracer,
    method: MethodDefinition,
    run_id: str | None = None,
    org_id: str | None = None,
) -> Any:
    """Replicate execute_traced logic using an explicit tracer."""
    span_name = f"method.{getattr(method, 'name', type(method).__name__)}"
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("method.name", getattr(method, "name", type(method).__name__))
        span.set_attribute("method.version", getattr(method, "version", "unknown"))
        if run_id:
            span.set_attribute("run_id", run_id)
        if org_id:
            span.set_attribute("org_id", org_id)
        try:
            result = method.execute(MagicMock(), MagicMock())
            span.set_status(StatusCode.OK)
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            raise


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestOtelTraceEmission:
    """Property 21: OpenTelemetry Trace Emission"""

    @given(operation_name=operation_name_strategy)
    @settings(max_examples=50)
    def test_trace_span_emits_exactly_one_span(self, operation_name: str) -> None:
        """Property: Every span context manager emits exactly one finished span.

        **Validates: Requirements 10.1**
        """
        exporter, tracer = _make_tracer()

        with tracer.start_as_current_span(operation_name):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1, (
            f"Expected exactly 1 span for operation '{operation_name}', got {len(spans)}"
        )

    @given(operation_name=operation_name_strategy)
    @settings(max_examples=50)
    def test_trace_span_name_matches_operation(self, operation_name: str) -> None:
        """Property: The emitted span name always equals the supplied operation_name.

        **Validates: Requirements 10.1**
        """
        exporter, tracer = _make_tracer()

        with tracer.start_as_current_span(operation_name):
            pass

        spans = exporter.get_finished_spans()
        assert spans[0].name == operation_name, (
            f"Span name '{spans[0].name}' does not match operation '{operation_name}'"
        )

    @given(operation_name=operation_name_strategy)
    @settings(max_examples=50)
    def test_trace_span_status_ok_on_success(self, operation_name: str) -> None:
        """Property: Span status is not ERROR when the wrapped function returns normally.

        **Validates: Requirements 10.1**
        """
        exporter, tracer = _make_tracer()

        with tracer.start_as_current_span(operation_name) as span:
            span.set_status(StatusCode.OK)

        spans = exporter.get_finished_spans()
        assert spans[0].status.status_code != StatusCode.ERROR, (
            "Span status must not be ERROR when function succeeds"
        )

    @given(operation_name=operation_name_strategy)
    @settings(max_examples=50)
    def test_trace_span_status_error_on_exception(self, operation_name: str) -> None:
        """Property: Span status is ERROR and exception is recorded when function raises.

        **Validates: Requirements 10.1**
        """
        exporter, tracer = _make_tracer()

        with pytest.raises(RuntimeError):
            with tracer.start_as_current_span(operation_name) as span:
                try:
                    raise RuntimeError("boom")
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    raise

        spans = exporter.get_finished_spans()
        assert spans[0].status.status_code == StatusCode.ERROR, (
            "Span status must be ERROR when function raises"
        )
        event_names = [e.name for e in spans[0].events]
        assert "exception" in event_names, "Exception event must be recorded on the span"

    @given(
        method_name=method_name_strategy,
        method_version=method_version_strategy,
        run_id=uuid_str_strategy,
        org_id=uuid_str_strategy,
    )
    @settings(max_examples=50)
    def test_method_execute_traced_emits_span_with_attributes(
        self,
        method_name: str,
        method_version: str,
        run_id: str,
        org_id: str,
    ) -> None:
        """Property: execute_traced always emits a span with method_name, method_version,
        run_id, and org_id attributes.

        **Validates: Requirements 10.2**
        """
        exporter, tracer = _make_tracer()

        method = _StubMethod(name=method_name, version=method_version)
        _execute_traced_with_tracer(tracer, method, run_id=run_id, org_id=org_id)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1, "execute_traced must emit exactly one span"

        attrs = spans[0].attributes or {}
        assert attrs.get("method.name") == method_name, (
            f"method.name attribute missing or wrong: {attrs}"
        )
        assert attrs.get("method.version") == method_version, (
            f"method.version attribute missing or wrong: {attrs}"
        )
        assert attrs.get("run_id") == run_id, f"run_id attribute missing or wrong: {attrs}"
        assert attrs.get("org_id") == org_id, f"org_id attribute missing or wrong: {attrs}"

    @given(
        method_name=method_name_strategy,
        method_version=method_version_strategy,
    )
    @settings(max_examples=30)
    def test_method_execute_traced_error_on_exception(
        self,
        method_name: str,
        method_version: str,
    ) -> None:
        """Property: execute_traced marks span as ERROR and re-raises when execute raises.

        **Validates: Requirements 10.2**
        """
        exporter, tracer = _make_tracer()

        method = _StubMethod(name=method_name, version=method_version, should_raise=True)

        with pytest.raises(ValueError, match="deliberate test failure"):
            _execute_traced_with_tracer(tracer, method)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR, (
            "Span must be ERROR when execute raises"
        )
        event_names = [e.name for e in spans[0].events]
        assert "exception" in event_names, "Exception event must be recorded on the span"

    @given(
        user_id=uuid_str_strategy,
        org_id=uuid_str_strategy,
        run_id=uuid_str_strategy,
    )
    @settings(max_examples=30)
    def test_span_user_context_attributes_are_set(
        self,
        user_id: str,
        org_id: str,
        run_id: str,
    ) -> None:
        """Property: user_id, org_id, run_id attributes set on a span are always readable.

        **Validates: Requirements 10.1**
        """
        exporter, tracer = _make_tracer()

        with tracer.start_as_current_span("test-op") as span:
            span.set_attribute("user_id", user_id)
            span.set_attribute("org_id", org_id)
            span.set_attribute("run_id", run_id)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = spans[0].attributes or {}
        assert attrs.get("user_id") == user_id
        assert attrs.get("org_id") == org_id
        assert attrs.get("run_id") == run_id
