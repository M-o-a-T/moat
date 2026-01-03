"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest
import sys

from moat.util import P
from moat.lib.micro import ACM, AC_exit, ticks_diff, ticks_ms
from moat.lib.proxy import as_proxy
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
        frame: 0x85
        console: false
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


def timed(t: int, min_: int, max_: int) -> int:
    """
    Check that the delta between this call and the last is between `min_` and
    `max_`.
    """
    t2 = ticks_ms()
    assert min_ <= ticks_diff(t2, t) <= max_

    return t2


async def test_iter_m(tmp_path):
    "basic iterator tests"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.b")) as drb:
        # await anyio.sleep(30)  ## attach gdb to micropython now
        t = ticks_ms()

        print("I00", file=sys.stderr)
        res = []
        async with d.cmd(P("r.b.it"), lim=3).stream_in() as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]
        t = timed(t, 300, 1200)

        if False:
            # This test currently crashes MPy
            print("I10", file=sys.stderr)
            res = []
            async with d.cmd(P("r.b.it")).stream_in() as it:
                async for (n,) in it:
                    if n == 3:
                        break
                    res.append(n)
            assert res == [0, 1, 2]
            t = timed(t, 450, 880)

        print("I20", file=sys.stderr)
        for i in range(1, 4):
            assert await drb.nit(0.1) == i
        t = timed(t, 300, 500)

        # now do the same thing with a subdispatcher
        s = d.sub_at(P("r.b"))

        print("I30", file=sys.stderr)
        res = []
        async with s.it.stream_in(delay=0.2, lim=3) as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]
        t = timed(t, 300, 880)

        print("I40", file=sys.stderr)
        await s.clr()
        for i in range(1, 4):
            assert await s.nit(delay=0.2) == i
        t = timed(t, 450, 1150)

        # now do the same thing with a partial subdispatcher
        s = d.sub_at(P("r"))

        print("I50", file=sys.stderr)
        res = []
        async with s.cmd(P("b.it"), lim=3, delay=0.2).stream_in() as it:
            async for (n,) in it:
                res.append(n)
        assert res == [0, 1, 2]
        t = timed(t, 300, 880)

        print("I60", file=sys.stderr)
        await s.b.clr()
        for i in range(1, 4):
            assert (await s.cmd(P("b.nit"), 0.1))[0] == i
        t = timed(t, 300, 500)

        print("I99", file=sys.stderr)
        t  # noqa:B018


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


# AC_use / ACM tests


class AsyncContextManagerTest:
    """Test async context manager for AC_use"""

    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self.value

    async def __aexit__(self, *exc):
        self.exited = True
        return False


class SyncContextManagerTest:
    """Test sync context manager for AC_use"""

    def __init__(self, value):
        self.value = value
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(self, *exc):
        self.exited = True
        return False


async def test_ac_use_async_context_manager():
    """Test AC_use with async context manager"""

    class TestObj:
        pass

    obj = TestObj()
    ctx = AsyncContextManagerTest("async_value")

    AC = ACM(obj)
    try:
        result = await AC(ctx)
        assert result == "async_value"
        assert ctx.entered is True
        assert ctx.exited is False
    except BaseException as exc:
        await AC_exit(obj, type(exc), exc, None)
        raise

    await AC_exit(obj)
    assert ctx.exited is True


async def test_ac_use_sync_context_manager():
    """Test AC_use with sync context manager"""

    class TestObj:
        pass

    obj = TestObj()
    ctx = SyncContextManagerTest("sync_value")

    AC = ACM(obj)
    try:
        result = await AC(ctx)
        assert result == "sync_value"
        assert ctx.entered is True
        assert ctx.exited is False
    except BaseException as exc:
        await AC_exit(obj, type(exc), exc, None)
        raise

    await AC_exit(obj)
    assert ctx.exited is True


async def test_ac_use_async_callable():
    """Test AC_use with async callable"""

    class TestObj:
        pass

    obj = TestObj()
    called = []

    async def async_callback():
        called.append("async")

    AC = ACM(obj)
    try:
        result = await AC(async_callback)
        assert result is None
        assert len(called) == 0  # Not called yet
    except BaseException as exc:
        await AC_exit(obj, type(exc), exc, None)
        raise

    await AC_exit(obj)
    assert called == ["async"]


async def test_ac_use_sync_callable():
    """Test AC_use with sync callable"""

    class TestObj:
        pass

    obj = TestObj()
    called = []

    def sync_callback():
        called.append("sync")

    AC = ACM(obj)
    try:
        result = await AC(sync_callback)
        assert result is None
        assert len(called) == 0  # Not called yet
    except BaseException as exc:
        await AC_exit(obj, type(exc), exc, None)
        raise

    await AC_exit(obj)
    assert called == ["sync"]


async def test_ac_use_nested_managers():
    """Test two managers attached to the same object"""

    class TestObj:
        pass

    obj = TestObj()
    ctx1 = AsyncContextManagerTest("value1")
    ctx2 = SyncContextManagerTest("value2")
    cleanup_order = []

    async def cleanup1():
        cleanup_order.append(1)

    def cleanup2():
        cleanup_order.append(2)

    # First ACM
    AC1 = ACM(obj)
    try:
        result1 = await AC1(ctx1)
        assert result1 == "value1"
        assert ctx1.entered is True
        await AC1(cleanup1)

        # Second ACM (nested)
        AC2 = ACM(obj)
        try:
            result2 = await AC2(ctx2)
            assert result2 == "value2"
            assert ctx2.entered is True
            await AC2(cleanup2)

            # Both contexts should be entered
            assert ctx1.entered is True
            assert ctx2.entered is True
            assert ctx1.exited is False
            assert ctx2.exited is False

        except BaseException as exc:
            await AC_exit(obj, type(exc), exc, None)
            raise

        # Exit second ACM
        await AC_exit(obj)
        assert ctx2.exited is True
        assert ctx1.exited is False  # First context still open

    except BaseException as exc:
        await AC_exit(obj, type(exc), exc, None)
        raise

    # Exit first ACM
    await AC_exit(obj)
    assert ctx1.exited is True

    # Cleanup should happen in reverse order (LIFO)
    assert cleanup_order == [2, 1]
