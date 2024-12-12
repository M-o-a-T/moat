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

from moat.util import DProxy, as_proxy, attrdict, packer, stream_unpacker, unpacker
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


def test_basic():
    for v in _val:
        w = unpacker(packer(v))
        assert v == w, (v, w)


def test_bar():
    b = Bar(95)
    as_proxy("b", b, replace=True)
    c = unpacker(packer(b))
    assert b == c
    with pytest.raises(ValueError, match="<Bar: 94>"):
        packer(Bar(94))


@pytest.mark.parametrize("chunks", [1, 2, 5])
def test_chunked(chunks):
    p = [(dict(a=1, b=23, c=345, d=6789012345678901234567890, e="duh")), "!"]
    m = b"".join(packer(x) for x in p)
    r = []
    u = stream_unpacker()
    for i in range(chunks):
        o1 = int(len(m) * (i / chunks))
        o2 = int(len(m) * ((i + 1) / chunks))
        u.feed(m[o1:o2])
        for msg in u:
            r.append(msg)
    assert r == p


def test_ip():
    adrs = (
        IPv4Address("1.23.45.181"),
        IPv6Address("FE80::12:34:0:0"),
        IPv4Network("1.23.45.128/25"),
        IPv6Network("FE80::12:35:0:0/111"),
        IPv4Interface("1.23.45.182/25"),
        IPv6Interface("FE80::12:36:F:ED/111"),
    )
    for a in adrs:
        m = packer(a)
        b = unpacker(m)
        assert type(a) is type(b)
        assert str(a) == str(b)


def test_dproxy():
    # first manually construct such a thing
    d = ("FuBar", (), None, [1, 2, 42], {"one": "two", "three": "four"})
    p = packer(ExtType(5, b"".join(packer(x) for x in d)))
    dp = unpacker(p)
    assert type(dp) is DProxy
    assert dp.name == "FuBar"
    assert dp[1] == 2
    assert dp[2] == 42
    assert dp["three" == "four"]
    pp = packer(dp)
    assert p == pp
