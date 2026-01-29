"""
Connection tests
"""

from __future__ import annotations

import anyio
import pytest
import sys

from moat.util import yload
from moat.lib.path import P
from moat.micro._test import mpy_stack
from moat.util.liner import Liner

pytestmark = pytest.mark.anyio


CFG1 = """
app: dir
r:
  app: net.tcp.Link
s:
  app: _test.MpyRaw
  mplex: false
  cfg:
    app:
      app: dir
      r:
        app: net.tcp.Port
      co:
        app: stdio.console
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
    cfg.s.cfg.app.r.update(host="127.0.0.1", port=free_tcp_port, wait=False)
    cfg.r.update(host="127.0.0.1", port=free_tcp_port, wait=False)

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


async def test_repl_stream(tmp_path, free_tcp_port):
    "REPL as data stream"
    cfg = yload(CFG1, attr=True)
    cfg.s.cfg.app.r.update(host="127.0.0.1", port=free_tcp_port, wait=False)
    cfg.r.update(host="127.0.0.1", port=free_tcp_port, wait=False)

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

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r.co")) as cons,
        cons.rw().stream() as co,
        anyio.create_task_group() as tg,
    ):
        d.tg.start_soon(readcons, "CONS ", d.sub_at(P("s.rd")))
        await d.cmd(P("r.rdy_"))
        cob = []
        co_r = aiter(co)

        async def co_next(_n):
            return (await anext(co_r))[0]

        tg.start_soon(readcons, "CO ", co_next, cob)
        await co.send(b"'Foo',2*21\n")
        await anyio.sleep(0.1)
        cb = "".join(cob)
        assert "Foo" in cb
        assert "42" in cb
        tg.cancel_scope.cancel()


CFG2 = """
app: dir
_sys:
  app: _sys.Cmd
r:
  app: _test.MpyCmd
  mplex: true
  cfg:
    app:
      app: dir
      co:
        app: stdio.console
        keep: false
        repl: true
      co_in:
        app: part.Transfer
        t: 5
        s:
          - p: !P r.crd
          - p: !P co.w
      co_out:
        app: part.Transfer
        t: 5
        s:
          - p: !P co.r
          - p: !P r.cwr
      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0x85
          console: true
    tt:
      a: b
      c:
        d: e
      z: 99

  link: *link
"""


async def test_repl_direct(tmp_path):
    "REPL on the Unix stdio data stream"
    cfg = yload(CFG2, attr=True)

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

    async with (
        mpy_stack(tmp_path, cfg) as d,
        d.sub_at(P("r")) as cr,
        anyio.create_task_group() as tg,
    ):
        cob = []
        tg.start_soon(readcons, "CONS ", d.sub_at(P("r.crd")), cob)
        await d.cmd(P("r.rdy_"))
        await anyio.sleep(0.5)

        await cr.cwr(b"'Foo',2*21\n")
        await anyio.sleep(0.5)
        cb = "".join(cob)
        assert "Foo" in cb
        assert "42" in cb
        tg.cancel_scope.cancel()
