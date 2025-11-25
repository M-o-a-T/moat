"""
Test the random-walk fake ADC
"""

from __future__ import annotations

import pytest

from moat.util import P
from moat.link._test import Scaffold
from moat.micro._test import mpy_stack

CFG = """
apps:
  x: _fake.ADC
  ln: link.Register
x:
  min: 0
  max: 100
  step: 10
ln:
  path: !P x
  link: !P foo.bar
"""


@pytest.mark.anyio
@pytest.mark.parametrize("seed", [1])  # range(10))
async def test_fake(seed, tmp_path, cfg):
    "basic random-walk ADC test"
    import moat  # noqa:PLC0415

    moat.cfg = cfg
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init="Foo"),
        mpy_stack(tmp_path, CFG, dict(x=dict(seed=seed))),
        sf.client_() as cl,
        await cl.get_service(P("foo.bar")) as fb,
    ):
        md = 0
        mdi = 0
        v = None
        for i in range(10):
            (vv,) = await fb.r()

            assert 0 < vv < 100
            if v is not None:
                vd = abs(vv - v)
                if vd > md:
                    md = vd
                    mdi = i
            v = vv
        assert 1 < md < 10, (md, mdi)
