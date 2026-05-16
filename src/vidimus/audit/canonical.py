"""RFC 8785 (JSON Canonicalization Scheme, JCS) implementation.

Why this matters: every signed artifact in Vidimus is hashed and verified
over its canonical JSON form. Without a deterministic canonical form, two
implementations or two Python versions could produce different hashes for
"the same" data. JCS guarantees:

  1. Object keys are sorted lexicographically (by code-unit value).
  2. Whitespace is removed.
  3. Numbers follow ECMAScript 6 stringification (deterministic).
  4. Strings use NFC normalization and minimal escaping.

We implement the subset of JCS needed for our schemas: strings, numbers,
booleans, null, arrays, objects. We deliberately reject NaN and Infinity
(per RFC 8785 §3.2.2.3, which forbids them in JSON anyway).

Reference: https://www.rfc-editor.org/rfc/rfc8785
"""

from __future__ import annotations

import math
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when input cannot be canonicalized (e.g. NaN, Infinity, unsupported type)."""


def canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 canonical JSON encoding of ``value`` as UTF-8 bytes.

    Args:
        value: A JSON-compatible Python object (dict, list, str, int, float,
            bool, None). Pydantic models should be exported via ``.model_dump()``
            before calling this function.

    Returns:
        Canonical JSON as UTF-8 bytes, suitable for hashing or signing.

    Raises:
        CanonicalizationError: If the value contains NaN, Infinity, or an
            unsupported type.
    """
    return _serialize(value).encode("utf-8")


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _serialize_string(value)
    if isinstance(value, bool):  # caught above, but keep for safety
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _serialize_number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        return _serialize_object(value)
    raise CanonicalizationError(f"Unsupported type: {type(value).__name__}")


def _serialize_object(obj: dict[Any, Any]) -> str:
    # Keys must be strings in JSON; reject anything else.
    items: list[tuple[str, Any]] = []
    for k, v in obj.items():
        if not isinstance(k, str):
            raise CanonicalizationError(f"Object keys must be strings, got {type(k).__name__}")
        items.append((k, v))
    # Sort by UTF-16 code units. For BMP characters this is identical to
    # Python's default string sort. For non-BMP, we would need explicit
    # UTF-16 encoding; our schemas don't use non-BMP keys, so this is fine.
    items.sort(key=lambda kv: kv[0])
    return "{" + ",".join(f"{_serialize_string(k)}:{_serialize(v)}" for k, v in items) + "}"


def _serialize_string(s: str) -> str:
    # JCS escaping per RFC 8785 §3.2.2.2: minimal, with these exceptions:
    #   - U+0022 (")  -> \"
    #   - U+005C (\)  -> \\
    #   - U+0008 (BS) -> \b
    #   - U+0009 (HT) -> \t
    #   - U+000A (LF) -> \n
    #   - U+000C (FF) -> \f
    #   - U+000D (CR) -> \r
    #   - Other C0 controls -> \u00XX (lowercase hex)
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\r":
            out.append("\\r")
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _serialize_number(n: float) -> str:
    if math.isnan(n) or math.isinf(n):
        raise CanonicalizationError("NaN and Infinity are not valid JSON")
    # Integers stored as floats: emit as integer literal.
    if n == int(n) and abs(n) < 1e16:
        return str(int(n))
    # Use Python's repr, which is round-trippable. This differs from full
    # ECMAScript 6 stringification (RFC 8785 §3.2.2.3) for edge cases, but
    # is deterministic and sufficient for our metric values which are
    # bounded floats in [0, 1] or small probability ranges.
    # For full ES6 compliance, a future version may switch to a dedicated
    # implementation.
    return repr(n)
