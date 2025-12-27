"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import suppress

from moat.util import P, yload
from moat.lib.micro import CancelledError
from moat.lib.rpc import NoStream
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  p: part.Average
  _sys: _sys.Cmd
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      c: cfg.Cmd
      p: part.Average
      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
        frame: 0x85
      log:
        txt: "S"
    p:
      t: 10

  link: *link
  log:
    txt: "M"
p:
  t: 10

"""


async def run_avg(xa):
    "generic averaging test"
    async with anyio.create_task_group() as tg:

        async def snd():
            await anyio.sleep(0.05)
            await xa.w(1, t=0)
            await anyio.sleep(0.05)
            await xa.w(2, t=1000)
            await anyio.sleep(0.05)
            await xa.w(3, t=1000)
            await anyio.sleep(0.05)
            await xa.w(3, t=10000)
            await anyio.sleep(0.05)
            await xa.w(1, t=10000)
            await anyio.sleep(0.05)
            await xa.w(3, t=1000)
            await anyio.sleep(0.05)
            await xa.w(3, t=99000)

        tg.start_soon(snd)
        with suppress(NoStream):
            async with xa.r.stream_in() as mon:
                mon = aiter(mon)
                print(1, await anext(mon))
                print(2, await anext(mon))
                print(3, await anext(mon))
                print(4, await anext(mon))
                print(5, await anext(mon))
                print(6, await anext(mon))


async def test_avg_here(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.r.cfg.apps.p

    async with (
        mpy_stack(tmp_path, cfg, run=True) as d,
        d.sub_at(P("p")) as xa,
    ):
        await run_avg(xa)


async def test_avg_there(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.apps.p

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.p")) as xa,
    ):
        with suppress(CancelledError):
            await run_avg(xa)
