"""OpenTelemetry metrics instruments for Zerna API.

Provides pre-built histograms and counters used across the application:
- run_duration_seconds   (histogram)
- artifact_size_bytes    (histogram)
- api_latency_seconds    (histogram)
- error_total            (counter)
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("zerna.api")

# Histogram: pipeline run duration in seconds
run_duration_histogram = _meter.create_histogram(
    name="zerna.run.duration_seconds",
    description="Duration of pipeline runs in seconds",
    unit="s",
)

# Histogram: artifact size in bytes
artifact_size_histogram = _meter.create_histogram(
    name="zerna.artifact.size_bytes",
    description="Size of produced artifacts in bytes",
    unit="By",
)

# Histogram: API endpoint latency in seconds
api_latency_histogram = _meter.create_histogram(
    name="zerna.api.latency_seconds",
    description="HTTP API request latency in seconds",
    unit="s",
)

# Counter: total errors by type and endpoint
error_counter = _meter.create_counter(
    name="zerna.api.errors_total",
    description="Total number of errors by type and endpoint",
)


def record_run_duration(duration_seconds: float, org_id: str, status: str) -> None:
    """Record a completed run's duration.

    Args:
        duration_seconds: Wall-clock duration of the run
        org_id: Organization identifier for attribution
        status: Final run status (completed, failed, cancelled)
    """
    run_duration_histogram.record(
        duration_seconds,
        attributes={"org_id": org_id, "status": status},
    )


def record_artifact_size(size_bytes: int, artifact_type: str, org_id: str) -> None:
    """Record the size of a produced artifact.

    Args:
        size_bytes: Artifact size in bytes
        artifact_type: Type of artifact (h5ad, csv, report, …)
        org_id: Organization identifier
    """
    artifact_size_histogram.record(
        size_bytes,
        attributes={"artifact_type": artifact_type, "org_id": org_id},
    )


def record_api_latency(
    latency_seconds: float, endpoint: str, method: str, status_code: int
) -> None:
    """Record HTTP request latency.

    Args:
        latency_seconds: Request processing time
        endpoint: Route path (e.g. "/v1/runs")
        method: HTTP method (GET, POST, …)
        status_code: HTTP response status code
    """
    api_latency_histogram.record(
        latency_seconds,
        attributes={
            "endpoint": endpoint,
            "http.method": method,
            "http.status_code": str(status_code),
        },
    )


def increment_error(error_type: str, endpoint: str) -> None:
    """Increment the error counter.

    Args:
        error_type: Classification (user_error, system_error, transient_error)
        endpoint: Route path where the error occurred
    """
    error_counter.add(
        1,
        attributes={"error_type": error_type, "endpoint": endpoint},
    )
    # Alert on high system/transient error rates via structured log
    # (Prometheus alerting rules consume these metrics; log for CloudWatch)
    if error_type in ("system_error", "transient_error"):
        import logging as _logging

        _logging.getLogger("zerna.errors").warning(
            "Error recorded",
            extra={"error_type": error_type, "endpoint": endpoint},
        )


# ---------------------------------------------------------------------------
# Quota metrics
# ---------------------------------------------------------------------------

_quota_meter = metrics.get_meter("zerna.quota")

storage_quota_gauge = _quota_meter.create_gauge(
    name="zerna.quota.storage_used_bytes",
    description="Current storage used per organization in bytes",
    unit="By",
)

compute_quota_gauge = _quota_meter.create_gauge(
    name="zerna.quota.active_runs",
    description="Current number of active (queued/running) runs per organization",
    unit="{runs}",
)

# Threshold for "approaching quota" alerts (80 %)
QUOTA_ALERT_THRESHOLD_PCT = 80.0


def record_storage_quota_usage(org_id: str, used_bytes: int, limit_bytes: int) -> None:
    """Emit storage quota usage metrics and log an alert if approaching limit.

    Args:
        org_id: Organization identifier.
        used_bytes: Current storage used in bytes.
        limit_bytes: Storage quota limit in bytes.
    """
    import logging

    storage_quota_gauge.set(used_bytes, attributes={"org_id": org_id})

    if limit_bytes > 0:
        pct = used_bytes / limit_bytes * 100
        if pct >= QUOTA_ALERT_THRESHOLD_PCT:
            logging.getLogger("zerna.quota").warning(
                "Organization approaching storage quota",
                extra={
                    "org_id": org_id,
                    "used_bytes": used_bytes,
                    "limit_bytes": limit_bytes,
                    "utilization_pct": round(pct, 2),
                },
            )


def record_compute_quota_usage(org_id: str, active_runs: int, limit_runs: int) -> None:
    """Emit compute quota usage metrics and log an alert if approaching limit.

    Args:
        org_id: Organization identifier.
        active_runs: Current number of active runs.
        limit_runs: Compute quota limit (max concurrent runs).
    """
    import logging

    compute_quota_gauge.set(active_runs, attributes={"org_id": org_id})

    if limit_runs > 0:
        pct = active_runs / limit_runs * 100
        if pct >= QUOTA_ALERT_THRESHOLD_PCT:
            logging.getLogger("zerna.quota").warning(
                "Organization approaching compute quota",
                extra={
                    "org_id": org_id,
                    "active_runs": active_runs,
                    "limit_runs": limit_runs,
                    "utilization_pct": round(pct, 2),
                },
            )
