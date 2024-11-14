"""
Basic codec tests
"""

from __future__ import annotations

from moat.lib.codec import NoCodecError, get_codec

import pytest


def test_noop():
    "basic tests for doing nothing"
    c = get_codec("noop")
    assert c.encode(b"foo\0\ff") == b"foo\0\ff"
    assert c.decode(b"foo\0\ff") == b"foo\0\ff"
    assert c.feed(b"foo\0\ff") == b"foo\0\ff"
    with pytest.raises(NoCodecError):
        c.encode("bar")
    with pytest.raises(NoCodecError):
        c.encode(42)


def test_utf8():
    "basic UTF-8 string tests"
    c = get_codec("utf8")
    assert c.encode("foo") == b"foo"
    assert c.decode(b"H\xc3\xaby!") == "Hëy!"
    assert c.encode("Hëy!") == b"H\xc3\xaby!"
    assert c.feed(b"H\xc3") == "H"
    assert c.feed(b"\xaby!") == "ëy!"

    with pytest.raises(NoCodecError):
        c.encode(b"bar")
    with pytest.raises(NoCodecError):
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

    assert msgpack.unpackb(c.encode(obj), use_list=True) == obj
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
