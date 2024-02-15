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

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


CFG1 = """
apps:
  s: _test.LoopLink
  c: bms._test.Cell
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
        return int(time.monotonic()*100000)&0xFFFF
    async with mpy_stack(tmp_path, CFG1) as d, d.sub_at("s") as s, d.sub_at("bc") as bc:
        p = RequestTiming(timer=tm())
        x = await bc(p=p,s=0)
        td = (tm()-x[1][0].timer)&0xFFFF
        print("Runtime",td/100,"msec")

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
  app: bms._test.Cell
  n: 4

"""
CFG4 = as_attr(CFG4)
CFG4.ca.cfg=CF.c

async def test_cell4(tmp_path):
    "Basic fake cell verification"
    def tm():
        return int(time.monotonic()*100000)&0xFFFF
    async with mpy_stack(tmp_path, CFG4) as d, d.sub_at("s") as s, d.sub_at("bc") as bc:
        p = RequestTiming(timer=tm())
        x = await bc(p=p,s=0,bc=True)
        td = (tm()-x[1][0].timer)&0xFFFF
        print("Runtime",td/100,"msec")
        assert len(x[1]) == 4


