"""
Empty test file
"""

import sys
from moat.util import yload
import pytest
from moat.micro.compat import Event, TaskGroup
from moat.micro._test import mpy_stack

from ._support import get_cfg, Dispatch

@pytest.mark.anyio
async def test_mplex(tmp_path):
    """
    Basic multiplex test
    """
    cfg = get_cfg(__name__)
    d = Dispatch(cfg)
    async with mpy_stack(tmp_path,"mplex") as d:
        r = await d.send("rbecho",m="Hi")
        assert r["r"] == "Hi"
        r = await d.send("r","b","echo",m="Ho")
        assert r["r"] == "Ho"

