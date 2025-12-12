"""
Basic file system test, using multithreading / subprocess
"""

from __future__ import annotations

import anyio
import multiprocessing as mp
import pytest

from moat.util import P
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
      link: &link
        frame: 0x85
        console: true
      log:
        txt: "S"
  link: *link
"""


async def test_fuse(tmp_path):
    "basic file system test"
    p = anyio.Path(tmp_path) / "fuse"
    r = anyio.Path(tmp_path) / "root"
    await p.mkdir()

    async with mpy_stack(tmp_path, CFG, {"r": {"cfg": {"f": {"root": str(r)}}}}) as d:
        async with wrap(d.sub_at(P("r.f")), p, debug=4):

            def fn(p):
                with open(p, "w") as f:
                    f.write("Fubar\n")

            def fx(p):
                pp = mp.Process(target=fn, args=[str(p)])
                pp.run()

            await anyio.to_thread.run_sync(fx, str(p / "test.txt"))
        st = await (r / "test.txt").stat()
        assert st.st_size == 6  # Fubar\n
