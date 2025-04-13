"""
Basic file system test, using commands directly
"""

from __future__ import annotations

import anyio
import pytest

from moat.micro._test import mpy_stack
from moat.util import P

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
        #async with d.sub_at(P("r.f")) as w:
        w= d.sub_at(P("r.f"))
        if True:
            await w.new(p="test")
            f = await w.open(p="test", m="w")
            n = await w.wr(f=f, d="Fubar\n")
            await w.cl(f=f)
            assert n == 6
        st = await (r / "test").stat()
        assert st.st_size == n
