"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import yload
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

CFG = """
app: dir
_sys:
  app: _sys.Cmd
b:
  app: _test.Cmd
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
      c:
        app: cfg.Cmd

      a:
        app: _test.Cmd
      b:
        app: _test.Cmd

      _sys:
        app: _sys.Cmd

      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0x85
        log:
          txt: "S"
      t:
        app: part.Transfer
        t: 100
        s:
        - p: !P a.nit
        # - p: !P a.echo
        - p: !P b.store

  link: *link
  log:
    txt: "M"

t:
  app: part.Transfer
  t: 100
  s:
  - p: !P r.a.nit
  # - p: !P r.a.echo
  - p: !P b.store
"""


async def test_store(tmp_path):
    "test basic store/retrieve"
    cfg = yload(CFG, attr=True)
    del cfg.t
    del cfg.r.cfg.app.t

    async with (
        rpc_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.a")) as xa,
    ):
        await xa.store(1, 2, 3)
        await xa.store(4)
        res = await xa.store()
        assert res == [1, 2, 3, 4]


async def _gather(xb, min_vals: int, timeout: float = 30) -> list:
    """Collect transferred values until at least @min_vals have arrived.

    The transfer ticks every 100 ms, but under load the stack may start
    slowly. Counting the samples produced in a fixed wall-time window is
    inherently flaky; waiting for a minimum count is not.
    """
    vals: list = []
    with anyio.fail_after(timeout):
        while len(vals) < min_vals:
            # _list=True: the reply may hold a single value, which the
            # default unpacking would collapse to a scalar.
            chunk = await xb.store(_list=True)
            vals.extend(chunk)
            if len(vals) < min_vals:
                await anyio.sleep(0.05)
    return vals


async def test_transfer_here(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.r.cfg.app.t

    async with (
        rpc_stack(tmp_path, cfg) as d,
        d.sub_at(P("b")) as xb,
    ):
        res = await _gather(xb, 5)
        assert res == list(range(1, len(res) + 1))


async def test_transfer_there(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.t

    async with (
        rpc_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.b")) as xb,
    ):
        res = await _gather(xb, 5)
        assert res == list(range(1, len(res) + 1))
