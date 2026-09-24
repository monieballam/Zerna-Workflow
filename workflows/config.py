"""Configuration management for Temporal workflows."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkflowSettings(BaseSettings):
    """Workflow settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Temporal configuration
    temporal_address: str = Field(default="localhost:7233", description="Temporal server address")
    temporal_namespace: str = Field(default="default", description="Temporal namespace")
    temporal_task_queue: str = Field(
        default="zerna-control-plane", description="Temporal task queue name"
    )
    temporal_max_concurrent_activities: int = Field(
        default=4, description="Maximum concurrent activity tasks handled by the worker"
    )
    temporal_max_concurrent_workflow_tasks: int = Field(
        default=16, description="Maximum concurrent workflow tasks handled by the worker"
    )
    worker_ready_file: str | None = Field(
        default=None, description="Path to a readiness marker written after the worker connects"
    )

    # Database
    database_url: str = Field(..., description="PostgreSQL connection string")

    # Redis
    redis_url: str = Field(..., description="Redis connection string")

    # S3
    s3_endpoint_url: str | None = Field(default=None, description="S3 endpoint URL (for MinIO)")
    s3_access_key_id: str = Field(..., description="S3 access key ID")
    s3_secret_access_key: str = Field(..., description="S3 secret access key")
    s3_region: str = Field(default="us-east-1", description="S3 region")
    s3_datasets_bucket: str = Field(..., description="S3 datasets bucket name")
    s3_artifacts_bucket: str = Field(..., description="S3 artifacts bucket name")

    # Retry policies
    activity_start_to_close_timeout_seconds: int = Field(
        default=300, description="Activity start-to-close timeout in seconds"
    )
    activity_retry_initial_interval_seconds: int = Field(
        default=1, description="Initial retry interval in seconds"
    )
    activity_retry_maximum_interval_seconds: int = Field(
        default=60, description="Maximum retry interval in seconds"
    )
    activity_retry_backoff_coefficient: float = Field(
        default=2.0, description="Retry backoff coefficient"
    )
    activity_retry_maximum_attempts: int = Field(default=5, description="Maximum retry attempts")

    # Workflow timeouts
    workflow_execution_timeout_seconds: int = Field(
        default=3600, description="Workflow execution timeout in seconds"
    )
    workflow_run_timeout_seconds: int = Field(
        default=3600, description="Workflow run timeout in seconds"
    )

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", description="OTLP exporter endpoint"
    )
    otel_service_name: str = Field(default="zerna-workflows", description="Service name")

    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_format: str = Field(default="json", description="Log format (json or text)")


@lru_cache
def get_workflow_settings() -> WorkflowSettings:
    """Get cached workflow settings instance."""
    return WorkflowSettings()
