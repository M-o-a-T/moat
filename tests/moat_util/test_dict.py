"""
Some rudimentary tests for merge and combine_dict
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

from moat.util import NotGiven, P, attrdict, combine_dict, merge, to_attrdict


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
    r = to_attrdict(a).update_(b, c)
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
    chkcr(dict(a=1, b=2, c=3), dict(b=4, d=5), dict(a=1, b=4, c=3, d=5))
    chkcr(dict(a=1, b=2, c=3), dict(b=NotGiven), dict(a=1, c=3))
    chkcr(dict(b=NotGiven), dict(a=1, b=2, c=3), dict(a=1, b=2, c=3))


def test_update():
    chku(dict(a={"b": "fubar", "ft": 42}), P("a.ft"), 44, dict(a={"b": "fubar", "ft": 44}))


def test_post():
    assert not attrdict().needs_post_
    assert not attrdict(a=1).needs_post_
    assert not attrdict(a=P("foo")).needs_post_
    assert attrdict(a=P(":@.foo")).needs_post_

    d = attrdict()
    d["$a"] = 42
    assert d.needs_post_
    assert attrdict(x=d).needs_post_
    e = attrdict()
    e["y"] = d
    assert e.needs_post_

    f = e.update_(P("f:n.h"), P(":@.bar"))
    assert f.needs_post_
    g = attrdict(i=[None, None, attrdict(k=attrdict())])
    assert not g.needs_post_
    g.set_(P("i:2.k"), attrdict((("$b", "cd"),)))
    assert g.needs_post_
