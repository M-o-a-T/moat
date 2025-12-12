"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import P, yload
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  t: part.Transfer
  _sys: _sys.Cmd
  b: _test.Cmd
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      c: cfg.Cmd

      a: _test.Cmd
      b: _test.Cmd
      t: part.Transfer

      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
        frame: 0x85
      log:
        txt: "S"
    t:
      t: 0.1
      s:
      - p: !P a.nit
      # - p: !P a.echo
      - p: !P b.store

  link: *link
  log:
    txt: "M"

t:
  t: 0.1
  s:
  - p: !P r.a.nit
  # - p: !P r.a.echo
  - p: !P b.store
"""


async def test_store(tmp_path):
    "test basic store/retrieve"
    cfg = yload(CFG, attr=True)
    del cfg.apps.t
    del cfg.r.cfg.apps.t

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
    del cfg.r.cfg.apps.t

    async with (
        mpy_stack(tmp_path, cfg, run=True) as d,
        d.sub_at(P("b")) as xb,
    ):
        await anyio.sleep(1)
        res = await xb.store()
        assert 8 <= len(res) <= 11
        assert list(res) == list(range(1, len(res) + 1))


async def test_transfer_there(tmp_path):
    "test data foo"
    cfg = yload(CFG, attr=True)
    del cfg.apps.t

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.b")) as xb,
    ):
        await anyio.sleep(1)
        res = await xb.store()
        assert 9 <= len(res) <= 14
        assert res == list(range(1, len(res) + 1))
