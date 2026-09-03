"""
Tests for moat.lib.codec.moat_msgpack — MoaT-standard MsgPack codec with extensions.
"""

from __future__ import annotations

import pytest

from moat.lib.codec import get_codec


class TestMoatMsgpackCodec:
    """Test the 'std-msgpack' codec (MoaT-standard MsgPack with extensions)."""

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, None, [1, 2, 3], {"a": 1, "b": 2}],
    )
    def test_round_trip(self, obj):
        """round trip."""
        c = get_codec("std-msgpack")
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_nested_structures(self):
        """nested structures."""
        c = get_codec("std-msgpack")
        obj = {"list": [1, [2, 3]], "dict": {"nested": {"deep": True}}}
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_unicode_strings(self):
        """unicode strings."""
        c = get_codec("std-msgpack")
        obj = "Hëllo, 世界 🌍"
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_large_numbers(self):
        """large numbers."""
        c = get_codec("std-msgpack")
        for n in [0, 1, -1, 255, 256, -256, 65535, 65536, 2**32, -(2**32)]:
            assert c.decode(c.encode(n)) == n

    def test_float_values(self):
        """float values."""
        c = get_codec("std-msgpack")
        for f in [0.0, 1.5, -3.14, 1e10, 1e-10]:
            result = c.decode(c.encode(f))
            assert result == pytest.approx(f, rel=1e-5)

    def test_binary_data(self):
        """binary data."""
        c = get_codec("std-msgpack")
        obj = b"\x00\x01\x02\xff"
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_empty_dict(self):
        """empty dict."""
        c = get_codec("std-msgpack")
        assert c.decode(c.encode({})) == {}

    def test_empty_list(self):
        """empty list."""
        c = get_codec("std-msgpack")
        assert c.decode(c.encode([])) == []
