from __future__ import annotations

import anyio
import os
import pytest
import time

from moat.util import yload
from moat.micro._test import mpy_stack
from moat.util.compat import log
from moat.ems.battery.diy_serial.packet import RequestTiming

from .support import CF, as_attr

pytestmark = [pytest.mark.anyio, pytest.mark.xfail]

TT = 250  # XXX assume that this is OK


CFG1 = """
apps:
  s: _test.LoopLink
  c: bms._test.cell.Cell
  t: bms._test.CellSim
  bc: bms.diy_serial.Comm
bc:
  comm: !P s
t:
  cell: !P c
  ctrl: !P s
s:
  usage: bB
"""
CFG1 = as_attr(CFG1, c=CF.c)


async def test_cell1(tmp_path):
    "Basic fake cell verification"

    def tm():
        return int(time.monotonic() * 100000) & 0xFFFF

    async with mpy_stack(tmp_path, CFG1) as d, d.sub_at("s") as s, d.sub_at("bc") as bc:
        p = RequestTiming(timer=tm())
        x = (await bc(p=p, s=0))[0]
        td = (tm() - x.timer) & 0xFFFF
        print("Runtime", td / 100, "msec")


CFG4 = """
apps:
  s: _test.LoopLink
  ca: sub.Array
  t: bms._test.CellsSim
  bc: bms.diy_serial.Comm
bc:
  comm: !P s
t:
  cell: !P ca
  ctrl: !P s
  n: 4
s:
  usage: bB
ca:
  app: bms._test.cell.Cell
  n: 4

"""
CFG4 = as_attr(CFG4)
CFG4.ca.cfg = CF.c


async def test_cell4(tmp_path):
    "Basic fake cell verification"

    def tm():
        return int(time.monotonic() * 100000) & 0xFFFF

    async with mpy_stack(tmp_path, CFG4) as d, d.sub_at("s") as s, d.sub_at("bc") as bc:
        p = RequestTiming(timer=tm())
        x = await bc(p=p, s=0, bc=True)
        td = (tm() - x[-1].timer) & 0xFFFF
        print("Runtime", td / 100, "msec")
        assert len(x) == 4


CFGC1 = """
apps:
  s: _test.LoopLink
  c: bms._test.cell.DiyBMSCell
  t: bms._test.CellSim
  bo: bms.diy_serial.Comm
  bc: bms.diy_serial.Cell
bc:
  comm: !P bo
  pos: 0
bo:
  comm: !P s
t:
  cell: !P c
  ctrl: !P s
s:
  usage: bB
"""
CFGC1 = as_attr(CFGC1, c=CF.c, bc=CF.c)


async def test_cell_link1(tmp_path):
    "Basic fake cell verification via comm"
    async with mpy_stack(tmp_path, CFGC1) as d, d.sub_at("bc") as c, d.sub_at("c") as cx:
        assert await c.u() == 5
        assert await cx.u() == 5
        assert await cx.u(c=0.25) == 2
        assert abs(1.96 - await cx.u(c=0.20)) < 0.00001
        assert abs(1.64 - await cx.u(c=0.10)) < 0.00001
        assert abs(1.36 - await cx.u(c=0.05)) < 0.00001
        assert abs(1.0784 - await cx.u(c=0.01)) < 0.00001
        assert await cx.u(c=0.75) == 8
        assert await cx.u(c=1) == 9
        assert await cx.u(c=0) == 1
        assert abs(0.04 - await cx.u(c=-0.1)) < 0.00001

        # charge
        assert await cx.c() == 0.5
        assert 24.9 <= await c.t() <= 25.1
        await cx.add_p(p=100, t=100)
        assert await cx.c() == 0.505
        assert 25.0 <= await c.t() <= 25.15
        assert await cx.t() == 25.1
        assert await c.lim() == (1, 1)
        for _ in range(100):
            await cx.add_p(p=100, t=100)
            if await c.lim() != (1, 1):
                break
        else:
            raise RuntimeError("took too long")

        rc, rd = await c.lim()
        assert rd == 1
        assert abs(0.96 - rc) < 0.00001
        await cx.add_p(p=-200, t=100)

        # temperature
        for _ in range(200):
            if await c.lim() != (1, 1):
                break
            await cx.add_p(p=200, t=1000)
            await cx.add_p(p=-200, t=1000)
        else:
            raise RuntimeError("took too long")
        assert 40 < await c.t() < 40.1

        # discharge
        for _ in range(100):
            await cx.add_p(p=-100, t=100)
            if await c.lim() != (1, 1):
                break
        else:
            raise RuntimeError("took too long")
        assert await c.t() < 38

        rc, rd = await c.lim()
        assert rc == 1
        assert abs(0.96 - rd) < 0.001


CFGA = """
apps:
  b: bms._test.batt.Batt
  a: bms._test.batt.Bal
a:
  t:
    chk: 500
  h:
    n: 2
    d: 0.01
  u:
    min: 3.5
    max: 7.5
  bat: !P b
b:
  app: bms._test.cell.DiyBMSCell
  cfg: CFGA
  n: 4
  rnd: 0.2
  t:
    w: 500
"""
CFGA = as_attr(CFGA)
assert CFGA.b.cfg == "CFGA"
CFGA.b.cfg = CF.c


async def test_batt(tmp_path):
    "Basic BMS test"
    try:
        os.unlink("fake.rtc")
    except FileNotFoundError:
        pass
    async with mpy_stack(tmp_path, CFGA) as d, d.sub_at("b") as b, d.sub_at("a") as a:
        u = await b.u()
        assert u == 20.2  # 1% plus
        await b.i(100)
        while True:
            c, _ = await b.lim()
            if c < 0.1:
                break
            await anyio.sleep(0.05)
        await anyio.sleep(0.5)
        await b.i(0)
        # the battery is now (more than) "full"

        u = await b.u()
        assert u > 25  # 1% plus
        uu = await b.all("u")
        log("%r", uu)
        xu = max(uu)  # maX and miN-U
        nu = min(uu)
        assert xu > 8.3
        assert xu - nu > 0.01
        log(f"u={xu:.3f} … {nu:.3f}")

        # now start balancing to lowest cell
        await a.u(h=nu)
        await anyio.sleep(2)
        uu = await b.all("u")
        xu2 = max(uu)  # maX and miN-U
        nu2 = min(uu)  # maX and miN-U
        assert xu2 < xu
        assert nu - nu2 < 0.01  # we hope – vagaries of randomness
        log(f"u={xu2:.3f} … {nu2:.3f}")

        # continue until low voltage reached
        for _ in range(10):
            xux = xu2
            await anyio.sleep(2)
            uu = await b.all("u")
            xu2 = max(uu)  # maX and miN-U
            nu2 = min(uu)  # maX and miN-U
            if xu2 == xux:
                break
            log(f"u={xu2:.3f} … {nu2:.3f}")
        else:
            raise RuntimeError("Balance?")

        # ensure that balancing stops
        await anyio.sleep(2)
        uu = await b.all("u")
        xu3 = max(uu)  # maX and miN-U
        nu3 = min(uu)  # maX and miN-U
        assert xu2 == xu3
        assert nu2 == nu3
