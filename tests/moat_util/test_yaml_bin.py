"""Tests for the !bin / !bina / !hex YAML tag handling."""

from __future__ import annotations

import io

from moat.lib.path import Path
from moat.util.yaml import yformat, yload, yprint


class TestBinaEncoding:
    """Verify !bina encoding for bytestrings with few non-printable bytes."""

    def _roundtrip(self, data: bytes) -> bytes:
        buf = io.StringIO()
        yprint({"key": data}, stream=buf, compact=True)
        loaded = yload(buf.getvalue())
        return loaded["key"]

    def _tags(self, data: bytes) -> str:
        """Return the YAML tag used for *data*."""
        buf = io.StringIO()
        yprint({"key": data}, stream=buf, compact=True)
        text = buf.getvalue()
        for line in text.splitlines():
            for token in line.split():
                if token.startswith("!"):
                    return token.lstrip("!")
        return "binary"

    # --- UTF-8 path still uses !bin ---

    def test_utf8_uses_bin_tag(self):
        """ASCII / UTF-8 data should be tagged !bin."""
        assert self._tags(b"hello world") == "bin"
        assert self._tags("café".encode("utf-8")) == "bin"

    def test_utf8_roundtrip(self):
        """UTF-8 data round-trips correctly."""
        assert self._roundtrip(b"hello world") == b"hello world"

    # --- !bina encoding ---

    def test_few_nonprintable_uses_bina(self):
        """1 non-printable byte in 20 → 5 % → !bina."""
        data = b"hello world testing\x80"
        assert self._tags(data) == "bina"
        assert self._roundtrip(data) == data

    def test_bina_preserves_printable(self):
        """Printable ASCII is preserved verbatim in !bina output."""
        data = b"abc\x81def\x82ghi"
        assert self._roundtrip(data) == data

    def test_bina_escapes_all_non_printable_types(self):
        """NUL, ESC, and DEL are all escaped."""
        data = b"\x00\x1b\x7f"
        assert self._roundtrip(data) == data

    def test_bina_newlines_and_tabs_preserved(self):
        r"""Newlines and tabs are printable and not escaped."""
        data = b"line1\nline2\ttab"
        assert self._roundtrip(data) == data

    def test_boundary_9_percent(self):
        """9 % non-printable → !bina."""
        data = bytearray(b"a" * 100)
        for i in range(9):
            data[i] = 0x80
        assert self._tags(bytes(data)) == "bina"
        assert self._roundtrip(bytes(data)) == bytes(data)

    def test_boundary_10_percent(self):
        """Exactly 10 % non-printable → !binary (>= 33 bytes)."""
        data = bytearray(b"a" * 100)
        for i in range(10):
            data[i] = 0x80
        assert self._tags(bytes(data)) == "binary"

    def test_boundary_11_percent(self):
        """11 % non-printable → !binary (>= 33 bytes)."""
        data = bytearray(b"a" * 100)
        for i in range(11):
            data[i] = 0x80
        assert self._tags(bytes(data)) == "binary"

    # --- Small length threshold behaviour ---
    # These use \x80 (non-UTF-8) to trigger the non-UTF-8 path.

    def _bina_threshold_len(self, length: int) -> str:
        """Return the tag used for *length* printable bytes with one \x80."""
        return self._tags(b"\x80" + b"a" * (length - 1))

    def test_1_byte(self):
        """1 byte: threshold=1, nonprintable=1, 1<1 False → hex."""
        assert self._bina_threshold_len(1) == "hex"

    def test_3_bytes(self):
        """3 bytes: threshold=1, nonprintable=1, 1<1 False → hex."""
        assert self._bina_threshold_len(3) == "hex"

    def test_19_bytes(self):
        """19 bytes: threshold=1, nonprintable=1, 1<1 False → hex."""
        assert self._bina_threshold_len(19) == "hex"

    def test_20_bytes(self):
        """20 bytes: threshold=2, nonprintable=1, 1<2 True → bina."""
        assert self._bina_threshold_len(20) == "bina"
        assert self._roundtrip(b"\x80" + b"a" * 19) == b"\x80" + b"a" * 19

    # --- long data fallback ---

    def test_long_non_printable_falls_back_to_binary(self):
        """33+ bytes with ≥ 10 % non-printable → !binary."""
        data = bytearray(b"a" * 40)
        for i in range(5):  # 12.5 % non-printable
            data[i] = 0x80
        assert self._tags(bytes(data)) == "binary"

    def test_long_all_printable_non_utf8(self):
        """33+ bytes, < 10 % non-printable → !bina."""
        data = bytearray(b"a" * 40)
        data[0] = 0x80  # 1/40 = 2.5 %
        assert self._tags(bytes(data)) == "bina"
        assert self._roundtrip(bytes(data)) == bytes(data)

    # --- bytearray and memoryview ---

    def test_bytearray_uses_bina(self):
        """bytearray with few non-printable uses !bina."""
        data = bytearray(b"hello world testing\x80")
        assert self._tags(data) == "bina"
        assert self._roundtrip(data) == bytes(data)

    def test_memoryview_uses_bina(self):
        """memoryview with few non-printable uses !bina."""
        data = memoryview(b"hello world testing\x80")
        assert self._tags(data) == "bina"
        assert self._roundtrip(bytes(data)) == bytes(data)

    # --- !bina literal parsing ---

    def test_bina_literal_parse(self):
        """!bina tagged YAML values parse correctly."""
        text = "!bina hello\\x80world\n"
        result = yload(text)
        assert result == b"hello\x80world"

    def test_bina_multiple_escapes(self):
        """Multiple \\x escapes in a !bina value."""
        text = "!bina \\x81ab\\x82cd\n"
        result = yload(text)
        assert result == b"\x81ab\x82cd"

    def test_bina_no_escapes(self):
        """!bina with no escape sequences."""
        text = "!bina abcdef\n"
        result = yload(text)
        assert result == b"abcdef"

    # --- backslash handling ---

    def test_bina_literal_backslash_roundtrip(self):
        """A literal backslash round-trips through !bina."""
        # 20 bytes so the non-printable byte stays under 10 %.
        data = b"path\\to\\file padding\x80"
        assert self._tags(data) == "bina"
        assert self._roundtrip(data) == data

    def test_bina_doubles_backslash_on_encode(self):
        """Literal backslashes are doubled in the !bina scalar."""
        data = b"a\\b padding padding pad\x80"
        buf = io.StringIO()
        yprint({"key": data}, stream=buf, compact=True)
        assert "a\\\\b" in buf.getvalue()

    def test_bina_backslash_before_hex_escape(self):
        """A literal ``\\x61`` in the data is not confused with an escape."""
        # Without doubling, the trailing 0x80 would force !bina and the
        # literal ``\x61`` could be mis-decoded as byte 0x61.
        data = b"prefix\\x61 padding tail\x80"
        assert self._tags(data) == "bina"
        assert self._roundtrip(data) == data

    def test_bina_only_backslashes(self):
        """Consecutive backslashes round-trip correctly."""
        data = b"\\\\\\ padding padding pad\x80"
        assert self._roundtrip(data) == data

    def test_bina_decode_doubled_backslash(self):
        """A ``\\\\`` in a !bina scalar decodes to one backslash."""
        text = "!bina a\\\\b\n"
        assert yload(text) == b"a\\b"


class TestYformatWithBin:
    """Ensure yformat works with binary data."""

    def test_format_bin(self):
        """Verify !bin is used for plain ASCII bytes."""
        text = yformat({"key": b"hello world"})
        assert "!bin" in text

    def test_format_bina(self):
        """Verify !bina is used for non-UTF-8 with < 10 % non-printable."""
        # Non-UTF-8 bytes with < 10 % non-printable → !bina
        # Need >= 20 bytes so threshold >= 2 with 1 non-printable
        text = yformat({"key": b"hello world testing\x80"})
        assert "!bina" in text

    def test_format_hex(self):
        """Verify !hex is used for non-UTF-8 with ≥ 10 % non-printable."""
        # Non-UTF-8 bytes with ≥ 10 % non-printable → !hex
        text = yformat({"key": b"hello \x80\x81\x82"})
        assert "!hex" in text


class TestPathTag:
    """Verify !P tag still works alongside bin tags."""

    def test_path_and_bin_together(self):
        """Verify !P tag still works alongside bin tags."""
        data = {"path": Path("/moat/test_path"), "blob": b"\x80abc"}
        text = yformat(data)
        loaded = yload(text)
        assert isinstance(loaded["path"], Path)
        assert loaded["blob"] == b"\x80abc"
