from __future__ import annotations

import anyio
import os
import pytest

from moat.util import yload
from moat.micro._test import mpy_stack
from moat.util.compat import log

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


def as_attr(d):  # noqa:D103
    return yload(d, attr=True)


"""
C definitions:
        -DSP_SENDLEN
        # verifies length

        -DSP_MAX_PACKET=5000
        # rather long

        -DSP_FRAME_START=0xFF
        # just the start bit
"""


CFG = """
apps:
  s: _test.LoopLink
  c: bms._test.Cell
  t: bms._test.CellSim
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

t:
  cell: !P c
  ctrl: !P s
s:
  usage: bB
"""
CFG = as_attr(CFG)


async def test_xmit(tmp_path):
    "Basic fake cell verification"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at("s") as s:
        await s.sb(b"12345")
        res = await s.rb()
        assert res == b'#12345'
