"""
Test runner
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from random import random

import anyio
from moat.util import attrdict, merge, packer, yload

from moat.micro.compat import TaskGroup
from moat.micro.main import Request, get_link, get_link_serial
from moat.micro.proto.multiplex import Multiplexer
from moat.micro.proto.stack import _Stacked

logging.basicConfig(level=logging.DEBUG)


@asynccontextmanager
async def mpy_server(
    temp: Path, debug=True, lossy=False, guarded=False, cff="test", cfg=None
):
    """
    Creates a test multiplexer with a Unix MicroPython process behind it
    """
    obj = attrdict()
    obj.debug = debug
    obj.lossy = lossy
    obj.guarded = guarded
    obj.socket = temp / "moat.sock"

    cff = Path(f"tests/{cff}.cfg")
    with open(cff, "r") as f:
        cf = yload(f, attr=True)
    cfg = merge(cf, cfg) if cfg else cf

    cfg["link"]["guarded"] = guarded
    cfg["link"]["lossy"] = lossy

    @asynccontextmanager
    async def _factory(req):
        try:
            os.stat("micro/lib")
        except OSError:
            pre = Path(__file__).parents[2]
        else:
            pre = "micro/"

        root = temp / "root"
        try:
            root.mkdir()
            (root / "tests").symlink_to(Path("tests").absolute())
        except EnvironmentError:
            pass
        with (root / "moat.cfg").open("wb") as f:
            f.write(packer(cfg))

        argv = [
            # "strace","-s300","-o/tmp/bla",
            pre / "lib/micropython/ports/unix/build-standard/micropython",
            pre / "tests-mpy/mplex.py",
            str(root),
            str(pre),
        ]

        async with await anyio.open_process(argv, stderr=sys.stderr) as proc:
            ser = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
            async with get_link_serial(
                obj, ser, request_factory=req, use_console=not lossy
            ) as link:
                yield link

    mplex = Multiplexer(_factory, obj.socket, cfg=cfg, load_cfg=True)
    async with TaskGroup() as tg:
        srv = await tg.spawn(mplex.serve, _name="serve")
        with anyio.fail_after(3):
            await mplex.wait()
        obj.server = mplex
        obj.cfg = cfg
        yield obj
        srv.cancel()


@asynccontextmanager
async def mpy_client(obj, **kw):
    """
    Creates a client that connects to the test server set up by
    `mpy_server`.
    """
    kw.setdefault("request_factory", Request)

    async with get_link(obj, cfg=obj.cfg, **kw) as link:
        yield link


class Loop(_Stacked):
    """
    A simple loopback object.

    The write queue is created locally, the read queue is taken from the
    "other side".
    """

    _link = None

    def __init__(self, qlen=0, loss=0):
        assert 0 <= loss < 1

        super().__init__(None)
        self.q_wr, self.q_rd = anyio.create_memory_object_stream(qlen)
        self.loss = loss

    def link(self, other):
        """Tell this loopback to read from some other loopback."""
        self._link = other

    async def send(self, data):  # pylint:disable=arguments-differ
        """Send data."""
        if self._link is None:
            raise anyio.BrokenResourceError(self)
        if random() < self.loss:
            return
        try:
            await self.q_wr.send(data)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream) as exc:
            raise EOFError from exc

    async def recv(self):  # pylint:disable=arguments-differ
        if self._link is None:
            raise anyio.BrokenResourceError(self)
        try:
            return await self._link.q_rd.receive()
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream):
            raise EOFError from None

    async def run(self):
        try:
            await super().run()
        finally:
            await self.aclose()

    async def aclose(self):
        await self.q_wr.aclose()
        if self._link is not None:
            await self._link.q_rd.aclose()
