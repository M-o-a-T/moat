"""
Tests for moat.lib.codec.yaml — YAML codec.

Note: The YAML codec's encode() method calls yprint() which prints to
stdout and returns None. This appears to be a pre-existing limitation
of the codec. These tests focus on what can be tested: codec creation
and decode functionality.
"""

from __future__ import annotations

from moat.lib.codec import get_codec


class TestYamlCodecCreation:
    """Test YAML codec creation and basic properties."""

    def test_create_codec(self):
        """create codec."""
        c = get_codec("yaml")
        assert c is not None

    def test_decode_yaml_dict(self):
        """Decoding a YAML string should produce the corresponding Python object."""
        c = get_codec("yaml")
        yaml_bytes = b"a: 1\nb: 2\n"
        result = c.decode(yaml_bytes)
        assert result == {"a": 1, "b": 2}

    def test_decode_yaml_list(self):
        """decode yaml list."""
        c = get_codec("yaml")
        yaml_bytes = b"- 1\n- 2\n- 3\n"
        result = c.decode(yaml_bytes)
        assert result == [1, 2, 3]

    def test_decode_yaml_nested(self):
        """decode yaml nested."""
        c = get_codec("yaml")
        yaml_bytes = b"outer:\n  inner: value\n"
        result = c.decode(yaml_bytes)
        assert result == {"outer": {"inner": "value"}}

    def test_decode_yaml_unicode(self):
        """decode yaml unicode."""
        c = get_codec("yaml")
        yaml_bytes = "name: Hëllo\n".encode("utf-8")
        result = c.decode(yaml_bytes)
        assert result == {"name": "Hëllo"}


class TestYamlCodecStream:
    """Test incremental decoding of a YAML document stream."""

    def _docs(self, data: bytes, eof: bool = True) -> list:
        c = get_codec("yaml")
        c.feed(data)
        res = list(c)
        if eof:
            c.eof()
            res.extend(c)
        return res

    def test_terminated(self):
        """Documents are returned once their "---" terminator arrives."""
        assert self._docs(b"a: 1\n---\nb: 2\n---\n", eof=False) == [{"a": 1}, {"b": 2}]

    def test_unterminated_last_held_back(self):
        """Without EOF, a trailing unterminated document stays buffered."""
        assert self._docs(b"a: 1\n---\nb: 2\n", eof=False) == [{"a": 1}]

    def test_unterminated_last_at_eof(self):
        """At EOF, a trailing unterminated document is returned."""
        assert self._docs(b"a: 1\n---\nb: 2\n") == [{"a": 1}, {"b": 2}]
        assert self._docs(b"a: 1\n---\nb: 2\n---") == [{"a": 1}, {"b": 2}]

    def test_eof_nothing_left(self):
        """EOF after a terminated stream, or on blank input, adds nothing."""
        assert self._docs(b"a: 1\n---\n") == [{"a": 1}]
        assert self._docs(b"a: 1\n---\n\n") == [{"a": 1}]
        assert self._docs(b"") == []
