"""DuckDB-backed persistent trace storage.

Implements the same interface as ``InMemoryStore`` but persists data to a
DuckDB database file (or ``:memory:`` for ephemeral testing). DuckDB was
chosen because it is:

  - Zero-config: no separate server process, just a Python pip install.
  - Columnar: fast aggregate queries over millions of traces.
  - SQL: any data analyst can introspect a Vidimus workspace with ``duckdb``.
  - Embeddable: ships as a single binary, no JVM, no Postgres dependency.

Requires the optional dependency:

    pip install vidimus[duckdb]

Schema:

    traces
      trace_id        VARCHAR PRIMARY KEY
      workspace       VARCHAR NOT NULL
      canonical_json  BLOB NOT NULL    -- canonical JSON for hashing
      leaf_hash       BLOB NOT NULL    -- SHA-256 of canonical_json
      captured_at     TIMESTAMP NOT NULL
      indexed_at      TIMESTAMP NOT NULL

    merkle_checkpoints
      workspace       VARCHAR NOT NULL
      root            BLOB NOT NULL
      trace_count     BIGINT NOT NULL
      period_start    TIMESTAMP NOT NULL
      period_end      TIMESTAMP NOT NULL
      issued_at       TIMESTAMP NOT NULL
      PRIMARY KEY (workspace, issued_at)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from vidimus.audit.canonical import canonicalize
from vidimus.audit.schemas import Trace

if TYPE_CHECKING:
    import duckdb  # noqa: F401


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id        VARCHAR PRIMARY KEY,
    workspace       VARCHAR NOT NULL,
    canonical_json  BLOB NOT NULL,
    leaf_hash       BLOB NOT NULL,
    captured_at     TIMESTAMP NOT NULL,
    indexed_at      TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_workspace_captured
    ON traces (workspace, captured_at);

CREATE TABLE IF NOT EXISTS merkle_checkpoints (
    workspace       VARCHAR NOT NULL,
    root            BLOB NOT NULL,
    trace_count     BIGINT NOT NULL,
    period_start    TIMESTAMP NOT NULL,
    period_end      TIMESTAMP NOT NULL,
    issued_at       TIMESTAMP NOT NULL,
    PRIMARY KEY (workspace, issued_at)
);
"""


class DuckDBStore:
    """Persistent trace store backed by DuckDB.

    Args:
        db_path: Path to the database file. Use ``:memory:`` for an ephemeral
            in-memory database (useful for tests).

    Example:
        >>> store = DuckDBStore("./vidimus.duckdb")
        >>> store.add_trace(trace)
        >>> traces = store.list_traces(workspace="acme-prod")
        >>> store.close()
    """

    def __init__(self, db_path: str | Path = "vidimus.duckdb") -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "DuckDBStore requires the 'duckdb' package. "
                "Install with: pip install vidimus[duckdb]"
            ) from exc

        self._duckdb = duckdb
        self._db_path = str(db_path)
        self._lock = RLock()
        self._conn: Any = duckdb.connect(self._db_path)
        # DuckDB needs each statement separately
        for stmt in SCHEMA_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                self._conn.execute(s)

    # ─────────────────────────────────────────────────────────────────────
    # Trace operations
    # ─────────────────────────────────────────────────────────────────────

    def add_trace(self, trace: Trace) -> None:
        """Insert (or replace) a trace."""
        canonical_bytes = canonicalize(trace.model_dump(mode="json"))
        leaf_hash = hashlib.sha256(canonical_bytes).digest()
        now = datetime.now(timezone.utc)

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO traces
                (trace_id, workspace, canonical_json, leaf_hash, captured_at, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    trace.trace_id,
                    trace.workspace,
                    canonical_bytes,
                    leaf_hash,
                    trace.captured_at,
                    now,
                ],
            )

    def get_trace(self, trace_id: str) -> Trace | None:
        """Fetch a single trace by id, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT canonical_json FROM traces WHERE trace_id = ?",
                [trace_id],
            ).fetchone()
        if row is None:
            return None
        return Trace.model_validate(json.loads(row[0].decode("utf-8")))

    def list_traces(
        self,
        workspace: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Trace]:
        """Return all traces in the workspace and optional time window.

        Sorted by ``trace_id`` for deterministic Merkle construction.
        """
        sql = "SELECT canonical_json FROM traces WHERE workspace = ?"
        params: list[Any] = [workspace]
        if start is not None:
            sql += " AND captured_at >= ?"
            params.append(start)
        if end is not None:
            sql += " AND captured_at <= ?"
            params.append(end)
        sql += " ORDER BY trace_id"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        return [Trace.model_validate(json.loads(r[0].decode("utf-8"))) for r in rows]

    def count(self, workspace: str | None = None) -> int:
        with self._lock:
            if workspace is None:
                row = self._conn.execute("SELECT COUNT(*) FROM traces").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM traces WHERE workspace = ?",
                    [workspace],
                ).fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        """Delete all data. Use with care."""
        with self._lock:
            self._conn.execute("DELETE FROM traces")
            self._conn.execute("DELETE FROM merkle_checkpoints")

    # ─────────────────────────────────────────────────────────────────────
    # Merkle checkpoint operations
    # ─────────────────────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        workspace: str,
        root: bytes,
        trace_count: int,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        """Record a Merkle root for later inclusion-proof verification."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO merkle_checkpoints
                (workspace, root, trace_count, period_start, period_end, issued_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    workspace,
                    root,
                    trace_count,
                    period_start,
                    period_end,
                    datetime.now(timezone.utc),
                ],
            )

    def list_checkpoints(self, workspace: str) -> list[dict[str, Any]]:
        """Return all checkpoints for a workspace, newest first."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT root, trace_count, period_start, period_end, issued_at
                FROM merkle_checkpoints
                WHERE workspace = ?
                ORDER BY issued_at DESC
                """,
                [workspace],
            ).fetchall()
        return [
            {
                "root": r[0].hex(),
                "trace_count": r[1],
                "period_start": r[2],
                "period_end": r[3],
                "issued_at": r[4],
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> "DuckDBStore":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
