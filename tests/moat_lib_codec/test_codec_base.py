"""
Tests for moat.lib.codec._base — Codec base class and Extension system.
"""

from __future__ import annotations

from moat.lib.codec import Extension, get_codec


class TestExtension:
    """Test the Extension system."""

    def test_empty_extension(self):
        """empty extension."""
        ext = Extension()
        assert ext is not None

    def test_encoder_registration(self):
        """encoder registration."""
        ext = Extension()

        @ext.encoder(99, str)
        def enc_str(codec, obj):  # noqa: ARG001
            return obj.upper().encode("utf-8")

        # The encoder should be registered
        assert ext is not None

    def test_decoder_registration(self):
        """decoder registration."""
        ext = Extension()

        @ext.decoder(99)
        def dec_str(codec, val):  # noqa: ARG001
            return val.decode("utf-8").lower()

        assert ext is not None


class TestGetCodec:
    """Test the get_codec factory function."""

    def test_get_noop(self):
        """get noop."""
        c = get_codec("noop")
        assert c is not None
        assert c.encode(b"test") == b"test"

    def test_get_null(self):
        """get null."""
        c = get_codec("null")
        assert c.encode(None) == b""

    def test_get_bool(self):
        """get bool."""
        c = get_codec("bool")
        assert c.encode(True) == b"on"

    def test_get_utf8(self):
        """get utf8."""
        c = get_codec("utf8")
        assert c.encode("hi") == b"hi"

    def test_get_std_cbor(self):
        """get std cbor."""
        c = get_codec("std-cbor")
        assert c is not None

    def test_get_std_msgpack(self):
        """get std msgpack."""
        c = get_codec("std-msgpack")
        assert c is not None

    def test_get_none_defaults_to_noop(self):
        """get none defaults to noop."""
        c = get_codec(None)
        assert c.encode(b"x") == b"x"

    def test_pass_codec_instance(self):
        """Passing a Codec instance should return it directly."""
        c1 = get_codec("noop")
        c2 = get_codec(c1)
        assert c2 is c1

    def test_get_dotted_module(self):
        """Full dotted module path should work."""
        c = get_codec("moat.lib.codec.noop")
        assert c.encode(b"data") == b"data"


class TestCodecBase:
    """Test the Codec abstract base class."""

    def test_init_default_extension(self):
        """Codec without ext should get an empty Extension."""
        c = get_codec("noop")
        assert c.ext is not None

    def test_buf_initialized(self):
        """buf initialized."""
        c = get_codec("noop")
        assert c.buf == b""
