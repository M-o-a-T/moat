"""
Some rudimentary tests for packing
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest
from ipaddress import IPv4Address, IPv4Network, IPv4Interface, IPv6Address, IPv6Network, IPv6Interface

import moat.util.cbor  # for the error traceback, if any
import moat.util.msgpack  # for the error traceback, if any
from moat.util import as_proxy, attrdict, packer, unpacker, stream_unpacker, DProxy
from moat.util.cbor import Tag
from moat.util.msgpack import ExtType

as_proxy("_ip4", IPv4Address)
as_proxy("_ip6", IPv6Address)
as_proxy("_ip4n", IPv4Network)
as_proxy("_ip6n", IPv6Network)
as_proxy("_ip4i", IPv4Interface)
as_proxy("_ip6i", IPv6Interface)

class Bar:
    "A proxied object"

    # ruff:noqa:PLW1641

    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return self.x == other.x

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.x}>"

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

@pytest.mark.parametrize("cbor",(False,True))
def test_ip(cbor):
    adrs = (
            IPv4Address("1.23.45.181"),
            IPv6Address("FE80::12:34:0:0"),
            IPv4Network("1.23.45.128/25"),
            IPv6Network("FE80::12:35:0:0/111"),
            IPv4Interface("1.23.45.182/25"),
            IPv6Interface("FE80::12:36:F:ED/111"),
        )
    for a in adrs:
        m = packer(a, cbor=cbor)
        if cbor:
            assert m[0] == 216 and m[1] == (52 if '4' in str(type(a)) else 54)
        b = unpacker(m, cbor=cbor)
        assert type(a) == type(b)
        assert str(a) == str(b)

    p1 = packer(IPv4Address("12.34.0.0"), cbor=cbor)
    p2 = packer(IPv4Address("12.34.0.1"), cbor=cbor)
    if cbor:
        assert len(p1)+2==len(p2)

    p1 = packer(IPv6Address("FE80::12:34:800:0"), cbor=cbor)
    p2 = packer(IPv6Address("FE80::12:34:800:1"), cbor=cbor)
    if cbor:
        assert len(p1)+3==len(p2)

def test_ip_old():
    for adr in (IPv4Address("1.23.45.181"), IPv6Address("FE80::12:34:56")):
        msg = unpacker(packer(Tag(260,adr.packed),cbor=True),cbor=True)
        assert type(adr) == type(msg)
        assert str(adr) == str(msg)

    for adr in (IPv4Network("1.23.45.128/25"), IPv6Network("FE80::12:35:0:0/111")):
        msg = unpacker(packer(Tag(261,{adr.prefixlen:adr.network_address.packed}),cbor=True),cbor=True)
        assert type(adr) == type(msg)
        assert str(adr) == str(msg)

@pytest.mark.parametrize("cbor",(False,True))
def test_dproxy(cbor):
    # first manually construct such a thing
    d = ("FuBar",(),None,[1,2,42],{"one":"two","three":"four"})
    if cbor:
        p = packer(Tag(27, ("FuBar",(),None,[1,2,42],{"one":"two","three":"four"})), cbor=cbor)
    else:
        p = packer(ExtType(5, b''.join(packer(x) for x in d)))
    dp = unpacker(p, cbor=cbor)
    assert type(dp) is DProxy
    assert dp.name == "FuBar"
    assert dp[1] == 2
    assert dp[2] == 42
    assert dp["three" == "four"]
    pp = packer(dp, cbor=cbor)
    assert p == pp


