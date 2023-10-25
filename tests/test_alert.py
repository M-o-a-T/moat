"""
Test the relay implementation
"""
from __future__ import annotations

import pytest

from moat.micro._test import mpy_stack
from moat.micro.alert import Alert as _Alert

CFG = """
apps:
  a: link.Alert
  b: link.Alert
  c: link.Alert
a:
  app: _fake.Pin
  cfg: {}
  n: 3
  i: !P pin
  i_off: 1
  1:
    init: true

"""
# ruff: noqa:D101,D103

class Alert(_Alert):
    def __repr__(self):
        return f"{self.__class__.__name__}:{self._data !r}"


class AlertA(Alert):
    pass


class AlertB(Alert):
    pass


async def rd(x):
    res = []
    async with x.it_r(1,s=False) as it:
        async for r in it:
            res.append(r)
    return res


@pytest.mark.anyio
async def test_ary(tmp_path):
    "fake alert test"
    async with mpy_stack(tmp_path, CFG) as d:
        # ruff: noqa: F841
        a = d.sub_at("a")
        b = d.sub_at("b")
        c = d.sub_at("c")

        await a.w(a=AlertA, p=("x",), d={"a": "Foo"})
        n = 0
        #r = await rd(a)
        #assert r == []
