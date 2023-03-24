"""
Some rudimentary tests for packing
"""

# pylint: disable=missing-function-docstring

import pytest

from moat.util import packer,unpacker, as_proxy, attrdict

class Bar:
    def __init__(self, x):
        self.x = x
    def __eq__(self, other):
        return self.x == other.x

@as_proxy("fu")
class Foo(Bar):
    pass

_val = [
        Foo(42),
        attrdict(x=1,y=2),
    ]

def test_basic():
    for v in _val:
        w = unpacker(packer(v))
        assert v == w, (v,w)

def test_bar():
    b = Bar(95)
    as_proxy("b")(b)
    c = unpacker(packer(b))
    assert b == c
    with pytest.raises(TypeError):
        packer(Bar(94))
