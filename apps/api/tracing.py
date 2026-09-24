"""Tracing helpers for Zerna API.

Provides:
- trace_span: decorator for adding named spans to service methods
- set_span_user_context: helper to attach user/org/run attributes to the current span
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_tracer = trace.get_tracer("zerna.api")


def trace_span(operation_name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps a function (sync or async) in an OTel span.

    The span name defaults to ``<module>.<function_name>`` when
    ``operation_name`` is not provided.

    Example::

        @trace_span("run_service.create_run")
        async def create_run(self, org_id, ...):
            ...

    Args:
        operation_name: Optional explicit span name.

    Returns:
        Decorated function.
    """

    def decorator(fn: F) -> F:
        name = operation_name or f"{fn.__module__}.{fn.__qualname__}"

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _tracer.start_as_current_span(name) as span:
                    try:
                        return await fn(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, str(exc))
                        raise

            return async_wrapper  # type: ignore[return-value]
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _tracer.start_as_current_span(name) as span:
                    try:
                        return fn(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, str(exc))
                        raise

            return sync_wrapper  # type: ignore[return-value]

    return decorator


def set_span_user_context(
    user_id: UUID | str | None = None,
    org_id: UUID | str | None = None,
    run_id: UUID | str | None = None,
) -> None:
    """Attach user/org/run identifiers to the currently active span.

    Call this inside route handlers or service methods after the user
    context is known.

    Args:
        user_id: Authenticated user identifier
        org_id: Organization identifier
        run_id: Run identifier (when applicable)
    """
    span = trace.get_current_span()
    if user_id is not None:
        span.set_attribute("user_id", str(user_id))
    if org_id is not None:
        span.set_attribute("org_id", str(org_id))
    if run_id is not None:
        span.set_attribute("run_id", str(run_id))
