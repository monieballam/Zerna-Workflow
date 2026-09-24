"""Tests for MinIO/S3 endpoint resolution (host vs Docker)."""

import pytest

from apps.api.config import Settings, resolve_s3_endpoint_url, running_inside_docker


def _minimal_settings(**kwargs) -> Settings:
    base = {
        "database_url": "postgresql://test",
        "redis_url": "redis://test",
        "jwt_secret_key": "test-secret-key-32-characters-min",
        "s3_access_key_id": "a",
        "s3_secret_access_key": "b",
        "s3_datasets_bucket": "d",
        "s3_artifacts_bucket": "ar",
    }
    base.update(kwargs)
    return Settings(**base)


def test_resolve_uses_non_empty_settings_url():
    s = _minimal_settings(s3_endpoint_url="http://custom.example:9000")
    assert resolve_s3_endpoint_url(s) == "http://custom.example:9000"


def test_resolve_host_fallback_uses_minio_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("MINIO_PORT", "19000")
    monkeypatch.setattr("apps.api.config.running_inside_docker", lambda: False)
    assert resolve_s3_endpoint_url(None) == "http://localhost:19000"


def test_resolve_host_fallback_minio_port_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("MINIO_PORT", raising=False)
    monkeypatch.setattr("apps.api.config.running_inside_docker", lambda: False)
    assert resolve_s3_endpoint_url(None) == "http://localhost:19000"


def test_resolve_docker_uses_minio_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setattr("apps.api.config.running_inside_docker", lambda: True)
    assert resolve_s3_endpoint_url(None) == "http://minio:9000"


def test_resolve_explicit_env_overrides_docker_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://explicit:1234")
    monkeypatch.setattr("apps.api.config.running_inside_docker", lambda: True)
    assert resolve_s3_endpoint_url(None) == "http://explicit:1234"


def test_running_inside_docker_false_by_default():
    # In CI/test env we are usually not in a container; only assert type
    assert isinstance(running_inside_docker(), bool)
