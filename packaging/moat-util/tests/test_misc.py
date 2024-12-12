"""
More util functions
"""

from __future__ import annotations

from moat.util.misc import pos2val, val2pos


def test_val2pos():
    """
    Translate an input value to the position in an interval
    """
    assert val2pos(0, 1, 2) == 0.5
    assert val2pos(0, 1, 4) == 0.25
    assert val2pos(0, 3, 4) == 0.75
    assert val2pos(4, 3, 0) == 0.25
    assert val2pos(4, 1, 0) == 0.75
    assert val2pos(0, 0, 2) == 0.0
    assert val2pos(0, 2, 2) == 1.0
    assert val2pos(0, -2, 2) == -1.0
    assert val2pos(0, 4, 2) == 2.0
    assert val2pos(0, 4, 2, clamp=True) == 1.0
    assert val2pos(0, -1, 2, clamp=True) == 0.0


def test_pos2val():
    """
    Translate the position in an interval to an output value
    """
    assert pos2val(0, 0.5, 2) == 1
    assert pos2val(0, 0.25, 4) == 1
    assert pos2val(0, 0.75, 4) == 3
    assert pos2val(4, 0.25, 0) == 3
    assert pos2val(4, 0.75, 0) == 1
    assert pos2val(0, 0, 2) == 0
    assert pos2val(0, 1, 2) == 2
    assert pos2val(0, -1, 2) == -2
    assert pos2val(0, 2, 2) == 4
    assert pos2val(0, 1.5, 2, clamp=True) == 2
    assert pos2val(0, -1, 2, clamp=True) == 0.0
