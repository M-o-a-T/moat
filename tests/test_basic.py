"""
Basic codec tests
"""

from __future__ import annotations

from moat.lib.codec import NoCodecError, get_codec

import pytest


def test_noop():
    c = get_codec("noop")
    assert c.encode(b"foo\0\ff") == b"foo\0\ff"
    assert c.decode(b"foo\0\ff") == b"foo\0\ff"
    assert c.feed(b"foo\0\ff") == b"foo\0\ff"
    with pytest.raises(NoCodecError):
        c.encode("bar")
    with pytest.raises(NoCodecError):
        c.encode(42)


def test_utf8():
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
    [12, "three four", 56],
)

@pytest.mark.parametrize("obj",objs)
def test_json(obj):
    import json
    c = get_codec("json")

    assert json.loads(c.encode(obj).decode("utf-8")) == obj
    assert c.decode(json.dumps(obj).encode("utf-8")) == obj

@pytest.mark.parametrize("obj",objs)
def test_msgpack(obj):
    import msgpack
    c = get_codec("msgpack")

    assert msgpack.unpackb(c.encode(obj), use_list=True) == obj
    assert c.decode(msgpack.packb(obj)) == obj


@pytest.mark.parametrize("obj",objs)
def test_cbor(obj):
    import cbor2
    c = get_codec("cbor")

    assert cbor2.loads(c.encode(obj)) == obj, (obj, c.encode(obj))
    assert c.decode(cbor2.dumps(obj)) == obj, (obj, cbor2.dumps(obj))
