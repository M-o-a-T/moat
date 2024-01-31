"""
Some rudimentary tests for packing
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest

from moat.util import as_proxy, attrdict, packer, unpacker

pytestmark = pytest.mark.skip


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


def test_basic():
    for v in _val:
        w = unpacker(packer(v, cbor=True), cbor=True)
        assert v == w, (v, w)


def test_bar():
    b = Bar(95)
    as_proxy("b", b, replace=True)
    c = unpacker(packer(b, cbor=True), cbor=True)
    assert b == c
    with pytest.raises(TypeError):
        packer(Bar(94), cbor=True)
