from __future__ import annotations  # noqa: D100

import anyio
import pytest

from moat.lib.priomap import TimerMap


@pytest.mark.anyio
async def test_basic():  # noqa: D103
    h = TimerMap({"a": 0.01, "b": 0.03, "c": 0.08})
    assert len(h) == 3
    res = []

    async def reader():
        async for k in h:
            res.append(k)

    async with anyio.create_task_group() as tg:
        tg.start_soon(reader)
        await anyio.sleep(0.015)
        h["y"] = 0.025
        h["x"] = 0.01
        while h:  # noqa:ASYNC110
            await anyio.sleep(0.025)
        assert not h
        h["z"] = 0
        await anyio.sleep(0.01)
        tg.cancel_scope.cancel()

    assert "".join(res) == "axbycz"
