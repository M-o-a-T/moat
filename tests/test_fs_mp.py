"""
Basic test using a MicroPython subtask
"""
import pytest

import anyio

from moat.micro._test import mpy_client, mpy_server
from moat.micro.fuse import wrap

import multiprocessing as mp

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

async def test_fuse(tmp_path):
    "basic file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with mpy_server(tmp_path, cfg={"f": {"prefix": str(r)}}) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            await p.mkdir()
            async with wrap(req, p, debug=4):

                def fn(p):
                    with open(p, "w") as f:
                        f.write("Fubar\n")

                def fx(p):
                    pp = mp.Process(target=fn, args=[str(p)])
                    pp.run()

                await anyio.to_thread.run_sync(fx, str(p / "test.txt"))
            st = await (r / "test.txt").stat()
            assert st.st_size == 6  # Fubar\n
