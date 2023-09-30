"""
Empty test file
"""

import sys
from moat.util import yload
import pytest
from moat.micro.cmd import Dispatch
from moat.micro.compat import Event, TaskGroup

from ._support import get_cfg

@pytest.mark.anyio
async def test_mplex():
    """
    Basic multiplex test
    """
    cfg = get_cfg(__name__)
    d = Dispatch(cfg)
    async with TaskGroup() as tg, d:
        r = await d.send("aecho",m="Hi")
        assert r["r"] == "Hi"
        r = await d.send("a","echo",m="Ho")
        assert r["r"] == "Ho"
        tg.cancel()

