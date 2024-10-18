"""
Some rudimentary tests for queues and broadcasting
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

import anyio
import pytest

from moat.util import AlertCollector


@pytest.mark.anyio
async def test_collect():
    r = AlertCollector()
    async with r, anyio.create_task_group() as tg:
        busy = False

        async def chk(b):
            nonlocal busy
            await anyio.sleep(0.02)
            assert busy == b
            assert r.is_busy() == b

        async def runner():
            nonlocal busy
            while True:
                await r.wait_busy()
                busy = True
                await r.wait()
                busy = False

        tg.start_soon(runner)
        await anyio.sleep(0.01)
        a = anyio.Event()
        await chk(False)
        r.add(a)
        await chk(True)
        a.set()
        await chk(False)

        a = anyio.Event()
        r.add(a)
        await chk(True)
        b = anyio.Event()
        r.add(b)
        await chk(True)
        a.set()
        await chk(True)
        c = anyio.Event()
        r.add(c)
        await chk(True)
        b.set()
        await chk(True)
        c.set()
        await chk(False)
        tg.cancel_scope.cancel()
