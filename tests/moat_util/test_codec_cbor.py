"""
Some rudimentary tests for packing
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)

from moat.util import attrdict
from moat.lib.codec import get_codec
from moat.lib.codec.cbor import Codec as CBOR
from moat.lib.codec.cbor import Tag
from moat.lib.codec.proxy import DProxy, as_proxy, name2obj
from moat.util.cbor import StdCBOR, gen_start, gen_stop

as_proxy("_ip4", IPv4Address)
as_proxy("_ip6", IPv6Address)
as_proxy("_ip4n", IPv4Network)
as_proxy("_ip6n", IPv6Network)
as_proxy("_ip4i", IPv4Interface)
as_proxy("_ip6i", IPv6Interface)


class Bar:
    "A proxied object"

    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return self.x == other.x

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.x}>"


# needs "replace" because testing re-imports
@as_proxy("fu_c")
class Foo(Bar):
    "A proxied class"

    # pylint: disable=unnecessary-pass


_val = [
    Foo(42),
    attrdict(x=1, y=2),
]


def test_basic():
    codec = StdCBOR()
    for v in _val:
        w = codec.decode(codec.encode(v))
        assert v == w, (v, w)


def test_bar():
    codec = StdCBOR()
    b = Bar(95)
    as_proxy("b_c", b)
    c = codec.decode(codec.encode(b))
    assert b == c
    cc = codec.encode(Bar(94))

    dec = get_codec("cbor")
    cd = dec.decode(cc)
    assert isinstance(cd, Tag)
    assert cd.tag == 32769
    bb = name2obj(cd.value)
    assert bb.x == 94


@pytest.mark.parametrize("chunks", [1, 2, 5])
def test_chunked(chunks):
    codec = StdCBOR()
    p = [dict(a=1, b=23, c=345, d=6789012345678901234567890, e="duh"), "!"]
    m = b"".join(codec.encode(x) for x in p)
    r = []
    for i in range(chunks):
        o1 = int(len(m) * (i / chunks))
        o2 = int(len(m) * ((i + 1) / chunks))
        print(f"from {o1} to {o2}")
        codec.feed(m[o1:o2])
        r.extend(iter(codec))
    assert r == p


def test_ip():
    codec = StdCBOR()
    adrs = (
        IPv4Address("1.23.45.181"),
        IPv6Address("FE80::12:34:0:0"),
        IPv4Network("1.23.45.128/25"),
        IPv6Network("FE80::12:35:0:0/111"),
        IPv4Interface("1.23.45.182/25"),
        IPv6Interface("FE80::12:36:F:ED/111"),
    )
    for a in adrs:
        m = codec.encode(a)
        assert m[0] == 216
        assert m[1] == (52 if "4" in str(type(a)) else 54)
        b = codec.decode(m)
        assert type(a) is type(b)
        assert str(a) == str(b)

    p1 = codec.encode(IPv4Address("12.34.0.0"))
    p2 = codec.encode(IPv4Address("12.34.0.1"))
    assert len(p1) + 2 == len(p2)

    p1 = codec.encode(IPv6Address("FE80::12:34:800:0"))
    p2 = codec.encode(IPv6Address("FE80::12:34:800:1"))
    assert len(p1) + 3 == len(p2)


def test_ip_old():
    codec = StdCBOR()
    for adr in (IPv4Address("1.23.45.181"), IPv6Address("FE80::12:34:56")):
        msg = codec.decode(codec.encode(Tag(260, adr.packed)))
        assert type(adr) is type(msg)
        assert str(adr) == str(msg)

    for adr in (IPv4Network("1.23.45.128/25"), IPv6Network("FE80::12:35:0:0/111")):
        msg = codec.decode(codec.encode(Tag(261, {adr.prefixlen: adr.network_address.packed})))
        assert type(adr) is type(msg)
        assert str(adr) == str(msg)


def test_dproxy():
    codec = StdCBOR()
    # first manually construct such a thing
    d = ("FuBar", 1, 2, 42, {"one": "two", "three": "four"})
    p = codec.encode(Tag(27, d))
    dp = codec.decode(p)
    assert type(dp) is DProxy
    assert dp.name == "FuBar"
    assert dp[1] == 2
    assert dp[2] == 42
    assert dp["three"] == "four"
    pp = codec.encode(dp)
    rcodec = CBOR()
    assert rcodec.decode(p) == rcodec.decode(pp)


def test_tags():
    t = gen_start("Hello", foo=42)
    assert t.tag == 55800
    assert t.value.tag == 1299145044
    tt = t.value.value
    assert len(tt[0]) >= 24
    assert tt[0].rstrip(" ") == "Hello"
    assert tt[1]["foo"] == 42

    t = gen_stop(bar=123.5)
    assert t.tag == 1298493254
    assert t.value["bar"] == 123.5
