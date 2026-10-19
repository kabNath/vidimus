"""duckdb is a core dependency: the default persistent store must work after a plain `pip install vidimus`."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _core_dependencies() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[(.*?)^\]", text, re.M | re.S)
    assert block
    return re.findall(r'"([^"]+)"', block.group(1))


def test_duckdb_is_a_core_dependency() -> None:
    assert any(d.startswith("duckdb") for d in _core_dependencies())


def test_duckdb_extra_still_exists_for_backwards_compatibility() -> None:
    assert re.search(
        r'^duckdb = \["duckdb', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
    )
