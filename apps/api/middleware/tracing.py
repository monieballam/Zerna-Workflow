"""Tracing and metrics middleware for Zerna API.

Responsibilities:
- Propagate trace context from incoming HTTP headers
- Inject user_id / org_id / request_id into the active span
- Record API latency via the metrics module
- Inject context fields into log records for structured logging
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from apps.api.metrics import increment_error, record_api_latency

logger = logging.getLogger(__name__)

_tracer = trace.get_tracer("zerna.middleware")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware that adds tracing, metrics, and structured log context to every request.

    For each request it:
    1. Generates a unique request_id (or reads X-Request-ID header)
    2. Starts a child span named after the HTTP method + path
    3. Sets span attributes: http.method, http.route, request_id
    4. Records API latency histogram after the response is sent
    5. Increments error counter for 5xx responses
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()
        status_code = 500

        # Attach request_id to the current span (created by FastAPIInstrumentor)
        span = trace.get_current_span()
        span.set_attribute("request_id", request_id)
        span.set_attribute("http.route", request.url.path)

        # Make request_id available to log records via a filter
        _inject_log_context(request_id=request_id)

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            increment_error("system_error", request.url.path)
            raise
        finally:
            elapsed = time.perf_counter() - start
            record_api_latency(elapsed, request.url.path, request.method, status_code)

            if status_code >= 500:
                increment_error("system_error", request.url.path)

        response.headers["X-Request-ID"] = request_id
        return response


def _inject_log_context(**fields: str) -> None:
    """Attach extra fields to all log records emitted in this thread/task.

    Uses a simple logging Filter installed on the root logger.
    """
    root = logging.getLogger()
    # Remove any previous context filter to avoid stacking
    root.filters = [f for f in root.filters if not isinstance(f, _ContextFilter)]
    root.addFilter(_ContextFilter(**fields))


class _ContextFilter(logging.Filter):
    """Injects arbitrary key-value pairs into every LogRecord."""

    def __init__(self, **fields: str) -> None:
        super().__init__()
        self._fields = fields

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self._fields.items():
            setattr(record, key, value)
        return True
