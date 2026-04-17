"""OpenTelemetry setup — emits spans via OTLP gRPC to Phoenix.

Uses GenAI semantic conventions:
  https://opentelemetry.io/docs/specs/semconv/gen-ai/
Extended with Donna-specific attributes:
  agent.job.id, agent.job.tainted, agent.taint.source_tool,
  agent.scope, agent.mode, agent.tool.name
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..config import settings

_initialized = False
_tracer: trace.Tracer | None = None


def initialize_tracing() -> None:
    global _initialized, _tracer
    if _initialized:
        return
    s = settings()
    resource = Resource.create({
        "service.name": s.otel_service_name,
        "service.namespace": "donna",
        "deployment.environment": s.env,
    })
    provider = TracerProvider(resource=resource)
    # Don't crash if Phoenix isn't up; exporter will silently retry
    try:
        exporter = OTLPSpanExporter(endpoint=s.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:
        pass
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("donna")
    _initialized = True


def tracer() -> trace.Tracer:
    if not _initialized:
        initialize_tracing()
    assert _tracer is not None
    return _tracer


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    t = tracer()
    with t.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            if v is not None:
                try:
                    sp.set_attribute(k, v)
                except Exception:
                    sp.set_attribute(k, str(v))
        yield sp


def set_attr(key: str, value: Any) -> None:
    sp = trace.get_current_span()
    if sp is not None:
        try:
            sp.set_attribute(key, value)
        except Exception:
            sp.set_attribute(key, str(value))
