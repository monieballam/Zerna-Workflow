"""Tests for base Pydantic models."""

from datetime import datetime
from uuid import uuid4

import pytest
from zerna_contracts import (
    ZernaBaseModel,
    ErrorResponse,
    HealthCheckResponse,
    IdentifiedModel,
    OrganizationScopedModel,
    PaginatedResponse,
    PaginationParams,
    TimestampedModel,
)
from pydantic import Field, ValidationError


class TestZernaBaseModel:
    """Test suite for ZernaBaseModel."""

    def test_base_model_creation(self):
        """Test creating a model that inherits from ZernaBaseModel."""

        class TestModel(ZernaBaseModel):
            name: str
            value: int = Field(ge=0)

        model = TestModel(name="test", value=42)
        assert model.name == "test"
        assert model.value == 42

    def test_base_model_validation(self):
        """Test that validation works on base models."""

        class TestModel(ZernaBaseModel):
            value: int = Field(ge=0)

        # Valid value
        model = TestModel(value=10)
        assert model.value == 10

        # Invalid value
        with pytest.raises(ValidationError):
            TestModel(value=-1)

    def test_base_model_forbids_extra_fields(self):
        """Test that extra fields are forbidden by default."""

        class TestModel(ZernaBaseModel):
            name: str

        with pytest.raises(ValidationError):
            TestModel(name="test", extra_field="not allowed")


class TestTimestampedModel:
    """Test suite for TimestampedModel."""

    def test_timestamped_model_auto_timestamp(self):
        """Test that created_at is automatically set."""

        class TestModel(TimestampedModel):
            data: str

        before = datetime.utcnow()
        model = TestModel(data="test")
        after = datetime.utcnow()

        assert before <= model.created_at <= after

    def test_timestamped_model_custom_timestamp(self):
        """Test that created_at can be explicitly set."""

        class TestModel(TimestampedModel):
            data: str

        custom_time = datetime(2024, 1, 1, 12, 0, 0)
        model = TestModel(data="test", created_at=custom_time)

        assert model.created_at == custom_time


class TestOrganizationScopedModel:
    """Test suite for OrganizationScopedModel."""

    def test_organization_scoped_model(self):
        """Test organization scoped model requires organization_id."""

        class TestModel(OrganizationScopedModel):
            name: str

        org_id = uuid4()
        model = TestModel(organization_id=org_id, name="test")

        assert model.organization_id == org_id
        assert model.name == "test"
        assert isinstance(model.created_at, datetime)

    def test_organization_scoped_model_requires_org_id(self):
        """Test that organization_id is required."""

        class TestModel(OrganizationScopedModel):
            name: str

        with pytest.raises(ValidationError):
            TestModel(name="test")


class TestIdentifiedModel:
    """Test suite for IdentifiedModel."""

    def test_identified_model(self):
        """Test identified model with UUID."""

        class TestModel(IdentifiedModel):
            name: str

        test_id = uuid4()
        model = TestModel(id=test_id, name="test")

        assert model.id == test_id
        assert model.name == "test"


class TestPaginationParams:
    """Test suite for PaginationParams."""

    def test_pagination_defaults(self):
        """Test default pagination values."""
        params = PaginationParams()

        assert params.page == 1
        assert params.page_size == 20

    def test_pagination_custom_values(self):
        """Test custom pagination values."""
        params = PaginationParams(page=5, page_size=50)

        assert params.page == 5
        assert params.page_size == 50

    def test_pagination_validation(self):
        """Test pagination validation rules."""
        # Page must be >= 1
        with pytest.raises(ValidationError):
            PaginationParams(page=0)

        # Page size must be >= 1
        with pytest.raises(ValidationError):
            PaginationParams(page_size=0)

        # Page size must be <= 100
        with pytest.raises(ValidationError):
            PaginationParams(page_size=101)


class TestPaginatedResponse:
    """Test suite for PaginatedResponse."""

    def test_paginated_response(self):
        """Test paginated response structure."""
        response = PaginatedResponse(total=100, page=2, page_size=20)

        assert response.total == 100
        assert response.page == 2
        assert response.page_size == 20


class TestErrorResponse:
    """Test suite for ErrorResponse."""

    def test_error_response_creation(self):
        """Test creating an error response."""
        response = ErrorResponse(
            error_type="user_error",
            error_code="INVALID_INPUT",
            message="Invalid input provided",
            request_id="req-123",
        )

        assert response.error_type == "user_error"
        assert response.error_code == "INVALID_INPUT"
        assert response.message == "Invalid input provided"
        assert response.request_id == "req-123"
        assert response.details is None
        assert isinstance(response.timestamp, datetime)

    def test_error_response_with_details(self):
        """Test error response with additional details."""
        response = ErrorResponse(
            error_type="validation_error",
            error_code="FIELD_REQUIRED",
            message="Field is required",
            details={"field": "email", "constraint": "required"},
            request_id="req-456",
        )

        assert response.details == {"field": "email", "constraint": "required"}


class TestHealthCheckResponse:
    """Test suite for HealthCheckResponse."""

    def test_health_check_response(self):
        """Test health check response."""
        response = HealthCheckResponse(status="healthy", version="0.1.0")

        assert response.status == "healthy"
        assert response.version == "0.1.0"
        assert isinstance(response.timestamp, datetime)
        assert response.dependencies is None

    def test_health_check_with_dependencies(self):
        """Test health check with dependency status."""
        response = HealthCheckResponse(
            status="healthy",
            version="0.1.0",
            dependencies={"database": "healthy", "redis": "healthy", "s3": "healthy"},
        )

        assert response.dependencies == {"database": "healthy", "redis": "healthy", "s3": "healthy"}
