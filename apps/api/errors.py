"""Error classification, response formatting, and monitoring for Zerna API.

Provides:
- ErrorType enum for classifying errors (user_error, system_error, transient_error)
- ZernaError base exception with classification
- ErrorResponse Pydantic model for consistent API error responses
- Exception handlers for FastAPI
- Error monitoring via structured logging and metrics

Requirements: 12.4, 16.1, 16.2, 16.3, 16.5, 10.4
"""

from __future__ import annotations

import builtins
import errno
import logging
import traceback
from enum import Enum
from typing import Any

import redis.exceptions
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from apps.api.metrics import increment_error

logger = logging.getLogger(__name__)

# Shown when Postgres/Redis are not reachable (typical local dev: Docker not running).
DEPENDENCY_UNAVAILABLE_MESSAGE = (
    "Cannot reach PostgreSQL or Redis. For local development: start Docker Desktop, then from the "
    "repository root run `./scripts/setup-dev-env.sh` or `docker compose up -d`, run "
    "`uv run --directory apps/api alembic upgrade head`, and restart the API."
)


def _operational_error_is_unreachable(exc: OperationalError) -> bool:
    """True when the failure is almost certainly 'server not listening' (e.g. Docker down)."""
    cause = exc.__cause__
    if isinstance(cause, ConnectionRefusedError):
        return True
    if isinstance(cause, OSError) and getattr(cause, "errno", None) in (
        errno.ECONNREFUSED,
        errno.ECONNABORTED,
    ):
        return True
    text = str(exc).lower()
    return (
        "connection refused" in text
        or "could not connect to server" in text
        or "connection is closed" in text
    )


