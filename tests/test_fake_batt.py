"""
Basic test using a MicroPython subtask
"""
from __future__ import annotations

import anyio
import os
import pytest

from moat.util import yload
from moat.micro._test import mpy_stack
from moat.util.compat import log

from.support import as_attr,CF

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


CFGC = """
apps:
  c: bms._test.Cell
"""
CFGC = as_attr(CFGC, c=CF.c)


async def test_cell(tmp_path):
    "Basic fake cell verification"
    async with mpy_stack(tmp_path, CFGC) as d, d.sub_at("c") as c:
        assert await c.u() == 5
        assert await c.u(c=0.25) == 2
        assert abs(1.96 - await c.u(c=0.20)) < 0.00001
        assert abs(1.64 - await c.u(c=0.10)) < 0.00001
        assert abs(1.36 - await c.u(c=0.05)) < 0.00001
        assert abs(1.0784 - await c.u(c=0.01)) < 0.00001
        assert await c.u(c=0.75) == 8
        assert await c.u(c=1) == 9
        assert await c.u(c=0) == 1
        assert abs(0.04 - await c.u(c=-0.1)) < 0.00001

        # charge
        assert await c.c() == 0.5
        assert await c.t() == 25
        await c.add_p(p=100, t=100)
        assert await c.c() == 0.505
        assert await c.t() == 25.1
        assert await c.lim() == (1, 1)
        for _ in range(100):
            await c.add_p(p=100, t=100)
            if await c.lim() != (1, 1):
                break
        else:
            raise RuntimeError("took too long")

        rc, rd = await c.lim()
        assert rd == 1
        assert abs(0.96 - rc) < 0.00001
        await c.add_p(p=-200, t=100)

        # temperature
        for _ in range(200):
            if await c.lim() != (1, 1):
                break
            await c.add_p(p=200, t=1000)
            await c.add_p(p=-200, t=1000)
        else:
            raise RuntimeError("took too long")
        assert 40 < await c.t() < 40.1

        # discharge
        for _ in range(100):
            await c.add_p(p=-100, t=100)
            if await c.lim() != (1, 1):
                break
        else:
            raise RuntimeError("took too long")
        assert await c.t() < 38

        rc, rd = await c.lim()
        assert rc == 1
        assert abs(0.96 - rd) < 0.00001


CFGA = """
apps:
  b: bms._test.Batt
  a: bms._test.Bal
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
  app: bms._test.Cell
  cfg: CFGA
  n: 4
  rnd: 0.2
  t:
    w: 500
"""
CFGA = as_attr(CFGA)
assert CFGA.b.cfg == "CFGA"
CFGA.b.cfg = CFGC.c


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
        log(f"u={xu :.3f} … {nu :.3f}")

        # now start balancing to lowest cell
        await a.u(h=nu)
        await anyio.sleep(2)
        uu = await b.all("u")
        xu2 = max(uu)  # maX and miN-U
        nu2 = min(uu)  # maX and miN-U
        assert xu2 < xu
        assert nu - nu2 < 0.01  # we hope – vagaries of randomness
        log(f"u={xu2 :.3f} … {nu2 :.3f}")

        # continue until low voltage reached
        for _ in range(10):
            xux = xu2
            await anyio.sleep(2)
            uu = await b.all("u")
            xu2 = max(uu)  # maX and miN-U
            nu2 = min(uu)  # maX and miN-U
            if xu2 == xux:
                break
            log(f"u={xu2 :.3f} … {nu2 :.3f}")
        else:
            raise RuntimeError("Balance?")

        # ensure that balancing stops
        await anyio.sleep(2)
        uu = await b.all("u")
        xu3 = max(uu)  # maX and miN-U
        nu3 = min(uu)  # maX and miN-U
        assert xu2 == xu3
        assert nu2 == nu3
