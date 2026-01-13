"""
Basic file system test, using commands directly
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

# pylint:disable=R0801 # Similar lines in 2 files

CFG = """
app: dir
r:
  app: _test.MpyCmd
  mplex: true
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
  link: *link
"""


async def test_fuse(tmp_path):
    "file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    async with mpy_stack(tmp_path, CFG, {"r": {"cfg": {"app": {"f": {"root": str(r)}}}}}) as d:
        await p.mkdir()
        async with d.sub_at(P("r.f")) as w:
            await w.new(p="test")
            f = await w.open(p="test", m="w")
            n = await w.wr(f=f, d="Fubar\n")
            await w.cl(f=f)
            assert n == 6
        st = await (r / "test").stat()
        assert st.st_size == n
