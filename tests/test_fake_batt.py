"""
Basic test using a MicroPython subtask
"""
import os
import pytest
import anyio
from moat.micro._test import mpy_stack
from moat.util.compat import ticks_add, ticks_diff, ticks_ms, log
from moat.util import yload

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK

def as_attr(d):
    return yload(d, attr=True)

CFGC = """
apps:
  c: bms._test.Cell
c:
  c: 0.5
  t: 25
  cap: 2000
  i:
    dis: -1
    chg: 0
  lim:
    t:
      abs:
        min: 0
        max: 45
      ext:
        min: 10
        max: 40
    c:
      min: 0.25
      max: 0.75
    p:  # exponent when 'ext' limit is exceeded
      min: 2
      max: 2
    u:
      abs:
        min: 1
        max: 9
      std:
        min: 3
        max: 7
      ext:
        min: 2
        max: 8
"""
CFGC = as_attr(CFGC)

async def test_cell(tmp_path):
    "Basic fake cell verification"
    async with mpy_stack(tmp_path, CFGC) as d, d.sub_at("c") as c:
        assert 5 == await c.u()
        assert 2 == await c.u(c=0.25)
        assert abs(1.96 - await c.u(c=0.20)) < 0.00001
        assert abs(1.64 - await c.u(c=0.10)) < 0.00001
        assert abs(1.36 - await c.u(c=0.05)) < 0.00001
        assert abs(1.0784 - await c.u(c=0.01)) < 0.00001
        assert 8 == await c.u(c=0.75)
        assert 9 == await c.u(c=1)
        assert 1 == await c.u(c=0)
        assert abs(0.04 - await c.u(c=-0.1)) < 0.00001

        # charge
        assert 0.5 == await c.c()
        assert 25 == await c.t()
        await c.add_p(p=100,t=100)
        assert 0.505 == await c.c()
        assert 25.1 == await c.t()
        assert (1,1) == await c.lim()
        for _ in range(100):
            await c.add_p(p=100,t=100)
            if (1,1) != await c.lim():
                break
        else:
            raise RuntimeError("took too long")

        rc,rd = await c.lim()
        assert rd == 1
        assert abs(0.96 - rc) < 0.00001
        await c.add_p(p=-200,t=100)

        # temperature
        for _ in range(200):
            if (1,1) != await c.lim():
                break
            await c.add_p(p=200,t=100)
            await c.add_p(p=-200,t=100)
        else:
            raise RuntimeError("took too long")
        assert 40 < await c.t() < 40.1

        # discharge
        for _ in range(100):
            await c.add_p(p=-100,t=100)
            if (1,1) != await c.lim():
                break
        else:
            raise RuntimeError("took too long")
        assert 38 > await c.t()

        rc,rd = await c.lim()
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
    ended = False
    try:
        os.unlink("fake.rtc")
    except FileNotFoundError:
        pass
    async with mpy_stack(tmp_path, CFGA) as d, d.sub_at("b") as b, d.sub_at("a") as a:
        u = await b.u()
        assert u == 20.2  # 1% plus
        await b.i(100)
        while True:
            c,d = await b.lim()
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
        assert xu-nu > 0.01
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
