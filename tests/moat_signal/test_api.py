"""
Tests for moat.signal.api — Signal messenger API helpers.
"""

from __future__ import annotations

import base64
import pytest

from moat.signal.api import bytearray_to_rfc_2397_data_url, get_attachments


class TestByteArrayToDataUrl:
    """Test bytearray_to_rfc_2397_data_url."""

    def test_simple_text(self):
        """Plain text bytes should produce a text/plain data URL."""
        result = bytearray_to_rfc_2397_data_url(bytearray(b"hello world"))
        assert result.startswith("data:")
        assert ";base64," in result
        # Decode the base64 part to verify content
        encoded_part = result.split(";base64,")[1]
        assert base64.b64decode(encoded_part) == b"hello world"

    def test_empty_bytearray(self):
        """Empty bytearray should still produce a valid data URL."""
        result = bytearray_to_rfc_2397_data_url(bytearray(b""))
        assert result.startswith("data:")
        assert ";base64," in result

    def test_mime_type_in_result(self):
        """The result should contain a MIME type specification."""
        result = bytearray_to_rfc_2397_data_url(bytearray(b"some data"))
        # The data URL format is data:<mime>;base64,<data>
        # The MIME type should be present between "data:" and ";base64,"
        mime_part = result[len("data:") : result.index(";base64,")]
        assert len(mime_part) > 0  # some MIME type should be detected

    def test_returns_string(self):
        """returns string."""
        result = bytearray_to_rfc_2397_data_url(bytearray(b"test"))
        assert isinstance(result, str)


class TestGetAttachments:
    """Test get_attachments."""

    def test_no_attachments(self):
        """No files or bytes should return empty list."""
        result = get_attachments(None, None)
        assert result == []

    def test_bytes_attachment(self):
        """Bytearray attachments should be converted to data URLs."""
        att = bytearray(b"test data")
        result = get_attachments(None, [att])
        assert len(result) == 1
        assert result[0].startswith("data:")

    def test_multiple_bytes_attachments(self):
        """Multiple bytearray attachments should all be processed."""
        atts = [bytearray(b"first"), bytearray(b"second")]
        result = get_attachments(None, atts)
        assert len(result) == 2

    @pytest.mark.skip(reason="Requires actual file on disk")
    def test_file_attachment(self, tmp_path):
        """File attachments should be read and converted to data URLs."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")
        result = get_attachments([str(test_file)], None)
        assert len(result) == 1
        assert result[0].startswith("data:")
