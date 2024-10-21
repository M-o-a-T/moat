from __future__ import annotations

import pytest
from tests.scaffold import scaffold

@pytest.mark.anyio
async def test_basic():
    async def handle(msg):
        assert tuple(msg.msg) == ("Test",123)
        return {"R":tuple(msg.msg)}
    async with scaffold(handle,None) as (a,b,tg):
        res, = await b.cmd("Test",123)
        assert res == {"R":("Test",123)}
        print("DONE")

