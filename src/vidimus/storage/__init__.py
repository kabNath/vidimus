"""Storage backends for Vidimus traces.

Two backends ship today:
  - ``InMemoryStore``: zero-config, fast, ephemeral (lost on restart).
  - ``DuckDBStore``: persistent, SQL-queryable, single file on disk.

Both expose the same interface so they are drop-in interchangeable.
"""

from vidimus.storage.memory import InMemoryStore

try:
    from vidimus.storage.duckdb_store import DuckDBStore  # noqa: F401

    _has_duckdb = True
except ImportError:
    _has_duckdb = False

__all__ = ["InMemoryStore"]
if _has_duckdb:
    __all__.append("DuckDBStore")