def _dependency_unreachable_in_chain(
    exc: BaseException | None, seen: set[int] | None = None
) -> bool:
    """Walk exception groups, causes, and context for Postgres/Redis down errors."""
    if exc is None:
        return False
    if seen is None:
        seen = set()
    eid = id(exc)
    if eid in seen:
        return False
    seen.add(eid)

    if isinstance(exc, redis.exceptions.ConnectionError):
        return True
    if isinstance(exc, OperationalError) and _operational_error_is_unreachable(exc):
        return True
    if isinstance(exc, ConnectionRefusedError):
        return True
    if _base_exception_group_type is not None and isinstance(exc, _base_exception_group_type):
        return any(_dependency_unreachable_in_chain(e, seen) for e in exc.exceptions)
    if exc.__cause__ is not None and _dependency_unreachable_in_chain(exc.__cause__, seen):
        return True
    if (
        exc.__context__ is not None
        and exc.__context__ is not exc.__cause__
        and _dependency_unreachable_in_chain(exc.__context__, seen)
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Error type classification (Requirement 16.3)
# ---------------------------------------------------------------------------


class ErrorType(str, Enum):
    """Classification of errors for retry and user feedback decisions.

    - user_error: Invalid input, missing permissions, quota exceeded.
      Should NOT be retried; user must take corrective action.
    - system_error: Unexpected internal failures (DB down, unhandled exception).
      Should be alerted; may be retried by operators.
    - transient_error: Temporary failures (network timeout, service unavailable).
      Should be retried with exponential backoff (Requirement 16.4, 16.5).
    """

    USER_ERROR = "user_error"
    SYSTEM_ERROR = "system_error"
    TRANSIENT_ERROR = "transient_error"


# ---------------------------------------------------------------------------
# Retry configuration per error type (Requirement 16.5)
# ---------------------------------------------------------------------------

RETRY_CONFIG: dict[ErrorType, dict[str, Any]] = {
    ErrorType.USER_ERROR: {
        "should_retry": False,
        "max_attempts": 1,
        "backoff_seconds": 0,
    },
    ErrorType.SYSTEM_ERROR: {
        "should_retry": False,  # Requires operator intervention
        "max_attempts": 1,
        "backoff_seconds": 0,
    },
    ErrorType.TRANSIENT_ERROR: {
        "should_retry": True,
        "max_attempts": 3,
        "backoff_seconds": 2,  # Base for exponential backoff: 2, 4, 8 seconds
    },
}


def get_retry_config(error_type: ErrorType) -> dict[str, Any]:
    """Return retry configuration for the given error type."""
    return RETRY_CONFIG[error_type]


# ---------------------------------------------------------------------------
# Zerna exception hierarchy
# ---------------------------------------------------------------------------


class ZernaError(Exception):
    """Base exception for all Zerna application errors.

    All domain exceptions should subclass this and set the appropriate
    error_type, http_status_code, and error_code.
    """

    error_type: ErrorType = ErrorType.SYSTEM_ERROR
    http_status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if error_code:
            self.error_code = error_code


# --- User errors (HTTP 4xx, no retry) ---


class ValidationError(ZernaError):
    """Input validation failed."""

    error_type = ErrorType.USER_ERROR
    http_status_code = 422
    error_code = "VALIDATION_ERROR"


class NotFoundError(ZernaError):
    """Requested resource does not exist."""

    error_type = ErrorType.USER_ERROR
    http_status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class PermissionDeniedError(ZernaError):
    """User lacks required permission."""

    error_type = ErrorType.USER_ERROR
    http_status_code = status.HTTP_403_FORBIDDEN
    error_code = "PERMISSION_DENIED"


class QuotaExceededError(ZernaError):
    """Organization quota exceeded."""

    error_type = ErrorType.USER_ERROR
    http_status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "QUOTA_EXCEEDED"


class ConflictError(ZernaError):
    """Resource conflict (e.g., duplicate version)."""

    error_type = ErrorType.USER_ERROR
    http_status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


class FileFormatError(ZernaError):
    """Uploaded file has invalid format."""

    error_type = ErrorType.USER_ERROR
    http_status_code = 422
    error_code = "INVALID_FILE_FORMAT"


# --- Transient errors (retry with backoff) ---


class ServiceUnavailableError(ZernaError):
    """Downstream service temporarily unavailable."""

    error_type = ErrorType.TRANSIENT_ERROR
    http_status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"


class TimeoutError(ZernaError):
    """Operation timed out."""

    error_type = ErrorType.TRANSIENT_ERROR
    http_status_code = status.HTTP_504_GATEWAY_TIMEOUT
    error_code = "TIMEOUT"


class StorageError(ZernaError):
    """Transient S3/storage error."""

    error_type = ErrorType.TRANSIENT_ERROR
    http_status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "STORAGE_ERROR"


# --- System errors (HTTP 5xx, alert required) ---


class DatabaseError(ZernaError):
    """Unexpected database error."""

    error_type = ErrorType.SYSTEM_ERROR
    http_status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "DATABASE_ERROR"


class WorkflowError(ZernaError):
    """Temporal workflow execution error."""

    error_type = ErrorType.SYSTEM_ERROR
    http_status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "WORKFLOW_ERROR"


# ---------------------------------------------------------------------------
# Error response model (Requirement 16.1, 16.2, 12.4)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standardized error response body.

    Included in all 4xx/5xx responses for consistent client handling.
    """

    error_type: ErrorType
    error_code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str | None = None  # For tracing (Requirement 16.2)


# ---------------------------------------------------------------------------
# Exception → ErrorResponse classification helpers
# ---------------------------------------------------------------------------


def classify_exception(exc: Exception) -> tuple[ErrorType, int, str]:
    """Classify any exception into (error_type, http_status_code, error_code).

    Args:
        exc: The exception to classify

    Returns:
        Tuple of (ErrorType, HTTP status code, error code string)
    """
    if isinstance(exc, ZernaError):
        return exc.error_type, exc.http_status_code, exc.error_code

    # Map common stdlib / third-party exceptions
    exc_type = type(exc).__name__

    # Transient errors
    if exc_type in {"ConnectionError", "ConnectionRefusedError", "ConnectionResetError"}:
        return ErrorType.TRANSIENT_ERROR, 503, "SERVICE_UNAVAILABLE"
    if exc_type in {"TimeoutError", "asyncio.TimeoutError"}:
        return ErrorType.TRANSIENT_ERROR, 504, "TIMEOUT"

    # User errors
    if exc_type in {"ValueError", "TypeError"}:
        return ErrorType.USER_ERROR, 422, "VALIDATION_ERROR"
    if exc_type == "PermissionError":
        return ErrorType.USER_ERROR, 403, "PERMISSION_DENIED"
    if exc_type == "FileNotFoundError":
        return ErrorType.USER_ERROR, 404, "NOT_FOUND"

    # Default: system error
    return ErrorType.SYSTEM_ERROR, 500, "INTERNAL_ERROR"


def _get_request_id(request: Request) -> str | None:
    """Extract request_id from response headers (set by ObservabilityMiddleware)."""
    return request.headers.get("X-Request-ID")


# Python 3.11+ (Starlette task groups can surface BaseExceptionGroup to the ASGI layer).
_base_exception_group_type = getattr(builtins, "BaseExceptionGroup", None)


def _dependency_unavailable_response(request: Request) -> JSONResponse:
    request_id = _get_request_id(request)
    logger.warning(
        "Backend dependency unreachable (database or cache)",
        extra={
            "error_code": "SERVICE_UNAVAILABLE",
            "error_type": ErrorType.TRANSIENT_ERROR.value,
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
    )
    increment_error(ErrorType.TRANSIENT_ERROR.value, request.url.path)
    body = ErrorResponse(
        error_type=ErrorType.TRANSIENT_ERROR,
        error_code="SERVICE_UNAVAILABLE",
        message=DEPENDENCY_UNAVAILABLE_MESSAGE,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------


async def zerna_error_handler(request: Request, exc: ZernaError) -> JSONResponse:
    """Handle ZernaError subclasses with structured error responses."""
    request_id = _get_request_id(request)

    # Log system errors with full context (Requirement 10.4)
    if exc.error_type == ErrorType.SYSTEM_ERROR:
        logger.error(
            "System error: %s",
            exc.message,
            extra={
                "error_code": exc.error_code,
                "error_type": exc.error_type.value,
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "traceback": traceback.format_exc(),
            },
        )
        increment_error(exc.error_type.value, request.url.path)
    elif exc.error_type == ErrorType.TRANSIENT_ERROR:
        logger.warning(
            "Transient error: %s",
            exc.message,
            extra={
                "error_code": exc.error_code,
                "error_type": exc.error_type.value,
                "request_id": request_id,
                "path": request.url.path,
            },
        )
        increment_error(exc.error_type.value, request.url.path)
    else:
        logger.info(
            "User error: %s",
            exc.message,
            extra={
                "error_code": exc.error_code,
                "error_type": exc.error_type.value,
                "request_id": request_id,
                "path": request.url.path,
            },
        )

    body = ErrorResponse(
        error_type=exc.error_type,
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.http_status_code,
        content=body.model_dump(mode="json"),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic RequestValidationError with HTTP 422 and field details.

    Requirement 12.4: Return 422 for validation errors with field details.
    """
    request_id = _get_request_id(request)

    # Format field-level errors for the client
    field_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        field_errors.append(
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    logger.info(
        "Request validation error",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "field_errors": field_errors,
        },
    )

    body = ErrorResponse(
        error_type=ErrorType.USER_ERROR,
        error_code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"field_errors": field_errors},
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body.model_dump(mode="json"),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Logs full context and returns a generic 500 response.
    Requirement 10.4: Log all errors with structured context.
    """
    if _dependency_unreachable_in_chain(exc):
        return _dependency_unavailable_response(request)

    request_id = _get_request_id(request)

    logger.error(
        "Unhandled exception: %s",
        str(exc),
        extra={
            "error_type": ErrorType.SYSTEM_ERROR.value,
            "error_code": "INTERNAL_ERROR",
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "traceback": traceback.format_exc(),
        },
    )
    increment_error(ErrorType.SYSTEM_ERROR.value, request.url.path)

    body = ErrorResponse(
        error_type=ErrorType.SYSTEM_ERROR,
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred. Please try again later.",
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(mode="json"),
    )


class CatchDependencyExceptionGroupsMiddleware(BaseHTTPMiddleware):
    """Starlette cannot register handlers for BaseExceptionGroup (not an Exception subclass).

    TaskGroup/collapse_excgroups can surface connection errors as ExceptionGroup; map those to 503 here.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except BaseException as exc:
            if _base_exception_group_type is not None and isinstance(
                exc, _base_exception_group_type
            ):
                if _dependency_unreachable_in_chain(exc):
                    return _dependency_unavailable_response(request)
            raise


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_error_handlers(app: FastAPI) -> None:
    """Register all Zerna error handlers on the FastAPI app.

    Call this during app initialization after creating the FastAPI instance.
    """
    app.add_exception_handler(ZernaError, zerna_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
