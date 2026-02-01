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
rtc:
  use:
  - _test
app:
  app: dir
  rtc:
    app: rtc.Cmd
  _sys:
    app: _sys.Cmd
  c:
    app: cfg.Cmd
  a:
    app: _test.Cmd
  r:
    app: _test.MpyCmd
    mplex: true
    cfg:
      rtc:
        use:
        - _test
      app:
        app: dir
        rtc:
          app: rtc.Cmd
        _sys:
          app: _sys.Cmd
        c:
          app: cfg.Cmd
        r:
          app: stdio.StdIO
          link: &link
            lossy: false
            guarded: false
            frame: 0x85
          log:
            txt: "S"
      tt: &tt
        a: b
        c:
          d: e
        z: 99

    link: *link
    log:
      txt: "M"

tt: *tt
"""


@pytest.mark.parametrize("remote", [False, True])
async def test_rtc(tmp_path, remote):
    "test basic RTC"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.rtc") if remote else P("rtc")) as rtc:
        await rtc("t1", "hello")
        await rtc("t2", {"Answer": 42})
        assert (await rtc("t1")) == "hello"
        assert (await rtc("t2"))["Answer"] == 42


@pytest.mark.parametrize("remote", [False, True])
async def test_rtc_cfg(tmp_path, remote):
    "test config updating"
    async with (
        mpy_stack(tmp_path, CFG) as d,
        d.cfg_at(P("r.c") if remote else P("c")) as cfg,
        d.cfg_at(P("r.rtc.cfg") if remote else P("rtc.cfg")) as rtc,
    ):
        cf = to_attrdict(await cfg.get())
        assert cf.tt.a == "b"
        assert cf.tt.c["d"] == "e"
        assert cf.tt.z == 99

        with pytest.raises(KeyError):
            rt = await rtc.get()
        rt = attrdict()
        rt.tt = attrdict()
        rt.tt.c = dict(d="f", g={"h": "i"})
        rt.tt.a = NotGiven
        await rtc.set(rt, sync=True, keep=True)

        cf = to_attrdict(await cfg.get(again=True))
        assert "a" not in cf.tt, cf.tt
        assert cf.tt.c.d == "f"
        assert cf.tt.c.g.h == "i"
        assert cf.tt.z == 99
