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
  rlink: !P baz.quux
"""


@pytest.mark.anyio
@pytest.mark.parametrize("seed", [1])  # range(10))
async def test_fake(seed, tmp_path, cfg):
    "basic random-walk ADC test"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init="Foo"),
        mpy_stack(tmp_path, CFG, dict(x=dict(seed=seed))) as ps,
        sf.client_() as cl,
        await cl.get_service(P("foo.bar")) as fb,
        cl.announcing(P("baz.quux"), host=False, service=cl.sub_at("d")) as ann,
    ):
        md = 0
        mdi = 0
        v = None
        ann.set()

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

        # This tests rlink
        # We do delayed lookup, so make sure it hasn't happened yet
        assert ps.sub["ln"].rlink is None

        se = ps.sender
        se.add_sub("ln")
        await se.ln.set(P("test:12"), 123)
        assert await cl.d_get(P("test:12")) == 123

        # make sure the lookup actually happened and nobody cheated
        assert ps.sub["ln"].rlink is not None
