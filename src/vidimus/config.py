"""Global configuration for the Vidimus runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vidimus.storage.memory import InMemoryStore


@dataclass
class VidimusConfig:
    """Runtime configuration for a Vidimus workspace.

    Attributes:
        workspace: Logical workspace identifier. Used to scope traces and
            attestations. Required.
        judges: List of LLM judge identifiers for evaluation. Default is a
            heuristic stub judge until real LLM judges are configured.
        store: Storage backend instance. Default is in-memory; swap for
            DuckDB in production.
        home_dir: Path where keys and runtime state live. Default ``~/.vidimus``.
    """

    workspace: str = "default"
    judges: list[str] = field(default_factory=lambda: ["stub"])
    store: Any = None  # late-bound to allow swappable backends
    home_dir: Path = field(default_factory=lambda: Path.home() / ".vidimus")

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = InMemoryStore()
        self.home_dir.mkdir(parents=True, exist_ok=True)


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
        store: Trace storage backend. Defaults to in-memory.
        home_dir: Directory for keys and runtime state. Defaults to ``~/.vidimus``.

    Returns:
        The active VidimusConfig.
    """
    global _CONFIG
    _CONFIG = VidimusConfig(
        workspace=workspace,
        judges=judges or ["stub"],
        store=store,
        home_dir=Path(home_dir) if home_dir else Path.home() / ".vidimus",
    )
    return _CONFIG


def get_config() -> VidimusConfig:
    """Return the active config, initializing with defaults if needed."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = VidimusConfig()
    return _CONFIG


def reset_config() -> None:
    """Reset the global config. Primarily for tests."""
    global _CONFIG
    _CONFIG = None
