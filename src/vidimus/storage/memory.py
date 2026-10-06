"""In-memory trace storage.

Default storage backend for v0.1. Suitable for development, tests, and
small (< 1M traces) production workloads. For persistence and scale,
v0.2 will ship a DuckDB backend with the same interface.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock

from vidimus.audit.schemas import Trace


class InMemoryStore:
    """Thread-safe in-memory trace store.

    Traces are kept in a flat list keyed by ``trace_id`` and indexed by
    workspace and timestamp for query filtering.
    """

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}
        self._lock = RLock()

    def add_trace(self, trace: Trace) -> None:
        with self._lock:
            self._traces[trace.trace_id] = trace

    def get_trace(self, trace_id: str) -> Trace | None:
        with self._lock:
            return self._traces.get(trace_id)

    def list_traces(
        self,
        workspace: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Trace]:
        """Return all traces in the given workspace and time window.

        Returned traces are sorted by ``trace_id`` for deterministic Merkle
        construction.
        """
        with self._lock:
            out: list[Trace] = []
            for t in self._traces.values():
                if t.workspace != workspace:
                    continue
                if start is not None and t.captured_at < start:
                    continue
                if end is not None and t.captured_at > end:
                    continue
                out.append(t)
            out.sort(key=lambda t: t.trace_id)
            return out

    def count(self, workspace: str | None = None) -> int:
        with self._lock:
            if workspace is None:
                return len(self._traces)
            return sum(1 for t in self._traces.values() if t.workspace == workspace)

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
