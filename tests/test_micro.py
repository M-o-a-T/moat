"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

import os
import sys
from contextlib import asynccontextmanager

import anyio
from moat.util import to_attrdict

from moat.micro.compat import TaskGroup
from moat.micro.main import get_link

from . import mpy_client, mpy_server


async def test_ping(tmp_path):
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"


@pytest.mark.parametrize("lossy",[False,True])
@pytest.mark.parametrize("guarded",[False,True])
async def test_modes(tmp_path, lossy,guarded):
    async with mpy_server(tmp_path, lossy=lossy, guarded=guarded) as obj:
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

            await req.set_cfg({"tt": {"a": "d", "e": {"f": 42}}})

        async with mpy_client(obj) as req:
            cfg = to_attrdict(await req.get_cfg())
            assert cfg.tt.a == "d"
            assert cfg.tt.e.f == 42
            assert cfg.tt.x == "y"
