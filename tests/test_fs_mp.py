"""
Basic test using a MicroPython subtask
"""
import pytest

pytestmark = pytest.mark.anyio

import os
import sys

import anyio
from moat.util import NotGiven

from moat.micro._test import mpy_client, mpy_server
from moat.micro.compat import sleep_ms
from moat.micro.fuse import wrap

TT = 250  # XXX assume that this is OK

import multiprocessing as mp


async def test_fuse(tmp_path):
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with mpy_server(tmp_path, cfg={"f": {"prefix": str(r)}}) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            await p.mkdir()
            nn = -1
            async with wrap(req, p, debug=4):

                def fn(p):
                    with open(p, "w") as f:
                        n = f.write("Fubar\n")
                    return n

                def fx(p):
                    pp = mp.Process(target=fn, args=[str(p)])
                    nonlocal nn
                    n = pp.run()
                    return n

                n = await anyio.to_thread.run_sync(fx, str(p / "test.txt"))
            st = await (r / "test.txt").stat()
            assert st.st_size == 6  ## n
            print("XA", file=sys.stderr)
        print("XB", file=sys.stderr)
    print("XC", file=sys.stderr)
