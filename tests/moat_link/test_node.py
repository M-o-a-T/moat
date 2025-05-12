"""Basic tests for nodes"""

from __future__ import annotations

import pytest
import time
from itertools import zip_longest

from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.util import NotGiven, P, PathLongener


def dump(n):
    """dump a node into a dict"""
    res = {}
    pl = PathLongener()
    for d, s, da, *me in n.dump():
        me = MsgMeta.restore(me)
        s = pl.long(d, s)  # noqa:PLW2901
        res[s] = (da, me.origin)
    return res


def test_basic():
    """
    Basic Node tests
    """
    n = Node()
    t = time.time()
    res = {
        P("a.b.c"): (42, "A"),
        P("a.b.c.d"): (99, "B"),
        P("b.c.d"): (111, "B"),
    }

    assert not n
    assert n._data is NotGiven  # noqa:SLF001
    assert n.set(P("a.b.c"), 42, MsgMeta(origin="A"))
    assert n.set(P("a.b.c.d"), 99, MsgMeta(origin="B"))
    assert n.set(P("b.c.d"), 111, MsgMeta(origin="B"))
    with pytest.raises(KeyError):
        n[P("a.b")]
    a = n[P("a.b.c")]
    assert a.data == 42
    assert a.meta.origin == "A"
    assert t <= a.meta.timestamp <= time.time()
    assert dump(n) == res

    nn = Node()
    np = nn.load()
    np.send(None)
    for x in n.dump():
        np.send(x)
    np.close()
    assert dump(nn) == res

    assert n.set(P("a.b.c"), 42, MsgMeta(origin="A")) is None
    assert n.set(P("a.b.c"), 43, MsgMeta(origin="A"))
    assert n.set(P("a.b.c"), 43, MsgMeta(origin="B")) is None
    assert n.set(P("a.b.c"), 43, MsgMeta(origin="B"), force=True) is True
    assert n.set(P("a.b.c"), 43, MsgMeta(origin="B", timestamp=999), force=True) is False
    assert n.set(P("a.b.c"), 44, MsgMeta(origin="C", timestamp=9999), force=True) is False
    assert n.set(P("a.b.c"), 44, MsgMeta(origin="C", timestamp=9999), force=False) is False
    assert n[P("a.b.c")].data == 43
    assert n[P("a.b.c")].meta.origin == "B"

    assert n.set(P("a.b.e"), 10, MsgMeta(origin="B"))
    assert n.set(P("a.b.f"), 11, MsgMeta(origin="B"))
    assert n.set(P("a.b.g.h"), 12, MsgMeta(origin="B"))
    assert n.set(P("a.b.g.o"), 121, MsgMeta(origin="B"))
    assert n.set(P("a.b.i"), 13, MsgMeta(origin="B"))
    assert n.set(P("a.b.j"), 14, MsgMeta(origin="B"))
    assert n.set(P("a.c"), 15, MsgMeta(origin="B"))
    assert n.set(P("a.c.d"), 16, MsgMeta(origin="B"))
    assert n.set(P("a.b.d"), 17, MsgMeta(origin="B"))
    assert n.set(P("c.b.d"), 18, MsgMeta(origin="B"))
    assert n.set(P("c.b.f.g"), 19, MsgMeta(origin="B"))
    assert n.set(P("c.e.t"), 20, MsgMeta(origin="B"))
    for a, b in zip_longest(n._dump_x(), n.dump()):
        assert a == b, (a, b)
