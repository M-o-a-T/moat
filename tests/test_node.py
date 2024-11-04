"""Basic tests for nodes
"""
from __future__ import annotations

import time
import pytest

from moat.link.node import Node
from moat.util import NotGiven,Path, P, PathLongener

def dump(n):
    """dump a node into a dict"""
    res = {}
    pl = PathLongener()
    for d,s,da,_ti,so in n.dump():
        s = pl.long(d,s)
        res[s] = (da,so)
    return res


def test_basic():
    n = Node()
    t = time.time()
    res = {
        P("a.b.c"): (42, "A"),
        P("a.b.c.d"): (99, "B"),
        P("b.c.d"): (111, "B"),
    }

    assert n.data is NotGiven
    assert n.set(P("a.b.c"), 42, "A")
    assert n.set(P("a.b.c.d"), 99, "B")
    assert n.set(P("b.c.d"), 111, "B")
    with pytest.raises(KeyError):
        n[P("a.b")]
    a = n[P("a.b.c")]
    assert a.data == 42
    assert a.source == "A"
    assert t <= a.tick <= time.time()
    assert dump(n) == res

    nn = Node()
    np = nn.load()
    np.send(None)
    for x in n.dump():
        np.send(x)
    np.close()
    assert dump(nn) == res

    assert n.set(P("a.b.c"), 42, "A") is False
    assert n.set(P("a.b.c"), 43, "A")
    assert n.set(P("a.b.c"), 43, "B") is False
    assert n.set(P("a.b.c"), 43, "B", force=True) is None
    assert n.set(P("a.b.c"), 43, "B", tick=999, force=True) is False
    assert n.set(P("a.b.c"), 44, "C", tick=9999, force=True) is False
    assert n.set(P("a.b.c"), 44, "C", tick=9999, force=False) is False
    assert n[P("a.b.c")].data == 43
    assert n[P("a.b.c")].source == "B"

