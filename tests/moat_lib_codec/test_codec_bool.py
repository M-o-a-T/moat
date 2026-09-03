"""
Tests for moat.lib.codec.bool — boolean text codec.
"""

from __future__ import annotations

import pytest

from moat.lib.codec.bool import Codec


class TestBoolCodecBasic:
    """Test basic encode/decode of the bool codec."""

    def test_encode_true(self):
        """encode true."""
        c = Codec()
        assert c.encode(True) == b"on"

    def test_encode_false(self):
        """encode false."""
        c = Codec()
        assert c.encode(False) == b"off"

    def test_decode_on(self):
        """decode on."""
        c = Codec()
        assert c.decode(b"on") is True

    def test_decode_off(self):
        """decode off."""
        c = Codec()
        assert c.decode(b"off") is False

    def test_encode_one_is_true(self):
        """Integer 1 should encode as 'on'."""
        c = Codec()
        assert c.encode(1) == b"on"

    def test_encode_zero_is_false(self):
        """Integer 0 should encode as 'off'."""
        c = Codec()
        assert c.encode(0) == b"off"


class TestBoolCodecCustom:
    """Test with custom on/off/null strings."""

    def test_custom_on_off(self):
        """custom on off."""
        c = Codec(on="YES", off="NO")
        assert c.encode(True) == b"YES"
        assert c.encode(False) == b"NO"
        assert c.decode(b"YES") is True
        assert c.decode(b"NO") is False

    def test_custom_null(self):
        """With null set, None should encode to the null string."""
        c = Codec(null="null")
        assert c.encode(None) == b"null"
        assert c.decode(b"null") is None

    def test_no_null_encoding_none_raises(self):
        """Without null set, encoding None should raise."""
        c = Codec()
        with pytest.raises(ValueError):  # noqa: PT011
            c.encode(None)


class TestBoolCodecErrors:
    """Test error handling."""

    def test_encode_invalid_value(self):
        """encode invalid value."""
        c = Codec()
        with pytest.raises(ValueError):  # noqa: PT011
            c.encode(42)

    def test_decode_invalid_data(self):
        """decode invalid data."""
        c = Codec()
        with pytest.raises(ValueError):  # noqa: PT011
            c.decode(b"maybe")

    def test_decode_invalid_with_null(self):
        """Even with null set, unknown data should raise."""
        c = Codec(null="null")
        with pytest.raises(ValueError):  # noqa: PT011
            c.decode(b"unknown")


class TestBoolCodecRoundTrip:
    """Test round-trip encode/decode."""

    @pytest.mark.parametrize("value", [True, False])
    def test_round_trip(self, value):
        """round trip."""
        c = Codec()
        encoded = c.encode(value)
        decoded = c.decode(encoded)
        assert decoded is value

    def test_round_trip_with_null(self):
        """round trip with null."""
        c = Codec(null="null")
        assert c.decode(c.encode(None)) is None
        assert c.decode(c.encode(True)) is True
        assert c.decode(c.encode(False)) is False
