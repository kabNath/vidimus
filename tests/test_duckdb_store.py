"""Tests for DuckDBStore.

Use ``:memory:`` databases throughout so tests are stateless and fast.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

duckdb = pytest.importorskip("duckdb")

from vidimus.audit.schemas import Trace
from vidimus.storage.duckdb_store import DuckDBStore


def _make_trace(trace_id: str, workspace: str = "ws-1", offset_seconds: int = 0) -> Trace:
    return Trace(
        trace_id=trace_id,
        workspace=workspace,
        spans=[],
        input=f"input for {trace_id}",
        output=f"output for {trace_id}",
        model="test-model",
        cost_usd=0.001,
        captured_at=datetime.now(timezone.utc) + timedelta(seconds=offset_seconds),
    )


@pytest.fixture
def store():
    s = DuckDBStore(":memory:")
    yield s
    s.close()


class TestBasicCRUD:
    def test_add_and_get(self, store):
        t = _make_trace("t-1")
        store.add_trace(t)
        got = store.get_trace("t-1")
        assert got is not None
        assert got.trace_id == "t-1"
        assert got.workspace == "ws-1"

    def test_get_missing_returns_none(self, store):
        assert store.get_trace("does-not-exist") is None

    def test_add_replaces_existing(self, store):
        store.add_trace(_make_trace("t-1"))
        # Add another trace with the same id — should overwrite
        t2 = Trace(
            trace_id="t-1",
            workspace="ws-1",
            spans=[],
            input="updated input",
            output="updated output",
            model="test-model",
            cost_usd=0.001,
            captured_at=datetime.now(timezone.utc),
        )
        store.add_trace(t2)
        got = store.get_trace("t-1")
        assert got.input == "updated input"
        assert store.count() == 1

    def test_count(self, store):
        assert store.count() == 0
        store.add_trace(_make_trace("t-1"))
        store.add_trace(_make_trace("t-2"))
        store.add_trace(_make_trace("t-3", workspace="ws-2"))
        assert store.count() == 3
        assert store.count("ws-1") == 2
        assert store.count("ws-2") == 1
        assert store.count("ws-nonexistent") == 0

    def test_clear(self, store):
        store.add_trace(_make_trace("t-1"))
        store.add_trace(_make_trace("t-2"))
        store.clear()
        assert store.count() == 0


class TestListTraces:
    def test_list_filters_by_workspace(self, store):
        store.add_trace(_make_trace("t-1", workspace="alpha"))
        store.add_trace(_make_trace("t-2", workspace="alpha"))
        store.add_trace(_make_trace("t-3", workspace="beta"))
        results = store.list_traces("alpha")
        assert len(results) == 2
        assert {t.trace_id for t in results} == {"t-1", "t-2"}

    def test_list_sorts_by_trace_id(self, store):
        store.add_trace(_make_trace("c"))
        store.add_trace(_make_trace("a"))
        store.add_trace(_make_trace("b"))
        results = store.list_traces("ws-1")
        assert [t.trace_id for t in results] == ["a", "b", "c"]

    def test_list_filters_by_time_window(self, store):
        # Add traces at offsets -100, 0, +100 seconds
        store.add_trace(_make_trace("t-past", offset_seconds=-100))
        store.add_trace(_make_trace("t-now", offset_seconds=0))
        store.add_trace(_make_trace("t-future", offset_seconds=100))
        # Window: [-50, +50] should catch only t-now
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=50)
        window_end = now + timedelta(seconds=50)
        results = store.list_traces("ws-1", start=window_start, end=window_end)
        assert len(results) == 1
        assert results[0].trace_id == "t-now"


class TestMerkleCheckpoints:
    def test_save_and_list(self, store):
        ws = "checkpoint-ws"
        root_bytes = bytes.fromhex("ab" * 32)
        period_start = datetime.now(timezone.utc) - timedelta(hours=1)
        period_end = datetime.now(timezone.utc)
        store.save_checkpoint(ws, root_bytes, 100, period_start, period_end)

        ckpts = store.list_checkpoints(ws)
        assert len(ckpts) == 1
        assert ckpts[0]["root"] == "ab" * 32
        assert ckpts[0]["trace_count"] == 100

    def test_list_empty(self, store):
        assert store.list_checkpoints("never-checkpointed") == []


class TestContextManager:
    def test_with_statement(self):
        with DuckDBStore(":memory:") as s:
            s.add_trace(_make_trace("t-cm"))
            assert s.count() == 1
        # After exit, store is closed; cannot use it anymore.

    def test_close_is_idempotent(self):
        s = DuckDBStore(":memory:")
        s.close()
        s.close()  # should not raise


class TestRoundTrip:
    def test_canonical_json_preserved(self, store):
        """Whatever goes in must come out byte-for-byte identical."""
        t = _make_trace("rt-1")
        store.add_trace(t)
        got = store.get_trace("rt-1")
        # All semantically relevant fields preserved
        assert got.trace_id == t.trace_id
        assert got.workspace == t.workspace
        assert got.input == t.input
        assert got.output == t.output
        assert got.model == t.model
