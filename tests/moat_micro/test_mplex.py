"""
Empty test file
"""

from __future__ import annotations

import pytest

from moat.lib.micro import log, sleep_ms, ticks_diff, ticks_ms
from moat.lib.path import P, Path
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
app: dir
a:
  app: _test.Cmd
l:
  app: remote.Fwd
  path: !P ":"
  log: LX
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
#     w:
#       app: wdt.Cmd
      b:
        app: _test.Cmd
      l:
        app: remote.Fwd
        path: !P ":"
        log: RX
      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0x85
          console: false
        log:
          txt: "!MH"
#       log_raw:
#         txt: "ML"

  link: *link
  log:
    txt: "!TH"
# log_raw:
#   txt: "TL"
"""


async def test_mplex(tmp_path):
    """Basic multiplexer test"""
    async with mpy_stack(tmp_path, CFG) as d:
        r = await d.cmd(P("a.echo"), m="He")
        assert r["r"] == "He"
        r = await d.cmd(P("l.a.echo"), m="Hel")
        assert r["r"] == "Hel"
        r = await d.cmd(P("r.b.echo"), m="Hi")
        assert r["r"] == "Hi"
        r = await d.cmd(P("r.l.b.echo"), m="Hol")
        assert r["r"] == "Hol"
        r = await d.cmd(P("r.r.a.echo"), m="Hu")
        assert r["r"] == "Hu"
        r = await d.cmd(P("r.r.l.a.echo"), m="Hul")
        assert r["r"] == "Hul"


@pytest.mark.parametrize("conn", ["a", "la", "rlb", "rb", "rra"])
async def test_iter(tmp_path, conn):
    """Iterator test, direct"""
    conn = list(conn)
    async with mpy_stack(tmp_path, CFG) as d:
        res = []
        t1 = ticks_ms()
        async with d.cmd(Path.build(conn + ["it"]), lim=3, delay=0.2).stream_in() as it:
            async for (n,) in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t1))
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t1))
        assert res == [0, 1, 2]
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 1200

        res = []
        async with d.cmd(Path.build(conn + ["it"]), lim=5, delay=0.2).stream_in() as it:
            async for (n,) in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t2))
                if n == 3:
                    break
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t2))
        assert res == [0, 1, 2]
        t1 = ticks_ms()
        assert 450 < ticks_diff(t1, t2) < 1550
        await sleep_ms(500)
        t1 = ticks_ms()

        for i in range(1, 4):
            (n,) = await d.cmd(Path.build(conn + ["nit"]), delay=0.2)
            assert n == i
        log("I X %d", ticks_diff(ticks_ms(), t1))
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 1450
