"""
Basic test using a MicroPython subtask
"""
import pytest
pytestmark = pytest.mark.anyio

import os
import sys
import anyio
from contextlib import asynccontextmanager

from moat.micro.compat import TaskGroup
from moat.micro.main import get_link

from . import mpy_server, mpy_client

async def test_start(tmp_path):
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
