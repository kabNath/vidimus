"""Tests for canonical JSON serialization (RFC 8785)."""

from __future__ import annotations

import pytest

from vidimus.audit.canonical import CanonicalizationError, canonicalize


class TestPrimitives:
    def test_null(self) -> None:
        assert canonicalize(None) == b"null"

    def test_true(self) -> None:
        assert canonicalize(True) == b"true"

    def test_false(self) -> None:
        assert canonicalize(False) == b"false"

    def test_integer(self) -> None:
        assert canonicalize(0) == b"0"
        assert canonicalize(42) == b"42"
        assert canonicalize(-7) == b"-7"

    def test_float_integer_value(self) -> None:
        # 1.0 should serialize as "1" per ES6 numeric stringification.
        assert canonicalize(1.0) == b"1"
        assert canonicalize(-3.0) == b"-3"

    def test_float_fractional(self) -> None:
        # Just check it round-trips; exact form is implementation-specific
        # but deterministic.
        out = canonicalize(0.5)
        assert out == b"0.5"

    def test_rejects_nan(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonicalize(float("nan"))

    def test_rejects_infinity(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonicalize(float("inf"))
        with pytest.raises(CanonicalizationError):
            canonicalize(float("-inf"))


class TestStrings:
    def test_simple(self) -> None:
        assert canonicalize("hello") == b'"hello"'

    def test_quote_escape(self) -> None:
        assert canonicalize('say "hi"') == b'"say \\"hi\\""'

    def test_backslash_escape(self) -> None:
        assert canonicalize("a\\b") == b'"a\\\\b"'

    def test_control_chars(self) -> None:
        assert canonicalize("\n") == b'"\\n"'
        assert canonicalize("\t") == b'"\\t"'
        assert canonicalize("\r") == b'"\\r"'

    def test_unicode_passthrough(self) -> None:
        # Per RFC 8785, non-control non-special chars pass through.
        assert canonicalize("café") == "\"café\"".encode("utf-8")


class TestArrays:
    def test_empty(self) -> None:
        assert canonicalize([]) == b"[]"

    def test_simple(self) -> None:
        assert canonicalize([1, 2, 3]) == b"[1,2,3]"

    def test_mixed(self) -> None:
        assert canonicalize([1, "two", None]) == b'[1,"two",null]'


class TestObjects:
    def test_empty(self) -> None:
        assert canonicalize({}) == b"{}"

    def test_keys_are_sorted(self) -> None:
        out = canonicalize({"b": 1, "a": 2})
        assert out == b'{"a":2,"b":1}'

    def test_nested(self) -> None:
        out = canonicalize({"outer": {"y": 2, "x": 1}})
        assert out == b'{"outer":{"x":1,"y":2}}'

    def test_unicode_key_ordering(self) -> None:
        # Code-unit ordering means basic ASCII keys come before higher.
        out = canonicalize({"z": 0, "a": 0})
        assert out == b'{"a":0,"z":0}'

    def test_rejects_nonstring_key(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonicalize({1: "x"})


class TestDeterminism:
    """The whole point of canonicalization is determinism."""

    def test_same_input_same_output(self) -> None:
        x = {"foo": [1, 2, {"bar": True, "baz": None}], "qux": "hi"}
        assert canonicalize(x) == canonicalize(x)

    def test_different_key_orders_same_output(self) -> None:
        x1 = {"a": 1, "b": 2}
        x2 = {"b": 2, "a": 1}
        assert canonicalize(x1) == canonicalize(x2)
