"""
Some rudimentary tests for packing
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest

import moat.util.cbor  # for the error traceback, if any
import moat.util.msgpack  # for the error traceback, if any
from moat.util import as_proxy, attrdict, packer, unpacker, stream_unpacker


class Bar:
    "A proxied object"

    # ruff:noqa:PLW1641

    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return self.x == other.x


# needs "replace" because testing re-imports
@as_proxy("fu", replace=True)
class Foo(Bar):
    "A proxied class"

    # pylint: disable=unnecessary-pass


_val = [
    Foo(42),
    attrdict(x=1, y=2),
]

@pytest.mark.parametrize("cbor",(False,True))
def test_basic(cbor):
    for v in _val:
        w = unpacker(packer(v, cbor=cbor), cbor=cbor)
        assert v == w, (v, w)


@pytest.mark.parametrize("cbor",(False,True))
def test_bar(cbor):
    b = Bar(95)
    as_proxy("b", b, replace=True)
    c = unpacker(packer(b, cbor=cbor), cbor=cbor)
    assert b == c
    with pytest.raises(ValueError):
        packer(Bar(94), cbor=cbor)

@pytest.mark.parametrize("cbor",(False,True))
@pytest.mark.parametrize("chunks",(1,2,5))
def test_chunked(cbor,chunks):
    p = [(dict(a=1,b=23,c=345,d=6789012345678901234567890,e="duh")),"!"]
    m = b"".join(packer(x) for x in p)
    r = []
    u = stream_unpacker()
    for i in range(chunks):
        o1 = int(len(m) * (i/chunks))
        o2 = int(len(m) * ((i+1)/chunks))
        u.feed(m[o1 : o2])
        for msg in u:
            r.append(msg)
    assert r == p
