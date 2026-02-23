"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, to_attrdict
from moat.lib.path import P, Path
from moat.lib.rpc._test import rpc_stack

pytestmark = pytest.mark.anyio

CFG = """
app:
  app: dir
  a:
    app: _test.Cmd
  _sys:
    app: _sys.Cmd
  c:
    app: cfg.Cmd
  l:
    app: _test.LoopCmd
    loop:
      qlen: 2
    link: {}
    log:
      txt: "LOOP"
  r:
    app: _test.MpyCmd
    cfg:
      app:
        app: dir
        # w:
        # app: wdt.Cmd
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
      txt: "!TH"
  # log_rel:
  #   txt: "TR"

tt:
  a: b
  c: [1,2,3]
  x: y
  z: 99
"""


@pytest.mark.parametrize("local", [True, False])
async def test_cfg(tmp_path, local: bool):
    "test config updating"
    async with (
        rpc_stack(tmp_path, CFG) as d,
        d.sub_at(P("c" if local else "r.c")) as cfx,
        cfx.cfg_at(Path()) as cfg,
    ):
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

        await cfg.set({"ta": []})
        await cfx.c(P("ta:0"), "One")
        await cfx.c(P("ta:n"), "Two")
        await cfx.c(P("ta:2"), "Three")
        cf = to_attrdict(await cfg.get(again=True))
        assert cf.ta == ["One", "Two", "Three"]
        with pytest.raises(IndexError):
            await cfx.c(P("ta:4"), "Five")
