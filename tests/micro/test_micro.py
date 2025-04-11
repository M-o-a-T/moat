"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, as_proxy, to_attrdict, P
from moat.micro._test import mpy_stack
import anyio
from moat.util.compat import ticks_diff, ticks_ms

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
    async with mpy_stack(tmp_path, CFG) as d:
        # await anyio.sleep(30)  ## attach gdb to micropython now
        t1 = ticks_ms()

        res = []
        async with d.cmd(P("r.b.it"), lim=3).stream_in() as it:
            async for n, in it:
                res.append(n)
        assert res == [0, 1, 2]
        t2 = ticks_ms()
        assert 300 < ticks_diff(t2, t1) < 880

        res = []
        async with d.cmd(P("r.b.it")).stream_in() as it:
            async for n, in it:
                if n == 3:
                    break
                res.append(n)
        assert res == [0, 1, 2]
        t1 = ticks_ms()
        assert 450 < ticks_diff(t1, t2) < 880

        for i in range(1,4):
            assert (await d.cmd(P("r.b.nit")))[0] == i
        t2 = ticks_ms()
        assert 300 < ticks_diff(t2, t1) < 880

        # now do the same thing with a subdispatcher
        s = d.sub_at(P("r.b"))

        res = []
        async with s.it(delay=.2, lim=3).stream_in() as it:
            async for n, in it:
                res.append(n)
        assert res == [0, 1, 2]
        t1 = ticks_ms()
        assert 300 < ticks_diff(t1, t2) < 880

        await s.clr()
        for i in range(1,4):
            assert (await s.nit(delay=.2))[0] == i
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 1100

        # now do the same thing with a partial subdispatcher
        s = d.sub_at(P("r"))

        res = []
        async with s.cmd("b.it", lim=3, delay=.2).stream_in() as it:
            async for n, in it:
                res.append(n)
        assert res == [0, 1, 2]
        t1 = ticks_ms()
        assert 300 < ticks_diff(t1, t2) < 880

        await s.b.clr()
        for i in range(1,4):
            assert (await s.cmd(P("b.nit")))[0] == i
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 880


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
        res = await d.cmd("r.b.echo", m="hi")
        assert res.kw == {"r": "hi"}


async def test_cfg(tmp_path):
    "test config updating"
    async with mpy_stack(tmp_path, CFG) as d, d.cfg_at(P("r.c")) as cfg:
        cf = to_attrdict(await cfg.get())
        assert cf.tt.a == "b"
        cf.tt.a = "x"
        assert cf.tt.c[1] == 2
        assert cf.tt.z == 99

        await cfg.set({"tt": {"a": "d", "e": {"f": 42}, "z": NotGiven}})

        cf = to_attrdict(await cfg.get(again=True))
        assert cf.tt.a == "d"
        assert cf.tt.e.f == 42
        assert cf.tt.x == "y"
        assert "z" not in cf.tt


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
        from pprint import pprint  # pylint:disable=import-outside-toplevel

        dr = await d.cmd("l.dir_")
        pprint(dr.kw)
        dr = await d.cmd("l._sys", "dir_")
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
        from pprint import pprint  # pylint:disable=import-outside-toplevel

        dr = await d.send("r", "dir_")
        pprint(dr)
        dr = await d.send("r", "_sys", "dir_")
        pprint(dr)

        f = Foo(42)
        b = Bar(95)
        as_proxy("b", b, replace=True)

        r = await req(x=f)
        assert isinstance(r, Foo), r
        r = await req(x=(f, "x"))
        assert r == 42, r

        r = await req(x=b, r=None)
        assert r is b
