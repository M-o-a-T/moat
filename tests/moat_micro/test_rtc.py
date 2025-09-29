"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, P, attrdict, to_attrdict
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
apps:
  r: _test.MpyCmd
  a: _test.Cmd
  _sys: _sys.Cmd
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      c: cfg.Cmd
      t: rtc.Cmd
      _sys: _sys.Cmd
    t:
      fake: true
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

"""


async def test_rtc(tmp_path):
    "test config updating"
    async with mpy_stack(tmp_path, CFG) as d, d.cfg_at(P("r.c")) as cfg, d.cfg_at(P("r.t")) as rtc:
        cf = to_attrdict(await cfg.get())
        rt = await rtc.get()
        assert cf.tt.a == "b"
        assert cf.tt.c["d"] == "e"
        assert cf.tt.z == 99

        rt["tt"] = attrdict()
        rt["tt"].c = dict(d="f", g={"h": "i"})
        rt["tt"].a = NotGiven
        await rtc.set(rt, replace=True, sync=True)

        cf = to_attrdict(await cfg.get(again=True))
        assert "a" not in cf.tt, cf.tt
        assert cf.tt.c.d == "f"
        assert cf.tt.c.g.h == "i"
        assert cf.tt.z == 99
