"""
Connection tests
"""

from __future__ import annotations

import anyio
import pytest
import sys

from moat.util import P, attrdict, yload
from moat.micro._test import mpy_stack
from moat.util.liner import Liner

pytestmark = pytest.mark.anyio


CFG1 = """
apps:
  s: _test.MpyRaw
  r: net.tcp.Link
s:
  mplex: false
  cfg:
    apps:
      co: stdio.console
      r: net.tcp.Port
    co:
      keep: false
      repl: true
  log:
    txt: "M"
"""

# TODO add a test that uses stdio with framing plus console=True, reads
# from the console stream and prints+verifies that via some _sys.stdout call


async def test_repl(tmp_path, free_tcp_port):
    "basic REPL test"
    cfg = yload(CFG1, attr=True)
    cfg.s.cfg.r = attrdict(host="127.0.0.1", port=free_tcp_port, wait=False)
    cfg.r = attrdict(host="127.0.0.1", port=free_tcp_port, wait=False)

    async def readcons(s, con, cob=None):
        if cob is None:
            wr = sys.stdout.write
        else:

            def wr(s):
                cob.append(s)
                sys.stdout.write(s)

        async with Liner(prefix=s, writer=wr) as line:
            while True:
                nbuf = await con(100)
                if isinstance(nbuf, memoryview):
                    nbuf = bytes(nbuf)
                line(nbuf)

    async with mpy_stack(tmp_path, cfg) as d:
        d.tg.start_soon(readcons, "CONS ", d.sub_at(P("s.rd")))
        await d.cmd(P("r.rdy_"))
        co = d.sub_at(P("r.co"))
        cob = []
        d.tg.start_soon(readcons, "CO ", co.r, cob)
        await co.w(b"'Foo',2*21\n")
        await anyio.sleep(0.1)
        cb = "".join(cob)
        assert "Foo" in cb
        assert "42" in cb
