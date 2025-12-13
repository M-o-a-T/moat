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
        buf = b""
        async with anyio.create_task_group() as tg:
            evt = anyio.Event()

            @tg.start_soon
            async def flush():
                nonlocal evt, buf
                while True:
                    with anyio.move_on_after(0.1):
                        await evt.wait()
                        evt = anyio.Event()
                        continue
                    # Event did not trigger
                    if buf:
                        pr = buf.decode("utf-8")
                        print(s, pr, "…")
                        if cob is not None:
                            cob.append(pr)
                        buf = b""
                    # now wait for the next incomplete line
                    await evt.wait()
                    evt = anyio.Event()

            while True:
                nbuf = await con(100)
                if isinstance(nbuf, memoryview):
                    nbuf = bytes(nbuf)
                buf += nbuf
                idx = buf.rfind(b"\n")
                if idx != -1:
                    pr = buf[:idx]
                    buf = buf[idx + 1 :]
                    pr = pr.decode("utf-8")
                    pr = pr.replace("\n", f"\n{s} ")
                    print(s, pr)
                    if cob is not None:
                        cob.append(pr)
                if buf:
                    evt.set()

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
