"""
Empty test file
"""

from __future__ import annotations

import pytest

from moat.micro._test import mpy_stack
from moat.util.compat import log, sleep_ms, ticks_diff, ticks_ms

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  a: _test.Cmd
r:
  mplex: true
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
    r:
      link: &link
        lossy: False
        guarded: False
      log:
        txt: "MH"
#     log_raw:
#       txt: "ML"

  link: *link
  log:
    txt: "TH"
# log_raw:
#   txt: "TL"
"""


async def test_mplex(tmp_path):
    """Basic multiplexer test"""
    async with mpy_stack(tmp_path, CFG) as d:
        r = await d.send("a", "echo", m="He")
        assert r["r"] == "He"
        r = await d.send("r", "b", "echo", m="Hi")
        assert r["r"] == "Hi"
        r = await d.send("r", "b", "echo", m="Ho")
        assert r["r"] == "Ho"
        r = await d.send("r", "r", "a", "echo", m="Hu")
        assert r["r"] == "Hu"


@pytest.mark.parametrize("conn", ["a", "rb", "rra"])
async def test_iter(tmp_path, conn):
    """Iterator test, direct"""
    conn = list(conn)
    async with mpy_stack(tmp_path, CFG) as d:
        res = []
        t1 = ticks_ms()
        async with d.send_iter(200, *conn, "it", lim=3) as it:
            async for n in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t1))
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t1))
        assert res == [0, 1, 2]
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 950

        res = []
        async with d.send_iter(200, *conn, "it") as it:
            async for n in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t2))
                if n == 3:
                    break
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t2))
        assert res == [0, 1, 2]
        t1 = ticks_ms()
        assert 450 < ticks_diff(t1, t2) < 950
        await sleep_ms(2000)
        t1 = ticks_ms()

        res = []
        async with d.send_iter(200, *conn, "nit", lim=3) as it:
            async for n in it:
                log("I %d %d", n, ticks_diff(ticks_ms(), t1))
                res.append(n)
        log("I X %d", ticks_diff(ticks_ms(), t1))
        assert res == [1, 2, 3]
        t2 = ticks_ms()
        assert 450 < ticks_diff(t2, t1) < 950
