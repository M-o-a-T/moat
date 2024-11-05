import pytest

from moat.lib.codec import get_codec, NoCodecError

def test_noop():
    c = get_codec("noop")
    assert c.encode(b'foo\0\ff') == b'foo\0\ff'
    assert c.decode(b'foo\0\ff') == b'foo\0\ff'
    assert c.feed(b'foo\0\ff') == b'foo\0\ff'
    with pytest.raises(NoCodecError):
        c.encode('bar')
    with pytest.raises(NoCodecError):
        c.encode(42)

def test_utf8():
    c = get_codec("utf8")
    assert c.encode('foo') == b'foo'
    assert c.decode(b'H\xc3\xaby!') == "Hëy!"
    assert c.encode("Hëy!") == b'H\xc3\xaby!'
    assert c.feed(b'H\xc3') == "H"
    assert c.feed(b'\xaby!') == "ëy!"

    with pytest.raises(NoCodecError):
        c.encode(b'bar')
    with pytest.raises(NoCodecError):
        c.encode(42)

def test_json():
    import json
    c = get_codec("json")
    for obj in (
            "Foo",
            True,
            False,
            None,
            123,
            99.5,
            {"one":"two"},
            [12,"three four",56],
            ):
        assert json.loads(c.encode(obj).decode("utf-8")) == obj
        assert c.decode(json.dumps(obj).encode("utf-8")) == obj
