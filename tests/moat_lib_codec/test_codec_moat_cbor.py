"""
Tests for moat.lib.codec.moat_cbor — MoaT-standard CBOR codec with extensions.
"""

from __future__ import annotations

import pytest

import cbor2

from moat.util import NotGiven
from moat.lib.codec import get_codec


class TestMoatCBORCodec:
    """Test the 'std-cbor' codec (MoaT-standard CBOR with extensions)."""

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, [1, 2, 3], {"a": 1, "b": 2}],
    )
    def test_round_trip(self, obj):
        """round trip."""
        c = get_codec("std-cbor")
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_not_given_encoding(self):
        """NotGiven (Ellipsis) should encode to CBOR null (0xF7)."""
        c = get_codec("std-cbor")
        assert c.encode(NotGiven) == b"\xf7"
        assert c.decode(b"\xf7") is NotGiven

    def test_empty_bytes_decode(self):
        """Empty bytes should decode to NotGiven."""
        c = get_codec("std-cbor")
        assert c.decode(b"") is NotGiven

    def test_compatible_with_cbor2(self):
        """Encoded output should be decodable by cbor2 directly."""
        c = get_codec("std-cbor")
        encoded = c.encode({"x": 1, "y": "two"})
        assert cbor2.loads(encoded) == {"x": 1, "y": "two"}

    def test_nested_structures(self):
        """nested structures."""
        c = get_codec("std-cbor")
        obj = {"list": [1, [2, 3]], "dict": {"nested": {"deep": True}}}
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_unicode_strings(self):
        """unicode strings."""
        c = get_codec("std-cbor")
        obj = "Hëllo, 世界 🌍"
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_large_numbers(self):
        """large numbers."""
        c = get_codec("std-cbor")
        for n in [0, 1, -1, 255, 256, -256, 65535, 65536, 2**32, -(2**32)]:
            assert c.decode(c.encode(n)) == n

    def test_float_values(self):
        """float values."""
        c = get_codec("std-cbor")
        for f in [0.0, 1.5, -3.14, 1e10, 1e-10]:
            assert c.decode(c.encode(f)) == f
