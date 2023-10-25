"""
Some rudimentary tests for queues and broadcasting
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import anyio
import pytest

from moat.util.broadcast import Broadcaster, LostData


@pytest.mark.anyio()
async def test_basic():
    seen = [0, 0, 0]

    async def a(b, n):
        await anyio.sleep(0.1 * (2 * n + 3))
        x = 128
        while True:
            try:
                x = await anext(b)
            except StopAsyncIteration:
                break
            except LostData as exc:
                seen[n] |= exc.n << 4
            else:
                seen[n] |= x

    bq = Broadcaster(1)
    async with anyio.create_task_group() as tg, bq:
        tg.start_soon(a, aiter(bq), 0)
        await anyio.sleep(0.1)
        bq(1)
        await anyio.sleep(0.1)
        tg.start_soon(a, aiter(bq), 1)
        await anyio.sleep(0.1)
        bq(2)
        await anyio.sleep(0.1)
        tg.start_soon(a, aiter(bq), 2)
        await anyio.sleep(0.1)
        bq(4)
        # no delay here
    assert seen == [7, 20, 4]
