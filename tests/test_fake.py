import pytest
from moat.util import attrdict

from moat.micro.part.fake import ADC


@pytest.mark.anyio
@pytest.mark.parametrize("seed", range(10))
async def test_fake(seed):
    d = ADC(attrdict(min=0, max=100, step=10, seed=seed))
    md = 0
    mdi = 0
    v = None
    for i in range(100):
        vv = await d.read()
        assert 0 < vv < 100
        if v is not None:
            vd = abs(vv - v)
            if vd > md:
                md = vd
                mdi = i
        v = vv
    assert 1 < md < 10, (md, mdi)
