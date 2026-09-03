"""
Tests for moat.lib.codec.moat_kv — legacy alias for moat_msgpack.
"""

from __future__ import annotations

import pytest

from moat.lib.codec import get_codec
from moat.lib.codec.moat_kv import Codec as MoatKVCodec


class TestMoatKVCodec:
    """Test the 'moat-kv' codec (legacy alias for moat-msgpack)."""

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, None, [1, 2, 3], {"a": 1, "b": 2}],
    )
    def test_round_trip_via_std_kv(self, obj):
        """round trip via std kv."""
        c = get_codec("std-kv")
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, None, [1, 2, 3], {"a": 1, "b": 2}],
    )
    def test_round_trip_direct_import(self, obj):
        """round trip direct import."""
        c = MoatKVCodec()
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_alias_for_moat_msgpack(self):
        """moat-kv should produce the same encoding as moat-msgpack."""
        c_kv = MoatKVCodec()
        c_mp = get_codec("std-msgpack")
        obj = {"key": "value", "num": 42}
        assert c_kv.encode(obj) == c_mp.encode(obj)

    def test_std_kv_is_same_as_std_msgpack(self):
        """std-kv and std-msgpack should be the same codec."""
        c_kv = get_codec("std-kv")
        c_mp = get_codec("std-msgpack")
        obj = [1, "two", 3.0]
        assert c_kv.encode(obj) == c_mp.encode(obj)
        assert c_kv.decode(c_kv.encode(obj)) == c_mp.decode(c_mp.encode(obj))

    def test_binary_data(self):
        """binary data."""
        c = MoatKVCodec()
        obj = b"\x00\x01\x02\xff"
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj
