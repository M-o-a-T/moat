"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

from moat.lib.micro import (
    TimeoutError,  # pylint: disable=redefined-builtin # noqa:A004
    log,
    wait_for_ms,
)
from moat.lib.path import Path

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["OutOfData", "_add_obj", "pos2val", "srepr", "val2pos", "wait_complain"]


class OutOfData(EOFError):  # noqa: D101
    pass


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


def drepr(k, v):
    "short repr of dictionaries"
    k = str(k)
    if v is None:
        return "?" + k
    if v is False:
        return "!" + k
    if v is True:
        return k
    return f"{k}={srepr(v)}"


def srepr(x, bare=False):
    "short repr of possibly-complex objects"
    if isinstance(x, set):
        if not x:
            return "∅"
        else:
            return "⊕".join(srepr(v) for v in x)
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, tuple):
        if bare:
            return ",".join(srepr(v) for v in x)
        return "(" + ",".join(srepr(v) for v in x) + ")"
    if isinstance(x, list):
        if bare:
            return ",".join(srepr(v) for v in x)
        return "[" + ",".join(srepr(v) for v in x) + "]"
    if isinstance(x, dict):
        if bare:
            return ",".join(drepr(k, v) for k, v in x.items())
        return "{" + ",".join(drepr(k, v) for k, v in x.items()) + "}"
    try:
        d = vars(x)
    except TypeError:
        return str(x)
    else:
        return f"{type(x).__name__}{srepr(d)}"


def _add_obj(a, b):
    """add attributes of B to A if they're missing"""
    for k in dir(b):
        if not hasattr(a, k):
            setattr(a, k, getattr(b, k))


async def wait_complain(s: str, i: int, p: Callable, *a, **k):
    """
    Wait for a callable to complete, complaining if it takes too long.

    Args:
        s: Description string for logging.
        i: Timeout in milliseconds.
        p: Callable to wait for.
        *a: Positional arguments for the callable.
        **k: Keyword arguments for the callable.
    """
    try:
        await wait_for_ms(i, p, *a, **k)
    except TimeoutError:
        log("Delayed  %s", s)
        await p(*a, **k)
        log("Delay OK %s", s)
