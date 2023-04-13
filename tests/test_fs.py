"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

import os
import sys

import anyio

from moat.micro._test import mpy_client, mpy_server
from moat.micro.fuse import wrap
from moat.micro.compat import sleep_ms
from moat.util import NotGiven

TT=250  # XXX assume that this is OK

async def test_fuse(tmp_path):
    with pytest.raises(EOFError):
        async with mpy_server(tmp_path) as obj:
            async with mpy_client(obj) as req:
                res = await req.send("ping", "hello")
                assert res == "R:hello"
                p = anyio.Path(tmp_path) / "fuse"
                r = anyio.Path(tmp_path) / "root"
                await p.mkdir()
                async with wrap(req,p,debug=4):
                    async with await (p/"test").open("w") as f:
                        n = await f.write("Fubar\n")
                st = await (r/"test").stat()
                assert st.size == n

