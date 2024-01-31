"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

__all__ = ["val2pos", "pos2val"]


def val2pos(a: float, b: float, c: float, /, clamp: bool = False):
    """
    Return the position of @b within [@a…@c].

        b==a => 0
        b==c => 1
        b==(a+c)/2 => 0.5

    If @clamp is set, the return value is limited to [0…1] even if @b is
    outside a…c.

    @a and @c may not be equal.
    """

    res = (a - b) / (a - c)
    if clamp:
        if res < 0:
            res = 0
        elif res > 1:
            res = 1
    return res


def pos2val(a: float, b: float, c: float, /, clamp: bool = False):
    """
    Return the value of @b within [@a…@c].

        a,0,c => a
        a,1,c => c
        a,0.5,c => (a+c)/2
        a,-1,c => 2*a-c
        a,2,c => 2*c-a

    If @clamp is set, the input is limited to [0…1].

    @a and @c may not be equal.
    """

    if clamp:
        if b < 0:
            b = 0
        elif b > 1:
            b = 1

    return a + b * (c - a)
