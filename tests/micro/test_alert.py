"""
Test the relay implementation
"""

from __future__ import annotations

import pytest

from moat.micro._test import mpy_stack
from moat.micro.alert import Alert as _Alert
from moat.micro.compat import Event, L, TaskGroup, sleep_ms
from moat.util import P

CFG = """
apps:
  a: link.Alert
  b: link.Alert
  c: link.Alert
a:
  mon:
    b:
      rem: !P ":"
      al: !P b
    c:
      rem: !P c
      al: !P ":"

"""
# ruff: noqa:D101,D103


class Alert(_Alert):
    def __repr__(self):
        return f"{self.__class__.__name__}:{self.data!r}"


class AlertA(Alert):
    pass


class AlertB(Alert):
    pass


async def rd(x, s=False, evt=None):
    res = []
    async with x.it_r(1, s=s) as it:
        if evt is not None:
            evt.set()
        async for r in it:
            res.append(r)
    return res


@pytest.mark.anyio
async def test_ary(tmp_path):
    "fake alert test"
    async with mpy_stack(tmp_path, CFG) as d, TaskGroup() as tg:
        # ruff: noqa: F841
        a = d.sub_at(P("a"))
        b = d.sub_at(P("b"))
        c = d.sub_at(P("c"))

        if L:
            await d.wait_ready()
        await b.w(a=AlertA, p=("x",), d={"a": "Foo"})
        await sleep_ms(100)

        n = 0
        r = await rd(a, True)
        assert len(r) == 1
        assert r[0]["a"] is AlertA
        assert r[0]["d"]["a"] == "Foo"
        assert r[0]["p"] == ("x",)

        rbr = None
        rev = Event()

        async def moni(evt):
            nonlocal rbr
            rbr = await rd(a, s=None, evt=evt)
            rev.set()

        evt = Event()
        await tg.spawn(moni, evt)
        await evt.wait()
        await c.w(a=AlertB, p=("y", "z"), d={"a": "baR"})
        await sleep_ms(100)
        await a.cl()
        await rev.wait()

        assert len(rbr) == 2
        assert rbr[0]["a"] is AlertA
        assert rbr[0]["d"]["a"] == "Foo"
        assert rbr[0]["p"] == ("x",)
        assert rbr[1]["a"] is AlertB
        assert rbr[1]["d"]["a"] == "baR"
        assert rbr[1]["p"] == ("c", "y", "z")
