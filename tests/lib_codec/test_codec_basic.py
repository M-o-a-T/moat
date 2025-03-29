"""
Basic codec tests
"""

from __future__ import annotations

from moat.lib.codec import get_codec
from moat.util import NotGiven, OutOfData

import pytest


def test_noop():
    "basic tests for doing nothing"
    c = get_codec("noop")
    assert c.encode(b"foo\0\ff") == b"foo\0\ff"
    assert c.decode(b"foo\0\ff") == b"foo\0\ff"
    c.feed(b"foo\0\ff")
    assert next(c) == b"foo\0\ff"
    with pytest.raises(ValueError):
        c.encode("bar")
    with pytest.raises(ValueError):
        c.encode(42)


def test_utf8():
    "basic UTF-8 string tests"
    c = get_codec("utf8")
    assert c.encode("foo") == b"foo"
    assert c.decode(b"H\xc3\xaby!") == "Hëy!"
    assert c.encode("Hëy!") == b"H\xc3\xaby!"
    c.feed(b"H\xc3")
    assert next(c) == "H"
    c.feed(b"\xaby!")
    assert next(c) == "ëy!"

    with pytest.raises(ValueError):
        c.encode(b"bar")
    with pytest.raises(ValueError):
        c.encode(42)


objs = (
    "Foo",
    True,
    False,
    None,
    123,
    99.5,
    {"one": "two"},
    {"no": False, "yes": True},
    [12, "three four", 56],
)


@pytest.mark.parametrize("obj", objs)
def test_json(obj):
    "basic json tests"
    import json

    c = get_codec("json")

    assert json.loads(c.encode(obj).decode("utf-8")) == obj
    assert c.decode(json.dumps(obj).encode("utf-8")) == obj


@pytest.mark.parametrize("obj", objs)
def test_msgpack(obj):
    "basic msgpack tests"
    import msgpack

    c = get_codec("msgpack")

    assert msgpack.unpackb(c.encode(obj)) == obj
    assert c.decode(msgpack.packb(obj)) == obj


@pytest.mark.parametrize("obj", objs)
def test_cbor(obj):
    "basic CBOR tests"
    import cbor2

    c = get_codec("cbor")

    a = c.encode(obj)
    b = cbor2.dumps(obj, canonical=True)
    assert a == b, (obj, a, b)
    assert cbor2.loads(a) == obj, (obj, a)
    assert c.decode(a) == obj, (obj, a)

def test_cbor_ng():
    """
    Test special support for top-level NotGiven (Ellipsis).
    """
    c = get_codec("cbor")

    a = c.encode(NotGiven, empty_elided=True)
    assert a == b''
    assert c.encode(NotGiven) == b'\xf7'
    b = c.decode(a, empty_elided=True)
    assert b is NotGiven
    assert c.decode(b'\xf7') is NotGiven
    with pytest.raises(OutOfData):
        c.decode(b'')

    # Embedding NotGiven still results in undef
    x = c.encode([NotGiven], empty_elided=True)
    assert x == b'\x81\xf7'
    assert c.decode(x) == [NotGiven]
