"""
Basic file system test, no multithreading / subprocess
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.micro.fuse import wrap

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

CFG = """
app: dir
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
      f:
        app: fs.Cmd
        root: "/tmp/nonexisting"
      r:
        app: stdio.StdIO
        link: &link
          frame: 0x85
          console: false
        log:
          txt: "S"
        log_raw:
          txt: "B"
  link: *link
  log:
    txt: "XD"
  log_raw:
    txt: "XB"
"""


async def test_fuse(tmp_path):
    "file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with rpc_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d:
        await p.mkdir()
        async with wrap(d.sub_at(P("r.f")), p, debug=4), await (p / "test").open("w") as f:
            n = await f.write("Fubar\n")
            assert n == 6
        st = await (r / "test").stat()
        assert st.st_size == n
