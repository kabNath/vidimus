"""OpenTelemetry OTLP/HTTP receiver.

Listens on port 4318 (the OpenTelemetry standard) and accepts OTLP-encoded
trace data in JSON form. Each OTel span is converted into a Vidimus ``Trace``
and inserted into the configured store.

This is what makes Vidimus "drop-in" alongside Opik, Langfuse, OpenLLMetry,
LangChain's OTel exporter, or any framework that emits OpenTelemetry traces.
Point your existing OTel exporter at ``http://localhost:4318`` and Vidimus
ingests everything in parallel with your existing observability backend.

Requires the optional dependencies:

    pip install vidimus[otel]

Example:

    from vidimus.receivers import OTLPHttpReceiver
    receiver = OTLPHttpReceiver(workspace="my-workspace", port=4318)
    receiver.run()  # blocks; use a thread for embedded use cases
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from vidimus.audit.schemas import Span, Trace

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# OTLP JSON span → Vidimus Trace conversion
# ─────────────────────────────────────────────────────────────────────────────


def _otel_attr_to_python(attr: dict[str, Any]) -> Any:
    """Convert one OTLP attribute value to a plain Python value.

    OTLP wraps values in a typed envelope: ``{"stringValue": "x"}``,
    ``{"intValue": "42"}``, etc.
    """
    value = attr.get("value", {})
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        return [_otel_attr_to_python({"value": v}) for v in value["arrayValue"].get("values", [])]
    return None


def _attrs_dict(attributes: list[dict[str, Any]]) -> dict[str, Any]:
    """OTLP attributes are a list of {"key": "...", "value": {...}} dicts."""
    out: dict[str, Any] = {}
    for a in attributes:
        key = a.get("key", "")
        out[key] = _otel_attr_to_python(a)
    return out


def _otel_status_to_vidimus(status_obj: dict[str, Any] | None) -> str:
    """Map OTel status code (0/1/2) to Vidimus literal."""
    if not status_obj:
        return "unset"
    code = status_obj.get("code", 0)
    return {0: "unset", 1: "ok", 2: "error"}.get(code, "unset")


def _ns_to_int(value: Any) -> int:
    """OTLP encodes nanoseconds as string in JSON; coerce safely."""
    if value is None:
        return 0
    return int(value)


def otlp_span_to_vidimus_span(otel_span: dict[str, Any]) -> Span:
    """Convert a single OTLP JSON span into a Vidimus ``Span``."""
    attrs = _attrs_dict(otel_span.get("attributes", []))
    # Pydantic Span only accepts scalar attribute values
    clean_attrs: dict[str, str | int | float | bool] = {}
    for k, v in attrs.items():
        if isinstance(v, (str, int, float, bool)):
            clean_attrs[k] = v
        else:
            clean_attrs[k] = str(v)

    return Span(
        span_id=otel_span.get("spanId", ""),
        parent_span_id=otel_span.get("parentSpanId") or None,
        name=otel_span.get("name", ""),
        start_ns=_ns_to_int(otel_span.get("startTimeUnixNano")),
        end_ns=_ns_to_int(otel_span.get("endTimeUnixNano")),
        attributes=clean_attrs,
        status=_otel_status_to_vidimus(otel_span.get("status")),
    )


def otlp_request_to_vidimus_traces(
    payload: dict[str, Any], workspace: str
) -> list[Trace]:
    """Convert a complete OTLP/HTTP trace request into Vidimus Traces.

    OTLP groups spans by trace_id implicitly (multiple spans share a trace_id).
    We group them, build one Vidimus Trace per OTel trace_id, and put all the
    spans of that trace_id inside.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    resource_attrs: dict[str, dict[str, Any]] = {}

    for resource_span in payload.get("resourceSpans", []):
        resource = resource_span.get("resource", {})
        resource_attr_dict = _attrs_dict(resource.get("attributes", []))

        for scope_span in resource_span.get("scopeSpans", []):
            for s in scope_span.get("spans", []):
                tid = s.get("traceId", "")
                grouped.setdefault(tid, []).append(s)
                resource_attrs.setdefault(tid, resource_attr_dict)

    traces: list[Trace] = []
    for trace_id, otel_spans in grouped.items():
        spans = [otlp_span_to_vidimus_span(s) for s in otel_spans]
        # Use the root span (parent_span_id is None) as the source of the trace
        # input/output, falling back to the first span if there is no clear root.
        root = next((s for s in spans if s.parent_span_id is None), spans[0])
        input_value = root.attributes.get("gen_ai.prompt") or root.attributes.get("input") or ""
        output_value = root.attributes.get("gen_ai.completion") or root.attributes.get("output") or ""
        model = root.attributes.get("gen_ai.model_name") or root.attributes.get("model")
        captured_at = datetime.fromtimestamp(root.start_ns / 1_000_000_000, tz=timezone.utc) \
            if root.start_ns else datetime.now(timezone.utc)

        traces.append(
            Trace(
                trace_id=trace_id,
                workspace=workspace,
                spans=spans,
                input=str(input_value),
                output=str(output_value),
                model=str(model) if model else None,
                cost_usd=None,
                captured_at=captured_at,
            )
        )

    return traces


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI receiver
# ─────────────────────────────────────────────────────────────────────────────


class OTLPHttpReceiver:
    """HTTP server that accepts OTLP/JSON traces and stores them in Vidimus.

    Args:
        workspace: Workspace to assign incoming traces to.
        host: Bind address. Default ``0.0.0.0`` for container-friendly access.
        port: Listening port. Default 4318 (OpenTelemetry standard).
        store: Optional pre-configured store. Defaults to the active config store.

    Example:
        >>> from vidimus.receivers import OTLPHttpReceiver
        >>> receiver = OTLPHttpReceiver(workspace="acme-prod")
        >>> receiver.run()
    """

    def __init__(
        self,
        workspace: str,
        host: str = "0.0.0.0",
        port: int = 4318,
        store: Any = None,
    ):
        try:
            from fastapi import Body, FastAPI
        except ImportError as exc:
            raise ImportError(
                "OTLPHttpReceiver requires 'fastapi' and 'uvicorn'. "
                "Install with: pip install vidimus[otel]"
            ) from exc

        self._workspace = workspace
        self._host = host
        self._port = port

        if store is None:
            from vidimus.config import get_config
            store = get_config().store
        self._store = store

        self.app = FastAPI(
            title="Vidimus OTLP receiver",
            description="Accepts OpenTelemetry OTLP/HTTP traces and forwards them to Vidimus.",
            version="0.1.0a1",
        )

        @self.app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "workspace": self._workspace,
                "traces_stored": self._store.count(self._workspace),
                "timestamp": time.time(),
            }

        @self.app.post("/v1/traces")
        async def receive_traces(payload: dict = Body(...)) -> dict[str, Any]:
            traces = otlp_request_to_vidimus_traces(payload, workspace=self._workspace)
            for t in traces:
                self._store.add_trace(t)
            logger.info("OTLP receiver ingested %d traces", len(traces))
            return {"partialSuccess": {}, "stored": len(traces)}

    def run(self) -> None:
        """Start the receiver. Blocks until terminated."""
        try:
            import uvicorn
        except ImportError as exc:
            raise ImportError(
                "Running the receiver requires 'uvicorn'. "
                "Install with: pip install vidimus[otel]"
            ) from exc

        logger.info(
            "Starting Vidimus OTLP receiver on http://%s:%d (workspace=%s)",
            self._host, self._port, self._workspace,
        )
        uvicorn.run(self.app, host=self._host, port=self._port, log_level="info")
