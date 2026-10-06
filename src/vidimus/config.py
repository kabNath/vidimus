"""Global configuration for the Vidimus runtime."""

from __future__ import annotations

import contextlib
import json
import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vidimus.storage.memory import InMemoryStore

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def default_home_dir() -> Path:
    """``$VIDIMUS_HOME`` if set, else ``~/.vidimus``."""
    env = os.environ.get("VIDIMUS_HOME")
    return Path(env) if env else Path.home() / ".vidimus"


def store_path(home_dir: Path, workspace: str) -> Path:
    """Location of a workspace's DuckDB file: ``<home>/workspaces/<workspace>/traces.duckdb``."""
    if not _WORKSPACE_RE.match(workspace):
        raise ValueError(
            f"invalid workspace name {workspace!r}: use letters, digits, '.', '_' or '-'"
        )
    return home_dir / "workspaces" / workspace / "traces.duckdb"


def _build_store(kind: str | None, home_dir: Path, workspace: str) -> Any:
    """Create a store from ``"memory"`` / ``"duckdb"`` / ``None`` (=env, else DuckDB)."""
    kind = kind or os.environ.get("VIDIMUS_STORE") or "duckdb"
    if kind == "memory":
        return InMemoryStore()
    if kind != "duckdb":
        raise ValueError(f"unknown store {kind!r}; expected 'memory' or 'duckdb'")
    try:
        from vidimus.storage.duckdb_store import DuckDBStore
    except ImportError:
        warnings.warn(
            "duckdb is not installed: traces are kept in memory and lost when this process "
            "exits, and the CLI cannot see them. Reinstall vidimus (duckdb is a core dependency).",
            RuntimeWarning,
            stacklevel=3,
        )
        return InMemoryStore()
    path = store_path(home_dir, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    return DuckDBStore(path)


@dataclass
class VidimusConfig:
    """Runtime configuration for a Vidimus workspace.

    Attributes:
        workspace: Logical workspace identifier. Used to scope traces and
            attestations. Required.
        judges: List of LLM judge identifiers for evaluation. Default is a
            heuristic stub judge until real LLM judges are configured.
        store: Storage backend instance. Default is a persistent DuckDB file in
            the workspace directory; pass ``"memory"`` (or an ``InMemoryStore``)
            for an ephemeral store, e.g. in tests.
        home_dir: Path where keys and runtime state live. Default ``~/.vidimus``
            (or ``$VIDIMUS_HOME``).
    """

    workspace: str = "default"
    judges: list[str] = field(default_factory=lambda: ["stub"])
    store: Any = None  # late-bound to allow swappable backends
    home_dir: Path = field(default_factory=default_home_dir)

    def __post_init__(self) -> None:
        self.home_dir.mkdir(parents=True, exist_ok=True)
        self._owns_store = self.store is None or isinstance(self.store, str)
        if self.store is None or isinstance(self.store, str):
            self.store = _build_store(self.store, self.home_dir, self.workspace)


# Module-level singleton. Mutated by init().
_CONFIG: VidimusConfig | None = None


def init(
    workspace: str = "default",
    judges: list[str] | None = None,
    store: Any = None,
    home_dir: Path | str | None = None,
) -> VidimusConfig:
    """Initialize the Vidimus runtime for this process.

    Args:
        workspace: Workspace name scoping traces and attestations.
        judges: LLM judge identifiers. Defaults to a heuristic stub judge.
        store: ``"memory"``, ``"duckdb"``, a store instance, or ``None`` for the
            default (a DuckDB file per workspace, unless ``$VIDIMUS_STORE=memory``).
            Existing data in the DuckDB file is kept.
        home_dir: Directory for keys and runtime state. Defaults to ``~/.vidimus``.

    Returns:
        The active VidimusConfig.
    """
    global _CONFIG
    _close_owned_store()
    _CONFIG = VidimusConfig(
        workspace=workspace,
        judges=judges or ["stub"],
        store=store,
        home_dir=Path(home_dir) if home_dir else default_home_dir(),
    )
    return _CONFIG


def get_config() -> VidimusConfig:
    """Return the active config, initializing with defaults if needed."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = VidimusConfig()
    return _CONFIG


def is_initialized() -> bool:
    return _CONFIG is not None


def _close_owned_store() -> None:
    if _CONFIG is not None and getattr(_CONFIG, "_owns_store", False):
        close = getattr(_CONFIG.store, "close", None)
        if close:
            close()


def reset_config() -> None:
    """Reset the global config (closing a store this module opened). Primarily for tests."""
    global _CONFIG
    _close_owned_store()
    _CONFIG = None


# --- Settings shared between terminals ----------------------------------------


def settings_path(home_dir: Path) -> Path:
    return home_dir / "config.json"


def save_settings(home_dir: Path, workspace: str, judges: list[str] | None = None) -> None:
    """Remember the workspace chosen by ``vidimus init`` so later CLI calls use it."""
    home_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"workspace": workspace}
    if judges:
        data["judges"] = judges
    settings_path(home_dir).write_text(json.dumps(data, indent=2) + "\n")


def init_from_saved_settings() -> VidimusConfig:
    """Initialize from ``$VIDIMUS_WORKSPACE`` / the settings written by ``vidimus init``."""
    home = default_home_dir()
    saved: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        saved = json.loads(settings_path(home).read_text())
    workspace = os.environ.get("VIDIMUS_WORKSPACE") or saved.get("workspace") or "default"
    return init(workspace=workspace, judges=saved.get("judges"), home_dir=home)
