"""
Basic test using a MicroPython subtask
"""
import pytest
from moat.micro._test import mpy_stack
from moat.util.compat import ticks_add, ticks_diff, ticks_ms

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK

CFGC = """
apps:
  c: bms._test.Cell
c:
  c: 0.5
  t: 25
  cap: 2000
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
        pass



async def xtest_bms(tmp_path):
    "Basic BMS test"
    ended = False
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            ended = True

            s = await req.send(["local", "bat1", "state"])
            print(s)

            t = ticks_add(ticks_ms(), -2000)
            for _ in range(3):
                res = await req.send(("local", "sq"), o=("bat1", "ui"))
                tn = ticks_ms()
                assert 1900 < ticks_diff(tn, t) < 2100, (tn, t)
                print(res)

    assert ended
