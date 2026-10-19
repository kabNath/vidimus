"""One version everywhere: code, packaging metadata, changelog, README badge."""

from __future__ import annotations

import re
from pathlib import Path

from vidimus import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_versions_are_aligned() -> None:
    pyproject = re.search(
        r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
    )
    changelog = re.search(
        r"^## \[([^\]]+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M
    )
    badge = re.search(
        r"badge/version-([0-9A-Za-z.]+)-", (ROOT / "README.md").read_text(encoding="utf-8")
    )
    assert pyproject and changelog and badge
    assert __version__ == pyproject.group(1) == changelog.group(1) == badge.group(1) == "0.1.0a3"
