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
from moat.util import to_attrdict

from . import mpy_server, mpy_client

async def test_ping(tmp_path):
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"

async def test_cfg(tmp_path):
    async with mpy_server(tmp_path) as obj:
        assert obj.server.cfg.tt.a == "b"
        obj.server.cfg.tt.a = "x"

        async with mpy_client(obj) as req:
            cfg = to_attrdict(await req.get_cfg())
            assert cfg.tt.a == "b"
            assert cfg.tt.c[1] == 2
