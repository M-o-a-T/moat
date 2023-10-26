"""
Basic file system test, no multithreading / subprocess
"""
from __future__ import annotations

import anyio
import pytest

from moat.micro._test import mpy_stack
from moat.micro.fuse import wrap

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

CFG = """
apps:
  r: _test.MpyCmd
r:
  mplex: true
  cfg:
    apps:
      r: stdio.StdIO
      f: fs.Cmd
    f:
      root: "/tmp/nonexisting"
    r:
      log:
        txt: "S"
"""


async def test_fuse(tmp_path):
    "file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with mpy_stack(tmp_path, CFG, {"r": {"cfg": {"f": {"root": str(r)}}}}) as d:
        await p.mkdir()
        async with wrap(d.sub_at("r", "f"), p, debug=4), \
                await (p / "test").open("w") as f:
            n = await f.write("Fubar\n")
            assert n == 6
        st = await (r / "test").stat()
        assert st.st_size == n
