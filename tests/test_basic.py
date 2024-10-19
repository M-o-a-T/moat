from __future__ import annotations

import pytest
from tests.scaffold import scaffold

@pytest.mark.anyio
async def test_basic():
    async with scaffold() as (a,b,tg):
        async def handle(msg):
            assert msg.cmd == ("Test",123)
            return {"R":msg.cmd}
        tg.start_soon(a.dispatch,handle)
        tg.start_soon(b.dispatch,handle)

        res, = await a.cmd("Test",123)
        assert res == {"R":("Test",123)}
        print("DONE")

