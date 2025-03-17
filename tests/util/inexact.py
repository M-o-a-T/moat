"""
Test inexact numbers
"""

from __future__ import annotations

from moat.util import InexactFloat

def I(val):
    return InexactFloat(val, .1,.5)  # rel, abs

def test_inexact():
    """
    Check for proper inequality
    """
    assert not I(5) < 4
    assert I(5) > 4
    assert I(5) >= 4
    assert not I(5) > 6
    assert I(5) < 6
    assert I(5) <= 6

    assert I(20) == 21
    assert I(20) <= 21
    assert I(20) >= 21
    assert I(20) == 19
    assert I(20) <= 19
    assert I(20) >= 19

    assert I(0) == I(.4)
    assert I(0) < I(.6)

    # pylint: disable=unnecessary-pass
