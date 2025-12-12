"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest
import sys

from moat.util import P, as_proxy
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  a: _test.Cmd
  l: _test.LoopCmd
  _sys: _sys.Cmd
l:
  loop:
    qlen: 2
  link: {}
  log:
    txt: "LOOP"
r:
  mplex: true
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
      c: cfg.Cmd
      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
        console: true
        frame: 0x85
      log:
        txt: "MH"
      log_raw:
        txt: "ML"
      log_rel:
        txt: "MR"
    tt:
      a: b
      c: [1,2,3]
      x: y
      z: 99

  link: *link
  log:
    txt: "TH"
# log_rel:
#   txt: "TR"

"""


async def test_ping(tmp_path):
    "basic connectivity test"
    async with mpy_stack(tmp_path, CFG) as d:
        res = await d.cmd(P("r.b.echo"), m="hello")
        assert res.kw == dict(r="hello")


async def test_iter_m(tmp_path):
    "basic iterator tests"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.b")) as drb:
        print("Attach GDB to micropython now, then continue", file=sys.stderr)
        proc=d.sub["r"].s.s.link
        print(f"gdb {proc.argv[0]} {proc.pid}", file=sys.stderr)
        breakpoint()

        print("I01")
        res = []
        async with d.cmd(P("r.b.it"), lim=3).stream_in() as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]

        print("I40")
        res = []
        async with d.cmd(P("r.b.it")).stream_in() as it:
            print("I41")
            async for (n,) in it:
                if n == 3:
                    break
                res.append(n)
        assert res == [0, 1, 2]

        print("I50")
        for i in range(1, 4):
            assert await drb.nit() == i

        # now do the same thing with a subdispatcher
        s = d.sub_at(P("r.b"))

        print("I60")
        res = []
        async with s.it.stream_in(delay=0.2, lim=3) as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]

        print("I70")
        await s.clr()
        for i in range(1, 4):
            assert await s.nit(delay=0.2) == i

        # now do the same thing with a partial subdispatcher
        s = d.sub_at(P("r"))

        print("I80")
        res = []
        async with s.cmd(P("b.it"), lim=3, delay=0.2).stream_in() as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]

        print("I90")
        await s.b.clr()
        for i in range(1, 4):
            assert (await s.cmd(P("b.nit")))[0] == i
        print("I99")


@pytest.mark.parametrize("lossy", [False, True])
@pytest.mark.parametrize("guarded", [False, True])
async def test_modes(tmp_path, lossy, guarded):
    "test different link modes"
    cfu = dict(
        r=dict(
            link=dict(lossy=lossy, guarded=guarded),
            cfg=dict(r=dict(link=dict(lossy=lossy, guarded=guarded))),
        ),
    )
    async with mpy_stack(tmp_path, CFG, cfu) as d:
        res = await d.cmd(P("r.b.echo"), m="hi")
        assert res.kw == {"r": "hi"}


class Bar:
    "proxied test object"

    def __init__(self, x):
        self.x = x

    def __repr__(self):
        return f"{self.__class__.__name__}.x={self.x}"

    def __eq__(self, other):
        return self.x == other.x


@as_proxy("foo")
class Foo(Bar):
    "proxied test class"

    # pylint:disable=unnecessary-pass


LCFG = """
apps:
  a: _test.Cmd
  l: _test.LoopCmd
  _sys: _sys.Cmd
l:
  loop:
    qlen: 2
  link:
    pack: {}
  log:
    txt: "LOOP"
"""


@pytest.mark.parametrize("cons", [None, False, True])
async def test_eval(tmp_path, cons):
    "test proxying"
    cf2 = {} if cons is None else {"l": {"link": {"cons": cons}}}
    async with mpy_stack(tmp_path, LCFG, cf2) as d, d.sub_at(P("l._sys.eval")) as req:
        from pprint import pprint  # pylint:disable=import-outside-toplevel  # noqa: PLC0415

        dr = await d.cmd(P("l.dir_"))
        pprint(dr.kw)
        dr = await d.cmd(P("l._sys.dir_"))
        pprint(dr.kw)

        f = Foo(42)
        b = Bar(95)
        as_proxy("b", b, replace=True)

        await req(x=f, r=["foo"])
        await req(x=42, r=["foo", "x"])
        r = await req(x="foo", r=None)
        assert isinstance(r, Foo), r
        r = await req(x=(f, "x"))
        assert r == 42, r

        r = await req(x=b, r=None)
        assert r is b, r
        r = await req(x=(b, "x"))
        assert r == 95, r
        # await req(x=b, a=("b",))
        r = await req(x=(b,), r=False)
        assert r[0] == {"x": 95}
        assert not r[1]
        assert r[2] == "Bar"


async def test_msgpack(tmp_path):
    "test proxying"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r._sys.eval")) as req:
        from pprint import pprint  # pylint:disable=import-outside-toplevel  # noqa: PLC0415

        dr = await d.cmd(P("r.dir_"))
        pprint(dr.kw)
        dr = await d.cmd(P("r._sys.dir_"))
        pprint(dr.kw)

        f = Foo(42)
        b = Bar(95)
        as_proxy("b", b, replace=True)

        r = await req(x=f)
        assert isinstance(r, Foo), r
        r = await req(x=(f, "x"))
        assert r == 42, r

        r = await req(x=b, r=None)
        assert r is b
