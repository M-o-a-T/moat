"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, to_attrdict
from moat.lib.path import P
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG = """
app: dir
a:
  app: _test.Cmd
_sys:
  app: _sys.Cmd
l:
  app: _test.LoopCmd
  loop:
    qlen: 2
  link: {}
  log:
    txt: "LOOP"
r:
  app: _test.MpyCmd
  mplex: true
  cfg:
    app:
      app: dir
  #   w:
        app: wdt.Cmd
      b:
        app: _test.Cmd
      c:
        app: cfg.Cmd
      _sys:
        app: _sys.Cmd
      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0xFA
          console: true
        log:
          txt: "MH"
        log_raw:
          txt: "ML"
        log_rel:
          txt: "MR"
      tt:
        a: b
        c: [1,2,3]
        x: y
        z: 99

  link: *link
  log:
    txt: "TH"
# log_rel:
#   txt: "TR"

"""


async def test_cfg(tmp_path):
    "test config updating"
    async with mpy_stack(tmp_path, CFG) as d, d.cfg_at(P("r.c")) as cfg:
        cf = to_attrdict(await cfg.get())
        assert cf.tt.a == "b"
        cf.tt.a = "x"
        assert cf.tt.c[1] == 2
        assert cf.tt.z == 99

        await cfg.set({"tt": {"a": "d", "e": {"f": 42}, "z": NotGiven}})

        cf = to_attrdict(await cfg.get(again=True))
        assert cf.tt.a == "d"
        assert cf.tt.e.f == 42
        assert cf.tt.x == "y"
        assert "z" not in cf.tt
