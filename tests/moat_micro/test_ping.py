"""
Test our ping thing
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import P
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  a: _test.Cmd
  p: ping.Cmd
  _sys: _sys.Cmd
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      c: cfg.Cmd
      p: ping.Cmd
      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
      log:
        txt: "S"
    tt:
      a: b
      c:
        d: e
      z: 99

  link: *link
  log:
    txt: "M"
p:
  d: 0.4
  t: 0.4
  p: !P r.p
  s: false

"""


async def test_ping(tmp_path):
    "test pinging"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.p")) as pi:
        rply = await pi(12, _list=...)
        assert rply[0] == 12
        await anyio.sleep(1)
