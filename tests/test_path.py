"""
Testing util.Path
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import pytest

from moat.util import P, Path, packer, unpacker, yformat, yload

_valid = (
    (("a", "b", "c"), "a.b.c"),
    (("a", 2, "c"), "a:2.c"),
    ((2, "c"), (":i2.c", ":2.c")),
    ((True, "c"), ":t.c"),
    ((1.23, "c"), ":1:.23.c"),
    (("", 1.23, "c"), ":e:1:.23.c"),
    (("a", "", 1.23, "c"), "a:e:1:.23.c"),
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
    ".a.b",
    "a.b.",
    "a:h123",
    "",
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
    p = Path()
    p.mark = "bar"
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
    d = ("a", 1, "b")
    m = packer(d)
    mm = unpacker(m)
    assert type(mm) is tuple  # pylint: disable=unidiomatic-typecheck
    assert mm == d

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
