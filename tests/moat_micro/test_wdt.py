"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven, P
from moat.micro._test import mpy_stack
from moat.src.test import raises
from moat.util.compat import log, sleep_ms

pytestmark = pytest.mark.anyio

TT = 500  # XXX depends on how much we're logging

CFG = """
apps:
# r: _test.MpyCmd
  r: sub.Err
  a: _test.Cmd
r:
 app: _test.MpyCmd
 cfg:
  mplex: true
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
      c: cfg.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
        frame: 0x85
      log:
        txt: "MH"
      log_raw:
        txt: "ML"

  link: *link
  log:
    txt: "TH"
  log_raw:
    txt: "TL"
"""


@pytest.mark.parametrize("guard", [False, True])
async def test_wdt(tmp_path, guard):
    "basic watchdog test"
    ended = False
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.b")) as r, d.cfg_at(P("r.c")) as c:
        res = await r.echo(m="hello")
        assert res == dict(r="hello")

        # XXX unfortunately we can't test ext=False or hw=True on Linux
        await c.set(
            {
                "apps": {"w": "sub.Err"},
                "w": dict(app="wdt.Cmd", cfg=dict(t=TT, ext=True, hw=False)),
            }
            if guard
            else {
                "apps": {"w": "wdt.Cmd"},
                "w": dict(t=TT, ext=True, hw=False),
            },
            sync=True,
        )
        async with d.sub_at(P("r.w")) as wd:
            await sleep_ms(TT / 2)
            await wd.x(n=1)
            await sleep_ms(TT / 2)
            await wd.x(n=2)
            ended = True
            log("Waiting for the watchdog to trigger")
            await sleep_ms(TT * 1.5)
            with raises(EOFError):
                res = await r.echo(m="hello")
    assert ended


async def test_wdt_off(tmp_path):
    """
    Check that the watchdog can be removed
    """
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.b")) as r, d.cfg_at(P("r.c")) as c:
        await c.set(
            {
                "apps": {"w1": "wdt.Cmd"},
                "w1": dict(t=TT * 2, ext=True, hw=False),
            },
            sync=True,
        )
        async with d.sub_at(P("r.w1")) as wd:
            await sleep_ms(TT)
            await wd.x()
            await sleep_ms(TT)
            await wd.x()
        await c.set(
            {
                "apps": {"w1": NotGiven},
            },
            sync=True,
        )
        await sleep_ms(TT * 3)

        res = await r.echo(m="hello again")
        assert res == dict(r="hello again")
        ended = True
    assert ended


async def test_wdt_update(tmp_path):
    """
    Check that the watchdog can be updated
    """
    ended = False
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at(P("r.b")) as r, d.cfg_at(P("r.c")) as c:
        await c.set(
            {
                "apps": {"w": "wdt.Cmd"},
                "w": dict(t=TT * 2, ext=True, hw=False),
            },
            sync=True,
        )

        async with d.sub_at(P("r.w")) as wd:
            await sleep_ms(TT)
            await wd.x(n=1)
            await sleep_ms(TT)
            await wd.x(n=2)
            await c.set({"w": dict(t=TT * 4)}, sync=True)
            await wd.x(n=3)
            await sleep_ms(TT * 3)
            await wd.x(n=4)
            await sleep_ms(TT * 3)
            await wd.x(n=5)
            ended = True
            await sleep_ms(TT * 5)

            with raises(EOFError):
                await r.echo(m="hello")
    assert ended
