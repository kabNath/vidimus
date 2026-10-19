"""Shared test setup.

The library defaults to a persistent DuckDB store under ``~/.vidimus``; the suite
forces the in-memory store so ordinary tests never touch the user's home.
Tests that exercise persistence opt back in with ``monkeypatch.delenv("VIDIMUS_STORE")``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _memory_store_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDIMUS_STORE", "memory")
