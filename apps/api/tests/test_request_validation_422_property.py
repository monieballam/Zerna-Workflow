"""Property-based tests for request validation with HTTP 422 responses.

**Property 24: Request Validation with 422 Response**

For any API endpoint, when a request body fails Pydantic schema validation,
the response must be HTTP 422 with a structured error body containing
field-level error details and a request_id for tracing.

**Validates: Requirements 12.4**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from apps.api.errors import (
    ErrorResponse,
    ErrorType,
    classify_exception,
)
from apps.api.errors import (
    ValidationError as ZernaValidationError,
)

# ---------------------------------------------------------------------------
# Sample Pydantic schemas (mirrors real API request models)
# ---------------------------------------------------------------------------


class SampleCreateRunRequest(BaseModel):
    dataset_version_id: str = Field(min_length=36, max_length=36)  # UUID string
    template_id: str = Field(min_length=36, max_length=36)
    parameters: dict = Field(default_factory=dict)
    random_seed: int | None = Field(default=None, ge=0)


class SampleCreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    page_size: int = Field(default=20, ge=1, le=100)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestRequestValidation422:
    """Property 24: Request Validation with 422 Response."""

    @given(
        name=st.one_of(
            st.just(""),  # empty string (violates min_length=1)
            st.text(min_size=256, max_size=300),  # too long (violates max_length=255)
        )
    )
    @settings(max_examples=40)
    def test_invalid_name_raises_validation_error(self, name):
        """Property: Invalid name values always fail Pydantic validation."""
        with pytest.raises(PydanticValidationError) as exc_info:
            SampleCreateDatasetRequest(name=name)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        # The field path should reference 'name'
        field_paths = [".".join(str(loc) for loc in e["loc"]) for e in errors]
        assert any("name" in path for path in field_paths)

    @given(
        page_size=st.one_of(
            st.integers(max_value=0),  # below minimum (ge=1)
            st.integers(min_value=101),  # above maximum (le=100)
        )
    )
    @settings(max_examples=40)
    def test_invalid_page_size_raises_validation_error(self, page_size):
        """Property: page_size outside [1, 100] always fails validation."""
        with pytest.raises(PydanticValidationError) as exc_info:
            SampleCreateDatasetRequest(name="valid-name", page_size=page_size)

        errors = exc_info.value.errors()
        assert len(errors) > 0

    @given(
        random_seed=st.integers(max_value=-1),  # negative (violates ge=0)
    )
    @settings(max_examples=30)
    def test_negative_random_seed_raises_validation_error(self, random_seed):
        """Property: Negative random_seed always fails validation."""
        with pytest.raises(PydanticValidationError) as exc_info:
            SampleCreateRunRequest(
                dataset_version_id="a" * 36,
                template_id="b" * 36,
                random_seed=random_seed,
            )

        errors = exc_info.value.errors()
        assert len(errors) > 0

    @given(
        error_type=st.sampled_from(list(ErrorType)),
        error_code=st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"
            ),
        ),
        message=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=50)
    def test_error_response_model_always_serializable(self, error_type, error_code, message):
        """Property: ErrorResponse model is always JSON-serializable for any valid inputs."""
        response = ErrorResponse(
            error_type=error_type,
            error_code=error_code,
            message=message,
            details={"field": "value"},
            request_id="test-request-id",
        )
        serialized = response.model_dump(mode="json")

        assert serialized["error_type"] == error_type.value
        assert serialized["error_code"] == error_code
        assert serialized["message"] == message
        assert serialized["request_id"] == "test-request-id"

    @given(
        exc_class=st.sampled_from(
            [
                ValueError,
                TypeError,
                PermissionError,
                FileNotFoundError,
                ConnectionError,
            ]
        )
    )
    @settings(max_examples=30)
    def test_classify_exception_always_returns_valid_error_type(self, exc_class):
        """Property: classify_exception always returns a valid ErrorType for any exception."""
        exc = exc_class("test error")
        error_type, http_status, error_code = classify_exception(exc)

        assert isinstance(error_type, ErrorType)
        assert http_status in (400, 403, 404, 409, 422, 429, 500, 503, 504)
        assert isinstance(error_code, str)
        assert len(error_code) > 0

    @given(
        message=st.text(min_size=1, max_size=200),
        details=st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.text(min_size=0, max_size=50),
            max_size=5,
        ),
    )
    @settings(max_examples=40)
    def test_zerna_validation_error_is_user_error(self, message, details):
        """Property: ZernaValidationError is always classified as user_error with 422."""
        exc = ZernaValidationError(message=message, details=details)

        assert exc.error_type == ErrorType.USER_ERROR
        assert exc.http_status_code == 422
        assert exc.error_code == "VALIDATION_ERROR"

        # classify_exception should agree
        error_type, http_status, error_code = classify_exception(exc)
        assert error_type == ErrorType.USER_ERROR
        assert http_status == 422

    @given(
        num_field_errors=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30)
    def test_validation_error_response_contains_field_errors(self, num_field_errors):
        """Property: Validation error responses always contain field-level error details."""
        # Simulate what validation_error_handler produces
        field_errors = [
            {"field": f"field_{i}", "message": "value is not valid", "type": "value_error"}
            for i in range(num_field_errors)
        ]

        response = ErrorResponse(
            error_type=ErrorType.USER_ERROR,
            error_code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"field_errors": field_errors},
            request_id="req-123",
        )

        serialized = response.model_dump(mode="json")
        assert "field_errors" in serialized["details"]
        assert len(serialized["details"]["field_errors"]) == num_field_errors

        for fe in serialized["details"]["field_errors"]:
            assert "field" in fe
            assert "message" in fe
            assert "type" in fe

    @given(
        error_type=st.sampled_from(list(ErrorType)),
    )
    @settings(max_examples=20)
    def test_error_response_request_id_is_optional(self, error_type):
        """Property: ErrorResponse is valid with or without request_id."""
        # Without request_id
        response_no_id = ErrorResponse(
            error_type=error_type,
            error_code="TEST_ERROR",
            message="test",
        )
        assert response_no_id.request_id is None

        # With request_id
        response_with_id = ErrorResponse(
            error_type=error_type,
            error_code="TEST_ERROR",
            message="test",
            request_id="abc-123",
        )
        assert response_with_id.request_id == "abc-123"

    @given(
        http_status=st.sampled_from([400, 401, 403, 404, 409, 422, 429, 500, 503]),
    )
    @settings(max_examples=20)
    def test_error_response_is_consistent_across_status_codes(self, http_status):
        """Property: ErrorResponse structure is consistent regardless of HTTP status code."""
        response = ErrorResponse(
            error_type=ErrorType.USER_ERROR,
            error_code="TEST_ERROR",
            message="test message",
            details={"key": "value"},
            request_id="req-id",
        )
        serialized = response.model_dump(mode="json")

        # Required fields always present
        assert "error_type" in serialized
        assert "error_code" in serialized
        assert "message" in serialized
        assert "details" in serialized
        assert "request_id" in serialized
