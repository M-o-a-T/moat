"""
Test our (fake) RTC
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, attrdict, to_attrdict
from moat.lib.path import P
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
app: dir
_sys:
  app: _sys.Cmd
a:
  app: _test.Cmd
r:
  app: _test.MpyCmd
  mplex: true
  cfg:
    app:
      app: dir
      _sys:
        app: _sys.Cmd
      c:
        app: cfg.Cmd
      t:
        app: rtc.Cmd
        fake: true
      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0x85
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
