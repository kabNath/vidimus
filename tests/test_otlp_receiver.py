"""Tests for the OpenTelemetry OTLP/HTTP receiver."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vidimus.receivers.otlp import (
    OTLPHttpReceiver,
    _attrs_dict,
    _otel_attr_to_python,
    _otel_status_to_vidimus,
    otlp_request_to_vidimus_traces,
    otlp_span_to_vidimus_span,
)
from vidimus.storage.memory import InMemoryStore


# ─────────────────────────────────────────────────────────────────────────────
# Attribute conversion
# ─────────────────────────────────────────────────────────────────────────────


class TestAttributeConversion:
    def test_string_value(self):
        assert _otel_attr_to_python({"value": {"stringValue": "hello"}}) == "hello"

    def test_int_value(self):
        # OTLP encodes ints as strings to preserve precision over JSON
        assert _otel_attr_to_python({"value": {"intValue": "42"}}) == 42

    def test_double_value(self):
        assert _otel_attr_to_python({"value": {"doubleValue": 3.14}}) == 3.14

    def test_bool_value(self):
        assert _otel_attr_to_python({"value": {"boolValue": True}}) is True

    def test_unknown_value_returns_none(self):
        assert _otel_attr_to_python({"value": {"unknownType": "x"}}) is None

    def test_attrs_dict(self):
        attrs = [
            {"key": "name", "value": {"stringValue": "test"}},
            {"key": "count", "value": {"intValue": "5"}},
        ]
        result = _attrs_dict(attrs)
        assert result == {"name": "test", "count": 5}


# ─────────────────────────────────────────────────────────────────────────────
# Status conversion
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusConversion:
    def test_none(self):
        assert _otel_status_to_vidimus(None) == "unset"

    def test_ok(self):
        assert _otel_status_to_vidimus({"code": 1}) == "ok"

    def test_error(self):
        assert _otel_status_to_vidimus({"code": 2}) == "error"


# ─────────────────────────────────────────────────────────────────────────────
# Span conversion
# ─────────────────────────────────────────────────────────────────────────────


def _make_otlp_span(span_id: str = "abc123", parent: str | None = None, name: str = "test_span") -> dict:
    return {
        "traceId": "trace-001",
        "spanId": span_id,
        "parentSpanId": parent or "",
        "name": name,
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000001000000000",
        "attributes": [
            {"key": "model", "value": {"stringValue": "gpt-4o"}},
            {"key": "tokens", "value": {"intValue": "42"}},
        ],
        "status": {"code": 1},
    }


class TestSpanConversion:
    def test_basic_span(self):
        otel = _make_otlp_span()
        span = otlp_span_to_vidimus_span(otel)
        assert span.span_id == "abc123"
        assert span.name == "test_span"
        assert span.attributes["model"] == "gpt-4o"
        assert span.attributes["tokens"] == 42
        assert span.status == "ok"

    def test_empty_parent_becomes_none(self):
        otel = _make_otlp_span(parent="")
        span = otlp_span_to_vidimus_span(otel)
        assert span.parent_span_id is None

    def test_with_parent(self):
        otel = _make_otlp_span(parent="parent-id")
        span = otlp_span_to_vidimus_span(otel)
        assert span.parent_span_id == "parent-id"


# ─────────────────────────────────────────────────────────────────────────────
# Full OTLP request conversion
# ─────────────────────────────────────────────────────────────────────────────


class TestRequestConversion:
    def test_single_trace(self):
        payload = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {},
                    "spans": [_make_otlp_span()],
                }],
            }],
        }
        traces = otlp_request_to_vidimus_traces(payload, workspace="ws")
        assert len(traces) == 1
        assert traces[0].trace_id == "trace-001"
        assert traces[0].workspace == "ws"
        assert len(traces[0].spans) == 1

    def test_multiple_spans_same_trace(self):
        payload = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {},
                    "spans": [
                        _make_otlp_span(span_id="a", name="root"),
                        _make_otlp_span(span_id="b", parent="a", name="child"),
                    ],
                }],
            }],
        }
        traces = otlp_request_to_vidimus_traces(payload, workspace="ws")
        assert len(traces) == 1  # Both spans go in the same Vidimus trace
        assert len(traces[0].spans) == 2

    def test_empty_payload(self):
        assert otlp_request_to_vidimus_traces({"resourceSpans": []}, workspace="ws") == []


# ─────────────────────────────────────────────────────────────────────────────
# HTTP endpoint (TestClient)
# ─────────────────────────────────────────────────────────────────────────────


class TestHttpReceiver:
    @pytest.fixture
    def receiver_and_client(self):
        store = InMemoryStore()
        receiver = OTLPHttpReceiver(workspace="test-ws", store=store)
        client = TestClient(receiver.app)
        return receiver, client, store

    def test_health(self, receiver_and_client):
        _, client, _ = receiver_and_client
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["workspace"] == "test-ws"

    def test_receive_single_trace(self, receiver_and_client):
        _, client, store = receiver_and_client
        payload = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "spans": [_make_otlp_span()],
                }],
            }],
        }
        r = client.post("/v1/traces", json=payload)
        assert r.status_code == 200
        assert r.json()["stored"] == 1
        assert store.count("test-ws") == 1

    def test_receive_multiple_traces(self, receiver_and_client):
        _, client, store = receiver_and_client
        # Build a payload with three distinct trace_ids
        payload = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "spans": [
                        {**_make_otlp_span(), "traceId": f"trace-{i}"}
                        for i in range(3)
                    ],
                }],
            }],
        }
        r = client.post("/v1/traces", json=payload)
        assert r.json()["stored"] == 3
        assert store.count("test-ws") == 3

    def test_receive_empty(self, receiver_and_client):
        _, client, store = receiver_and_client
        r = client.post("/v1/traces", json={"resourceSpans": []})
        assert r.status_code == 200
        assert r.json()["stored"] == 0
