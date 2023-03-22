"""
Some rudimentary tests for queues and broadcasting
"""

# pylint: disable=missing-function-docstring

import anyio
import pytest

from moat.util import Broadcaster, NotGiven, combine_dict, merge


@pytest.mark.anyio
async def test_basic():
    seen = [0, 0, 0]

    async def a(b, n):
        async for x in b:
            seen[n] |= x

    bq = Broadcaster()
    async with anyio.create_task_group() as tg, bq:
        tg.start_soon(a, bq, 0)
        await anyio.sleep(0.05)
        bq(1)
        await anyio.sleep(0.05)
        tg.start_soon(a, bq, 1)
        await anyio.sleep(0.05)
        bq(2)
        await anyio.sleep(0.05)
        tg.start_soon(a, bq, 2)
        await anyio.sleep(0.05)
        bq(4)
        await anyio.sleep(0.05)
    assert seen == [7, 6, 4]
