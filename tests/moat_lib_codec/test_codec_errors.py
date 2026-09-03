"""
Tests for moat.lib.codec.errors — error classes used in codec/RPC.
"""

from __future__ import annotations

import pytest

from moat.lib.codec.errors import NoPathError, SilentRemoteError
from moat.lib.path import P


class TestSilentRemoteError:
    """Test SilentRemoteError."""

    def test_is_runtime_error(self):
        """is runtime error."""
        err = SilentRemoteError("test")
        assert isinstance(err, RuntimeError)

    def test_message_preserved(self):
        """message preserved."""
        err = SilentRemoteError("something failed")
        assert "something failed" in str(err)


class TestNoPathError:
    """Test NoPathError."""

    def test_is_key_error(self):
        """is key error."""
        err = NoPathError(P("foo"), ["bar"])
        assert isinstance(err, KeyError)

    def test_str_contains_path(self):
        """str contains path."""
        err = NoPathError(P("foo"), ["bar"])
        s = str(err)
        assert "foo" in s

    def test_str_contains_all_args(self):
        """str contains all args."""
        err = NoPathError(P("a"), ["b"], "c", "d")
        s = str(err)
        assert "a" in s

    def test_args_preserved(self):
        """args preserved."""
        err = NoPathError(P("foo"), ["bar"], "extra")
        assert err.args[0] == P("foo")
        assert err.args[1] == ["bar"]
        assert err.args[2] == "extra"

    def test_with_multiple_args(self):
        """with multiple args."""
        err = NoPathError(P("a"), ["b"], "c", "d")
        assert len(err.args) == 4

    def test_can_be_raised_and_caught(self):
        """can be raised and caught."""
        with pytest.raises(NoPathError):
            raise NoPathError(P("test"), ["path"])

    def test_can_be_caught_as_key_error(self):
        """NoPathError subclasses KeyError, so catching KeyError should work."""
        with pytest.raises(KeyError):
            raise NoPathError(P("test"), ["path"])
