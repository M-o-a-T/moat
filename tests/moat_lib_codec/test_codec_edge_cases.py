"""
Extended tests for moat.lib.codec.json — JSON codec edge cases.
"""

from __future__ import annotations

import pytest

from moat.lib.codec import get_codec


class TestJsonCodecEdgeCases:
    """Edge-case tests for the JSON codec beyond the basics."""

    def test_nested_deep(self):
        """nested deep."""
        c = get_codec("json")
        obj = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_special_characters_in_strings(self):
        """special characters in strings."""
        c = get_codec("json")
        obj = 'quote"backslash\\newline\ntab\t'
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_unicode_escape(self):
        """unicode escape."""
        c = get_codec("json")
        obj = "\\u0041"  # literal backslash-u-0041
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_large_number(self):
        """large number."""
        c = get_codec("json")
        obj = 2**53 - 1  # max safe integer in JSON
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_negative_float(self):
        """negative float."""
        c = get_codec("json")
        obj = -3.14159
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_empty_containers(self):
        """empty containers."""
        c = get_codec("json")
        assert c.decode(c.encode({})) == {}
        assert c.decode(c.encode([])) == []

    def test_mixed_list(self):
        """mixed list."""
        c = get_codec("json")
        obj = [1, "two", 3.0, True, None, [4, 5], {"six": 7}]
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_encode_returns_bytes(self):
        """encode returns bytes."""
        c = get_codec("json")
        encoded = c.encode({"key": "value"})
        assert isinstance(encoded, (bytes, bytearray))


class TestBinaryCodecAlias:
    """Test that the 'binary' codec is an alias for 'noop'."""

    def test_binary_is_noop(self):
        """binary is noop."""
        c = get_codec("binary")
        assert c.encode(b"test") == b"test"
        assert c.decode(b"test") == b"test"

    def test_binary_rejects_non_bytes(self):
        """binary rejects non bytes."""
        c = get_codec("binary")
        with pytest.raises(ValueError):  # noqa: PT011
            c.encode("not bytes")

    def test_binary_empty(self):
        """binary empty."""
        c = get_codec("binary")
        assert c.encode(b"") == b""
        assert c.encode(None) == b""
