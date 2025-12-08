"""
Some rudimentary tests for merge and combine_dict
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

from moat.util import NotGiven, P, attrdict, combine_dict, merge


def chkm(a, b, c, drop=False):
    r = merge(a, b, drop=drop)
    assert r == c


def chkc(a, b, c):
    r = combine_dict(a, b)
    assert r == c


def chkcr(a, b, c):
    r = combine_dict(a, b, replace=True)
    assert r == c


def chku(a, b, c, d):
    r = attrdict._update(a, b, c)  # noqa: SLF001
    assert r == d


def test_merge():
    chkm(dict(a=1, b=2, c=3), dict(b=NotGiven), dict(a=1, c=3))
    chkm(dict(a=1, b=2, c=3), dict(b=4, d=5), dict(a=1, b=4, c=3, d=5))
    chkm(
        dict(a=1, b=[1, 2, 3], c=3),
        dict(b=(4, NotGiven, None, 6)),
        dict(a=1, b=[4, 3, 6], c=3),
    )
    chkm(
        dict(a=1, b=[1, 2, 3], c=3),
        dict(b={0: 4, 1: NotGiven, 3: 6}),
        dict(a=1, b=[4, 3, 6], c=3),
    )
    chkm(
        dict(a=1, b=[1, 2, 3], c=3),
        dict(a=1, b=(4, NotGiven, None, 6)),
        dict(a=1, b=[4, 3, 6]),
        drop=True,
    )


def test_combine():
    chkc(dict(a=1, b=2, c=3), dict(b=4, d=5), dict(a=1, b=2, c=3, d=5))
    chkc(dict(a=1, b=2, c=3), dict(b=NotGiven), dict(a=1, b=2, c=3))
    chkc(dict(b=NotGiven), dict(a=1, b=2, c=3), dict(a=1, c=3))


def test_combine_r():
    chkc(dict(a=1, b=2, c=3), dict(b=4, d=5), dict(a=1, b=4, c=3, d=5))
    chkc(dict(a=1, b=2, c=3), dict(b=NotGiven), dict(a=1, c=3))
    chkc(dict(b=NotGiven), dict(a=1, b=2, c=3), dict(a=1, b=2, c=3))


def test_update():
    chku(dict(a={"b": "fubar", "ft": 42}), P("a.ft"), 44, dict(a={"b": "fubar", "ft": 44}))
