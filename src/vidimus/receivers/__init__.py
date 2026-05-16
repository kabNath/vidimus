"""Ingestion receivers — drop Vidimus in next to your existing observability stack.

Currently ships:
  - ``OTLPHttpReceiver``: accepts OpenTelemetry OTLP/HTTP traces on port 4318.

Any framework that emits OpenTelemetry traces (LangChain, LlamaIndex,
OpenLLMetry, Opik, Langfuse OTel exporter, raw OTel SDK) can point at the
receiver and have its traces ingested into Vidimus in parallel with whatever
observability backend it normally sends to.

Requires the optional dependency: ``pip install vidimus[otel]``.
"""

try:
    from vidimus.receivers.otlp import OTLPHttpReceiver  # noqa: F401

    _has_otel = True
except ImportError:
    _has_otel = False

__all__ = []
if _has_otel:
    __all__.append("OTLPHttpReceiver")
