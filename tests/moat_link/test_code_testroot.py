"""Tests for ``moat.link.code.testroot``: test roots and path resolution."""

from __future__ import annotations

import os
import pytest

from moat.util import attrdict, yload
from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.link.code.testroot import TestRoot, with_test_root


def test_alloc():
    "Test roots are :R.test.PID.SEQ and don't collide"
    a, b = TestRoot(), TestRoot()
    assert a.path[:2] == ("test", os.getpid())
    assert b.path[:2] == ("test", os.getpid())
    assert a.path != b.path
    assert not a.path.has_prefix


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        ("in", "test.1.2.in"),
        (":T.in.x", "test.1.2.in.x"),
        (":T", "test.1.2"),
        (":R.foo.bar", "foo.bar"),
        (":R", ":"),
        (":", "test.1.2"),
    ],
)
def test_resolve_path(src, dst):
    "Single paths"
    tr = TestRoot(P("test.1.2"))
    res = tr.resolve(P(src))
    assert res == P(dst)
    assert not res.has_prefix


@pytest.mark.parametrize("src", [":S.foo", ":Q.foo", ":@.foo"])
def test_resolve_bad(src):
    "Other roots and relative paths are rejected"
    with pytest.raises(ValueError, match="supported here"):
        TestRoot(P("test.1.2")).resolve(P(src))


def test_bad_root():
    "The test root itself must be plain"
    with pytest.raises(ValueError, match="plain path"):
        TestRoot(P(":R.test.1"))


def test_resolve_nested():
    "Paths inside dicts and lists; everything else is untouched"
    tr = TestRoot(P("test.1.2"))
    data = yload(
        """\
args:
  src: !P in
  dst: !P :T.out
  abs: !P :R.home.lamp
  seconds: 0.2
  name: in
steps:
- [monitor, out, !P out]
- [set, !P :R.x, 2]
- [check, "len(out) == 2"]
""",
        attr=True,
    )
    res = tr.resolve(data)
    assert type(res) is type(data)
    assert res.args == dict(
        src=P("test.1.2.in"),
        dst=P("test.1.2.out"),
        abs=P("home.lamp"),
        seconds=0.2,
        name="in",
    )
    assert res.steps == [
        ["monitor", "out", P("test.1.2.out")],
        ["set", P("x"), 2],
        ["check", "len(out) == 2"],
    ]
    assert isinstance(res.steps[0][2], Path)
    # the original is not modified
    assert data.args.src == P("in")

    assert tr.resolve((P("a"), attrdict(b=P(":R.b")))) == (P("test.1.2.a"), {"b": P("b")})


@pytest.mark.anyio
async def test_cleanup(cfg):
    "The test subtree is deleted afterwards, also on error, unless kept"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        c = await sf.client()

        async with with_test_root(c) as tr1, with_test_root(c) as tr2:
            assert tr1.path != tr2.path
            await c.d.set(tr1.resolve(P("a")), 1)
            await c.d.set(tr1.resolve(P("a.b")), 2)
            await c.d.set(tr2.resolve(P("a")), 3)
            assert (await c.d.get(tr1.resolve(P("a.b"))))[0] == 2
            assert (await c.d.get(tr2.resolve(P("a"))))[0] == 3
        for tr in (tr1, tr2):
            with pytest.raises(KeyError):
                await c.d.get(tr.resolve(P("a")))

        async def boom():
            async with with_test_root(c) as tr:
                await c.d.set(tr.resolve(P("x.y")), 1)
                raise RuntimeError(tr)

        with pytest.raises(RuntimeError) as exc:
            await boom()
        tr = exc.value.args[0]
        with pytest.raises(KeyError):
            await c.d.get(tr.resolve(P("x.y")))

        async with with_test_root(c, keep=True) as tr:
            await c.d.set(tr.resolve(P("x")), 4)
        assert (await c.d.get(tr.resolve(P("x"))))[0] == 4
        await tr.delete(c)
        with pytest.raises(KeyError):
            await c.d.get(tr.resolve(P("x")))
