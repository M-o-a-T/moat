"""
Test the random-walk fake ADC
"""
import pytest
from moat.util import attrdict

from moat.micro.part.fake import ADC
from moat.micro.test.cmd import Root


@pytest.mark.anyio
@pytest.mark.parametrize("seed", range(10))
async def test_fake(seed):
    "basic random-walk ADC test"
    d = ADC(Root(),"test", attrdict(min=0, max=100, step=10, seed=seed))
    md = 0
    mdi = 0
    v = None
    for i in range(100):
        vv = await d.cmd_r()
        assert 0 < vv < 100
        if v is not None:
            vd = abs(vv - v)
            if vd > md:
                md = vd
                mdi = i
        v = vv
    assert 1 < md < 10, (md, mdi)
