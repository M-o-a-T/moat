"""
Empty test file
"""

from __future__ import annotations

from moat.src.test import raises


def test_nothing():
    """
    Empty test
    """
    pass  # pylint: disable=unnecessary-pass
    with raises(SyntaxError):
        raise SyntaxError("foo")
