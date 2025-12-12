"""
Connection tests
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import P, attrdict, yload
from moat.micro._test import mpy_stack

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


async def test_console(tmp_path, free_tcp_port):
    "basic console test"
    cfg = yload(CFG1, attr=True)
    cfg.s.cfg.r = attrdict(host="127.0.0.1", port=free_tcp_port, wait=False)
    cfg.r = attrdict(host="127.0.0.1", port=free_tcp_port, wait=False)

    async def readcons(s, con, cob=None):
        while True:
            buf = await con(100)
            if isinstance(buf, memoryview):
                buf = bytes(buf)
            buf = buf.decode("utf-8")
            buf = buf.replace("\n", f"\n{s} ")
            print(s, buf)
            if cob is not None:
                cob.append(buf)

    async with mpy_stack(tmp_path, cfg) as d:
        d.tg.start_soon(readcons, "CONS", d.sub_at(P("s.rd")))
        await d.cmd(P("r.rdy_"))
        co = d.sub_at(P("r.co"))
        cob = []
        d.tg.start_soon(readcons, "CO", co.r, cob)
        await co.w(b"'Foo',2*21\n")
        await anyio.sleep(0.1)
        cb = "".join(cob)
        assert "Foo" in cb
        assert "42" in cb
