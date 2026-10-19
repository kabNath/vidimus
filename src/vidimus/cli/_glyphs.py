"""Terminal-encoding fallback for the CLI's non-ASCII glyphs.

Windows consoles and CI runners often use a legacy code page (e.g. cp1252) for
``sys.stdout``. Printing a check mark or an ellipsis there raises
``UnicodeEncodeError``. Every glyph the CLI emits is routed through :func:`safe`,
which leaves text untouched when the stream is UTF-8 and falls back to ASCII
otherwise.
"""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console

_ASCII_FALLBACK = {
    "✓": "OK",  # check mark
    "✗": "FAIL",  # ballot x
    "⚠": "WARN",  # warning sign
    "…": "...",  # ellipsis
    "→": "->",  # right arrow
    "–": "-",  # en dash
    "—": "-",  # em dash
    "κ": "kappa",  # Greek kappa
    "α": "alpha",  # Greek alpha
}


def stdout_is_utf8() -> bool:
    enc = getattr(sys.stdout, "encoding", None) or ""
    return enc.replace("_", "-").lower() in ("utf-8", "utf8")


def safe(text: str) -> str:
    """Return ``text`` with known glyphs replaced by ASCII if stdout is not UTF-8."""
    if stdout_is_utf8():
        return text
    for glyph, repl in _ASCII_FALLBACK.items():
        text = text.replace(glyph, repl)
    # Anything else (user data such as paths) must never crash the printer.
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    return text.encode(enc, errors="replace").decode(enc, errors="replace")


class SafeConsole(Console):
    """A rich ``Console`` that applies :func:`safe` to every string it renders.

    ``Console.print`` and ``Table`` cells both turn ``str`` into renderables via
    ``render_str``, so overriding that one method covers all output.
    """

    def render_str(self, text: str, *args: Any, **kwargs: Any) -> Any:
        return super().render_str(safe(text), *args, **kwargs)
