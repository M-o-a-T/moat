"""
Test the random-walk fake ADC
"""

from __future__ import annotations

import pytest

from moat.micro._test import mpy_stack
from moat.util import P

CFG = """
apps:
  x: _fake.ADC
x:
  min: 0
  max: 100
  step: 10
"""


@pytest.mark.anyio()
@pytest.mark.parametrize("seed", range(10))
async def test_fake(seed, tmp_path):
    "basic random-walk ADC test"
    async with mpy_stack(tmp_path, CFG, dict(x=dict(seed=seed))) as d:
        md = 0
        mdi = 0
        v = None
        for i in range(100):
            (vv,) = await d.cmd(P("x.r"))
            assert 0 < vv < 100
            if v is not None:
                vd = abs(vv - v)
                if vd > md:
                    md = vd
                    mdi = i
            v = vv
        assert 1 < md < 10, (md, mdi)
