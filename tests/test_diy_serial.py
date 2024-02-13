from __future__ import annotations

import anyio
import os
import pytest

from moat.util import yload
from moat.micro._test import mpy_stack
from moat.util.compat import log
from moat.ems.battery.diy_serial.packet import RequestTiming

from .support import CF, as_attr

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


CFG = """
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
CFG = as_attr(CFG, c=CF.c)

async def test_xmit(tmp_path):
    "Basic fake cell verification"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at("s") as s, d.sub_at("bc") as bc:
        p = RequestTiming(timer=0)
        x = await bc(p=p,s=0)
        print(x)
