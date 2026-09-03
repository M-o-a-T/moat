"""
Tests for moat.lib.codec.jsonvalue and moat.lib.codec.jsonvalstr codecs.
"""

from __future__ import annotations

import json
import pytest

from moat.lib.codec import get_codec


class TestJsonValueCodec:
    """Test the 'jsonvalue' codec — wraps data in a {"value": ...} envelope."""

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, None, [1, 2, 3], {"a": 1, "b": 2}],
    )
    def test_round_trip(self, obj):
        """round trip."""
        c = get_codec("jsonvalue")
        encoded = c.encode(obj)
        # Encoded should be JSON with a "value" key
        decoded_json = json.loads(encoded)
        assert "value" in decoded_json
        assert decoded_json["value"] == obj
        # Decode should extract the value
        assert c.decode(encoded) == obj

    def test_encode_structure(self):
        """encode structure."""
        c = get_codec("jsonvalue")
        encoded = c.encode(42)
        assert json.loads(encoded) == {"value": 42}

    def test_decode_extracts_value(self):
        """decode extracts value."""
        c = get_codec("jsonvalue")
        data = json.dumps({"value": "test"}).encode("utf-8")
        assert c.decode(data) == "test"

    def test_ext_raises(self):
        """ext raises."""
        with pytest.raises(ValueError):  # noqa: PT011
            get_codec("jsonvalue", ext=object())


class TestJsonValStrCodec:
    """Test the 'jsonvalstr' codec — stringified element inside a value envelope."""

    @pytest.mark.parametrize(
        "obj",
        [42, "hello", True, False, None, [1, 2, "three"], {"a": 1, "b": "two"}],
    )
    def test_round_trip(self, obj):
        """round trip."""
        c = get_codec("jsonvalstr")
        encoded = c.encode(obj)
        # Should be able to decode back
        assert c.decode(encoded) == obj

    def test_encode_is_json(self):
        """encode is json."""
        c = get_codec("jsonvalstr")
        encoded = c.encode(42)
        # The outer layer is JSON with {"value": ...}
        outer = json.loads(encoded)
        assert "value" in outer

    def test_nested_objects(self):
        """nested objects."""
        c = get_codec("jsonvalstr")
        obj = {"nested": {"deep": [1, 2, {"x": "y"}]}}
        encoded = c.encode(obj)
        assert c.decode(encoded) == obj

    def test_ext_raises(self):
        """ext raises."""
        with pytest.raises(ValueError):  # noqa: PT011
            get_codec("jsonvalstr", ext=object())
