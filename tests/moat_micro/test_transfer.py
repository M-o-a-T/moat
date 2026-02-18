"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import yload
from moat.lib.path import P
from moat.micro._test import mpy_stack

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
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.a")) as xa,
    ):
        await xa.store(1, 2, 3)
        await xa.store(4)
        res = await xa.store()
        assert res == [1, 2, 3, 4]


async def test_transfer_here(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.r.cfg.app.t

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("b")) as xb,
    ):
        await anyio.sleep(1)
        res = await xb.store()
        assert 8 <= len(res) <= 11
        assert list(res) == list(range(1, len(res) + 1))


async def test_transfer_there(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.t

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.b")) as xb,
    ):
        await anyio.sleep(1)
        res = await xb.store()
        assert 9 <= len(res) <= 14
        assert res == list(range(1, len(res) + 1))
