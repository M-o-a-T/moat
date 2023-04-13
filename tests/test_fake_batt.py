"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

import os
import sys

import anyio

from moat.micro._test import mpy_client, mpy_server
from moat.micro.compat import sleep_ms
from moat.util import NotGiven

TT=250  # XXX assume that this is OK

async def test_bms(tmp_path):
    ended = False
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            ended = True

    assert ended

