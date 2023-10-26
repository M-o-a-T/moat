"""
Test the "every" iterator
"""
from __future__ import annotations

import pytest
import time

from moat.micro.compat import every_ms


@pytest.mark.anyio()
async def test_it():
    "'every' iterator test"
    nn = 0

    async def rr():
        for x in range(5):
            yield x

    rep = aiter(rr())
    t1 = time.monotonic()
    async for n in every_ms(100, anext, rep):
        assert nn == n
        nn += 1
    assert nn == 5
    t2 = time.monotonic()
    assert 0.499 <= t2 - t1 <= 0.701
