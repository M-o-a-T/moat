"""
Basic test using a MicroPython subtask
"""

from __future__ import annotations

import pytest

from moat.util import attrdict, ungroup, yload
from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.micro._test import mpy_stack
from moat.micro.app._test_ import UserCrash
from moat.src.test import raises

pytestmark = pytest.mark.anyio

TT = 100  # XXX depends on how much we're logging

CFG = """
app: log.Cmd
cfg:
  app: dir
  # r: _test.MpyCmd
  a: &err
    app: sub.Err
    cfg:
      app: _test.Cmd
    retry: 3
    timeout: 150
  r:
    app: _test.MpyCmd
    mplex: true
    cfg:
      app:
        app: dir
        b: *err
        c:
          app: cfg.Cmd
        r:
          app: stdio.StdIO
          link: &link
            lossy: false
            guarded: false
            frame: 0x85
#         log:
#           txt: "MH"
#         log_raw:
#           txt: "ML"

    link: *link
#   log:
#     txt: "TH"
#   log_raw:
#     txt: "TL"
"""


@pytest.mark.parametrize("remote", [False, True])
async def test_crash(tmp_path, remote):
    "basic error handling test"
    ended = False
    cfg = yload(CFG, attr=True)
    cfg.cfg.a = attrdict(app="_test.Cmd")
    cfg.cfg.r.cfg.app.b = attrdict(app="_test.Cmd")
    with raises(Exception) as exc, ungroup:
        async with (
            mpy_stack(tmp_path, cfg) as d,
            d.sub_at(P("r.b" if remote else "a")) as r,
        ):
            res = await r.echo(m="hello")
            assert res == dict(r="hello")
            await r.crash()
            await sleep_ms(TT / 2)
            res = await r.echo(m="hello")
            ended = True
            await sleep_ms(TT)
            res = await r.echo(m="hello")
    if not remote:
        assert isinstance(ungroup.one(exc.value.split(UserCrash)[0]), UserCrash)
    assert ended


@pytest.mark.parametrize("remote", [False, True])
async def test_err(tmp_path, remote):
    "basic error handling test"
    n = 0
    cfg = yload(CFG, attr=True)
    cfg.cfg.a.timeout = TT * 3 / 2
    cfg.cfg.r.cfg.app.b.timeout = int(TT * 3 / 2)
    with raises(Exception):
        async with (
            mpy_stack(tmp_path, cfg) as d,
            d.sub_at(P("r.b" if remote else "a")) as r,
        ):
            while True:
                await r.rdy_()
                res = await r.echo(m="hello")
                assert res == dict(r="hello")
                await r.crash()

                await sleep_ms(TT * 4)  # remote can be rather slow
                n += 1
    assert n == 3
