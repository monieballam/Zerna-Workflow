"""Configuration management for Zerna API."""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: str = Field(default="development", description="Environment name")

    # Database
    database_url: str | None = Field(default=None, description="PostgreSQL connection string")
    postgres_user: str = Field(default="zerna", description="PostgreSQL user")
    postgres_password: str = Field(default="zerna_dev_password", description="PostgreSQL password")
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="zerna", description="PostgreSQL database name")

    # Redis
    redis_url: str | None = Field(default=None, description="Redis connection string")
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: str = Field(default="zerna_redis_password", description="Redis password")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_cache_ttl: int = Field(default=300, description="Cache TTL in seconds")
    redis_session_ttl: int = Field(default=3600, description="Session TTL in seconds")

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_workers: int = Field(default=4, description="Number of API workers")
    api_reload: bool = Field(default=True, description="Enable hot reload")

    # CORS
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated CORS origins",
    )

    # Rate limiting
    rate_limit_per_minute: int = Field(default=100, description="Rate limit per minute per user")

    # After 5 failed logins, block further attempts for 15 minutes (stored in Redis).
    # Set false for local development if you hit 429 after wrong passwords.
    auth_login_lockout_enabled: bool = Field(
        default=True,
        description="Enable Redis-backed lockout after repeated failed login attempts",
    )
    # When true, API endpoints accept unauthenticated requests as the bootstrap admin.
    auth_disabled: bool = Field(
        default=False,
        description="Disable sign-in; treat requests without a Bearer token as the bootstrap admin",
    )

    # Authentication
    jwt_secret_key: str = Field(..., description="JWT secret key for signing")
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm (HS256 for local dev; set RS256 + PEM in JWT_SECRET_KEY for production)",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=60, description="Access token expiration in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30, description="Refresh token expiration in days"
    )
    password_hash_algorithm: str = Field(
        default="argon2id", description="Password hashing algorithm"
    )
    bootstrap_admin_email: str | None = Field(
        default="admin@zerna.local",
        description="Promote this user to admin in the current app org when present.",
    )
    bootstrap_admin_password: str | None = Field(
        default=None,
        description="Optional password used to create the bootstrap admin if missing.",
    )
    bootstrap_admin_org_name: str = Field(
        default="Zerna",
        description="Organization to use when creating or attaching the bootstrap admin.",
    )

    # Multi-tenancy
    default_storage_quota_gb: int = Field(default=1000, description="Default storage quota in GB")
    default_compute_quota_runs: int = Field(
        default=10, description="Default compute quota for concurrent runs"
    )

    # S3 / MinIO — see ``resolve_s3_endpoint_url`` when this is unset
    s3_endpoint_url: str | None = Field(
        default=None,
        description=(
            "S3-compatible endpoint (MinIO). If unset: Docker uses http://minio:9000; "
            "host dev uses http://localhost:${MINIO_PORT:-19000}"
        ),
    )
    s3_access_key_id: str = Field(..., description="S3 access key ID")
    s3_secret_access_key: str = Field(..., description="S3 secret access key")
    s3_region: str = Field(default="us-east-1", description="S3 region")
    s3_datasets_bucket: str = Field(..., description="S3 datasets bucket name")
    s3_artifacts_bucket: str = Field(..., description="S3 artifacts bucket name")

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", description="OTLP exporter endpoint"
    )
    otel_service_name: str = Field(default="zerna-api", description="Service name")

    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_format: str = Field(default="json", description="Log format (json or text)")
    sql_echo: bool = Field(default=False, description="Enable SQL query logging")

    # Debug
    debug: bool = Field(default=False, description="Enable debug mode")

    # Stale run reconciliation
    stale_run_reconciler_enabled: bool = Field(
        default=True,
        description="Run a background reconciler that repairs stale RUNNING runs",
    )
    stale_run_reconciler_interval_seconds: int = Field(
        default=30,
        description="How often to scan for stale RUNNING runs",
    )
    stale_run_threshold_seconds: int = Field(
        default=120,
        description="How old progress.updated_at must be before a RUNNING run is considered stale",
    )
    stale_run_max_auto_restart_attempts: int = Field(
        default=2,
        description="Maximum automatic restarts from checkpoint before a stale run is failed",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def async_database_url(self) -> str:
        """Build async database URL from components, falling back to DATABASE_URL."""
        if self.database_url and "${" not in self.database_url:
            url = self.database_url
        else:
            url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        # Ensure asyncpg driver prefix
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def resolved_redis_url(self) -> str:
        """Build Redis URL from components, falling back to REDIS_URL."""
        if self.redis_url and "${" not in self.redis_url:
            return self.redis_url
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"


def running_inside_docker() -> bool:
    """True when the process likely runs in a container (compose worker/API)."""
    if os.path.exists("/.dockerenv"):
        return True
    flag = os.getenv("RUNNING_IN_DOCKER", "").strip().lower()
    return flag in ("1", "true", "yes")


def resolve_s3_endpoint_url(settings: Settings | None = None) -> str:
    """Resolve the boto3 S3 endpoint for MinIO or compatible storage.

    Precedence:
    1. ``settings.s3_endpoint_url`` when set to a non-empty string (from ``S3_ENDPOINT_URL``).
    2. Environment variable ``S3_ENDPOINT_URL`` (recommended for all deployments).
    3. Inside Docker (see :func:`running_inside_docker`): ``http://minio:9000`` (compose network).
    4. On the host: ``http://localhost:{MINIO_PORT}`` with default ``MINIO_PORT=19000`` to match
       the repo's docker-compose host port mapping for MinIO.

    This avoids stale defaults like ``localhost:9000`` when MinIO is mapped to another host port.
    """
    if settings is not None:
        raw = getattr(settings, "s3_endpoint_url", None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    explicit = os.getenv("S3_ENDPOINT_URL", "").strip()
    if explicit:
        return explicit
    if running_inside_docker():
        return "http://minio:9000"
    port = os.getenv("MINIO_PORT", "19000").strip() or "19000"
    return f"http://localhost:{port}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # type: ignore[call-arg]  # BaseSettings loads required values from env.
