"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

CFG = """
app: dir
_sys:
  app: _sys.Cmd
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
      c:
        app: cfg.Cmd
      p:
        app: ping.Cmd
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

  link: *link
  log:
    txt: "M"
a:
  app: _test.Cmd
p:
  app: ping.Cmd
  d: 0.4
  t: 0.4
  p: !P r.p
  s: false

"""


async def test_ping(tmp_path):
    "test pinging"
    async with rpc_stack(tmp_path, CFG) as d, d.sub_at(P("r.p")) as pi:
        rply = await pi(12, _list=...)
        assert rply[0] == 12
        await anyio.sleep(1)
