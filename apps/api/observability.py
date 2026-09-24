"""OpenTelemetry instrumentation setup for the Zerna Control Plane API."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

logger = logging.getLogger(__name__)


def setup_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
    environment: str = "development",
) -> TracerProvider:
    """Configure OpenTelemetry tracing with OTLP exporter.

    Args:
        service_name: Name of the service (e.g. "zerna-api")
        otlp_endpoint: OTLP gRPC endpoint (e.g. "http://jaeger:4317")
        environment: Deployment environment

    Returns:
        Configured TracerProvider
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )

    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info("OpenTelemetry OTLP exporter configured: %s", otlp_endpoint)
    else:
        # Fallback: log spans to console in development
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        logger.info("OpenTelemetry console exporter configured (no OTLP endpoint)")

    trace.set_tracer_provider(provider)
    return provider


def setup_metrics(service_name: str) -> None:
    """Configure OpenTelemetry metrics with Prometheus exporter.

    Prometheus scrapes /metrics endpoint exposed by the SDK.

    Args:
        service_name: Name of the service
    """
    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from opentelemetry.sdk.metrics import MeterProvider

        reader = PrometheusMetricReader()
        meter_provider = MeterProvider(
            resource=Resource.create({"service.name": service_name}),
            metric_readers=[reader],
        )

        from opentelemetry import metrics as otel_metrics

        otel_metrics.set_meter_provider(meter_provider)
        logger.info("OpenTelemetry Prometheus metrics configured for %s", service_name)
    except ImportError:
        logger.warning("opentelemetry-exporter-prometheus not installed; metrics disabled")


def instrument_fastapi(app: FastAPI) -> None:
    """Attach FastAPI auto-instrumentation to the application.

    This automatically creates spans for every HTTP request/response.

    Args:
        app: FastAPI application instance
    """
    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI OpenTelemetry instrumentation enabled")


def get_tracer(name: str = "zerna") -> trace.Tracer:
    """Return a named tracer for manual span creation.

    Args:
        name: Instrumentation scope name

    Returns:
        OpenTelemetry Tracer
    """
    return trace.get_tracer(name)
