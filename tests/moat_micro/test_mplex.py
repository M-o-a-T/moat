"""
Empty test file
"""

from __future__ import annotations

import pytest

from moat.util import P, Path
from moat.micro._test import mpy_stack
from moat.util.compat import log, sleep_ms, ticks_diff, ticks_ms

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  a: _test.Cmd
  l: remote.Fwd
l:
  path: !P ":"
  log: LX
r:
  mplex: true
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
      l: remote.Fwd
    l:
      path: !P ":"
      log: RX
    r:
      link: &link
        lossy: false
        guarded: false
        frame: 0x85
        console: false
      log:
        txt: "!MH"
#     log_raw:
#       txt: "ML"

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
    # from moat.util._trio import hookup
    # hookup()

    conn = list(conn)
    async with mpy_stack(tmp_path, CFG) as d:
        res = []
        t1 = ticks_ms()
        async with d.cmd(Path(*conn) / "it", lim=3, delay=0.2).stream_in() as it:
            async for (n,) in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t1))
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t1))
        assert res == [0, 1, 2]
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 1200

        res = []
        async with d.cmd(Path(*conn) / "it", lim=5, delay=0.2).stream_in() as it:
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
            (n,) = await d.cmd(Path(*conn) / "nit", delay=0.2)
            assert n == i
        log("I X %d", ticks_diff(ticks_ms(), t1))
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 1350
