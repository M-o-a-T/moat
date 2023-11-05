"""
Empty test file
"""
from __future__ import annotations

from moat.util.misc import range_at, range_for


def test_range_at():
    """
    Empty test
    """
    assert range_at(0, 1, 2) == 0.5
    assert range_at(0, 1, 4) == 0.25
    assert range_at(0, 3, 4) == 0.75
    assert range_at(4, 3, 0) == 0.25
    assert range_at(4, 1, 0) == 0.75
    assert range_at(0, 0, 2) == 0.0
    assert range_at(0, 2, 2) == 1.0
    assert range_at(0, -2, 2) == -1.0
    assert range_at(0, 4, 2) == 2.0
    assert range_at(0, 4, 2, clamp=True) == 1.0
    assert range_at(0, -1, 2, clamp=True) == 0.0

def test_range_for():
    """
    Empty test
    """
    assert range_for(0, 0.5, 2) == 1
    assert range_for(0, 0.25, 4) == 1
    assert range_for(0, 0.75, 4) == 3
    assert range_for(4, 0.25, 0) == 3
    assert range_for(4, 0.75, 0) == 1
    assert range_for(0, 0, 2) == 0
    assert range_for(0, 1, 2) == 2
    assert range_for(0, -1, 2) == -2
    assert range_for(0, 2, 2) == 4
    assert range_for(0, 1.5, 2, clamp=True) == 2
    assert range_for(0, -1, 2, clamp=True) == 0.0
