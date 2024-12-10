"""
Testing util.Path
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest

from moat.util import PS, P, Path, packer, unpacker, yformat, yload

_valid = (
    (("a", "b", "c"), "a.b.c"),
    (("a", 2, "c"), "a:2.c"),
    ((2, "c"), (":i2.c", ":2.c")),
    ((True, "c"), ":t.c"),
    ((1.23, "c"), ":1:.23.c"),
    (("", 1.23, "c"), ":e:1:.23.c"),
    (("a", "", 1.23, "c"), "a:e:1:.23.c"),
    (("a", "", 1.23, ""), "a:e:1:.23:e"),
    (("a", "", 1.23), "a:e:1:.23"),
    (("a", "", "b"), "a:e.b"),
    (("a", "x y", "b"), ("a.x y.b", "a.x:_y.b")),
    (("a", True), "a:t"),
    (("x", None), "x:n"),
    ((31,), (":x1f", ":31")),
    ((31, "q"), (":x1f.q", ":31.q")),
    (("b", 31, 5), ("b:x1f:5", "b:31:5")),
    (((1, 2), 1.23), (":(1,2):1:.23", ":1,2:1:.23")),
    (((1, 2), "", 1.23), (":(1,2):e:1:.23", ":1,2:e:1:.23")),
    (((1, 2), "c"), ":1,2.c"),
    (((1, "a b", 2), "c"), (":1,'a b',2.c", ":1,'a:_b',2.c")),
    ((), ":"),
    (("a", b"abc"), "a:vabc"),
    (("a", b"ab\x99"), ("a:y616299", "a:sYWKZ")),
    (("a", b"a b"), "a:va:_b"),
    (("a", b"", "c"), "a:v.c"),
)

_invalid = (
    ":w",
    ":t:",
    "a.b:",
    ":2..c",
    "a..b",
    "a.:1",
    "a.:t",
    ":x1g",
    ":x",
    ":ec",
    ".a.b",
    "a.b.",
    "a:h123",
    "",
    ":list",
    ":dict",
)

_valid_s = (
    (("a", "b", "c"), "a/b/c"),
    (("a", 2, "c"), "a/:2/c"),
    ((2, "c"), (":i2/c", ":2/c")),
    ((True, "c"), ":t/c"),
    ((1.23, "c"), ":1.23/c"),
    (("", 1.23, "c"), "/:1.23/c"),
    (("a", "", 1.23, "c"), "a//:1.23/c"),
    (("a", "", 1.23, ""), "a//:1.23/"),
    (("a", "", 1.23), "a//:1.23"),
    (("a", "", "b"), "a//b"),
    (("a", "x y", "b"), "a/x y/b"),
    (("a", True), "a/:t"),
    (("x", None), "x/:n"),
    ((31,), (":x1f", ":31")),
    ((31, "q"), (":x1f/q", ":31/q")),
    (("b", 31, 5), ("b/:x1f/:5", "b/:31/:5")),
    (((1, 2), 1.23), (":(1,2)/:1.23", ":1,2/:1.23")),
    (((1, 2), "", 1.23), (":(1,2)//:1.23", ":1,2//:1.23")),
    (((1, 2), "c"), ":1,2/c"),
    (((1, "a b", 2), "c"), (":1,'a b',2/c", ":1,'a:_b',2/c")),
    (("a", b"abc"), "a/:vabc"),
    (("a", b"ab\x99"), ("a/:y616299", "a/:sYWKZ")),
    (("a", b"a b"), "a/:va:_b"),
    (("a", b"", "c"), "a/:v/c"),
    ((), ":m"),
)
_valid_s2 = (
    (("",), ("", ":e"), ""),
    (("", ""), ("/", ":e:e"), ""),
    (("", "a", ""), ("/a/", ":e.a:e"), ""),
    (("", "a", "b", ""), ("/a/b/", ":e.a.b:e"), ""),
    (("",), (":mx/", ":mx:e"), "x"),
    (("", ""), (":mx//", ":mx:e:e"), "x"),
    (("", "a", ""), (":mx//a/", ":mx:e.a:e"), "x"),
    (("", "a", "b", ""), (":mx//a/b/", ":mx:e.a.b:e"), "x"),
)

_invalid_s = (
    ":w",
    ":t:",
    "/:",
    ":",
    ":/",
    ":e",
    ":ec",
    #   "a:1",
    #   "a:t",
    #   "a:n",
    ":x1g",
    ":x",
    "a/:h123",
    ":list",
    ":dict",
)


@pytest.mark.parametrize("a,b", _valid)  # noqa:PT006
def test_valid_paths(a, b):
    if isinstance(b, tuple):
        b, xb = b
    else:
        xb = b
    assert str(Path(*a)) == xb
    assert a == tuple(Path.from_str(b))


@pytest.mark.parametrize("a", _invalid)
def test_invalid_paths(a):
    with pytest.raises(SyntaxError):
        Path.from_str(a)


@pytest.mark.parametrize("a,b", _valid_s)  # noqa:PT006
def test_valid_spaths(a, b):
    if isinstance(b, tuple):
        b, xb = b
    else:
        xb = b
    assert Path(*a).slashed == xb
    assert a == tuple(Path.from_slashed(b))


@pytest.mark.parametrize("a,b,m", _valid_s2)  # noqa:PT006
def test_valid_spaths2(a, b, m):
    b, xb = b
    assert str(Path(*a, mark=m)) == xb
    assert a == tuple(Path.from_slashed(b))


@pytest.mark.parametrize("a", _invalid_s)
def test_invalid_spaths(a):
    with pytest.raises(SyntaxError):
        Path.from_slashed(a)


def test_paths():
    p = P("a.b")
    assert str(p) == "a.b"
    q = p | "c"
    assert str(p) == "a.b"
    assert str(q) == "a.b.c"
    r = p + ()  # noqa:RUF005
    assert p is r
    r = p + ("c", "d")  # noqa:RUF005
    assert str(p) == "a.b"
    assert str(r) == "a.b.c.d"
    pp = Path.build(("a", "b"))
    assert str(p) == str(pp)


def test_tagged():
    p = P(":mfoo:")
    assert p.mark == "foo"
    assert len(p) == 0
    p = Path(mark="bar")
    assert str(p) == ":mbar:"
    p = P("a:mx.b")
    assert p.mark == "x"  # pylint: disable=no-member
    p = P(":mx.a.b")
    assert p.mark == "x"  # pylint: disable=no-member
    p = P(":mx.a.b:mx")
    assert p.mark == "x"  # pylint: disable=no-member
    p = P("a.b:mx")
    assert p.mark == "x"  # pylint: disable=no-member
    with pytest.raises(SyntaxError):
        P(":mx.a:my.b")
    with pytest.raises(SyntaxError):
        P("a:mx.b:my")


def test_msgpack():
    d = ["a", 1, "b"]
    m = packer(d)
    mm = unpacker(m)
    assert isinstance(mm, (tuple, list))
    assert list(mm) == d

    d = Path("a", 1, "b")
    m = packer(d)
    mm = unpacker(m)
    assert type(mm) is Path  # pylint: disable=unidiomatic-typecheck
    assert mm == d

    d = {"Hello": d}
    m = packer(d)
    mm = unpacker(m)
    assert type(mm["Hello"]) is Path  # pylint: disable=unidiomatic-typecheck
    assert mm == d


def test_yaml():
    a = Path.from_str("a.b.c")
    b = "!P a.b.c\n...\n"
    assert yformat(a) == b
    assert yload(b) == a


def test_root():
    from moat.util.cbor import StdCBOR
    from moat.util.path import Q_Root, Root

    Root.set(P("abba.c"))
    Q_Root.set(P("some.queue"))
    p = P(":R.d.::a.e")
    p2 = P("yes:Q.d.::a.e")
    c = StdCBOR()
    assert p.slashed == "abba/c/d/::a/e"
    assert str(p) == ":R.d.::a.e"
    pc = c.encode(p)
    p2c = c.encode(p2)
    assert b"abba" not in pc
    assert b"queue" not in p2c

    assert b":a" in pc
    assert b"::a" not in pc

    Root.set(P("duddy"))
    Q_Root.set(P("fuddy"))
    pp = c.decode(pc)
    pp2 = c.decode(p2c)
    assert pp.slashed == "duddy/d/::a/e"
    assert pp2.slashed == "yes/fuddy/d/::a/e"
    assert p == pp
    assert p2 == pp2
    assert p != p2

    assert "yes" in pp2
    assert "fuddy" not in pp2

    assert pp2 == PS("yes/fuddy/d/::a/e")
