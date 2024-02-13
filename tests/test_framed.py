from __future__ import annotations

import anyio
import os
import pytest

from moat.util import yload
from moat.micro._test import mpy_stack
from moat.util.compat import log

from .support import as_attr,CF

pytestmark = pytest.mark.anyio

TT = 250  # XXX assume that this is OK


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
t:
  cell: !P c
  ctrl: !P s
s:
  usage: bB
"""
CFG = as_attr(CFG, c=CF.c)


async def test_xmit(tmp_path):
    "Basic fake cell verification"
    async with mpy_stack(tmp_path, CFG) as d, d.sub_at("s") as s:
        await s.sb(b"12345")
        res = await s.rb()
        assert res == b'#12345'
