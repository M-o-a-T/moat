"""
Basic test using a MicroPython subtask
"""
import pytest

import anyio

from moat.micro._test import mpy_client, mpy_server
from moat.micro.fuse import wrap

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

async def test_fuse(tmp_path):
    "file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with mpy_server(tmp_path, cfg={"f": {"prefix": str(r)}}) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"
            await p.mkdir()
            async with wrap(req, p, debug=4):
                async with await (p / "test").open("w") as f:
                    n = await f.write("Fubar\n")
            st = await (r / "test").stat()
            assert st.st_size == n
