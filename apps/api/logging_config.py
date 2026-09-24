"""Structured JSON logging configuration for Zerna API."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects.

    Each record includes:
    - timestamp (ISO-8601 UTC)
    - level
    - logger name
    - message
    - context fields injected via LogContext (user_id, org_id, run_id, request_id)
    - exc_info with full stack trace when an exception is attached
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject context fields set by LogContext
        for field in ("user_id", "org_id", "run_id", "request_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        # Include full stack trace for exceptions
        if record.exc_info:
            payload["exc_info"] = traceback.format_exception(*record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Apply logging configuration to the root logger.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        fmt: "json" for structured output, anything else for plain text
    """
    handler = logging.StreamHandler()

    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Replace any existing handlers to avoid duplicate output
    root.handlers.clear()
    root.addHandler(handler)
