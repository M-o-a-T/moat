"""
Test runner
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from random import random
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar

import anyio
from moat.util import attrdict, merge, packer, yload, Queue, combine_dict

from moat.micro.compat import TaskGroup, AC_use
from moat.micro.cmd.stream import StreamCmd
from moat.micro.cmd.tree import Dispatch
#from moat.micro.main import Request, get_link, get_link_serial
#from moat.micro.proto.multiplex import Multiplexer
from moat.micro.proto.stack import BaseMsg, BaseBuf
from moat.micro.proto.stream import ProcessBuf
from moat.micro.app.pipe import Process

logging.basicConfig(level=logging.DEBUG)
def lbc(*a,**k):
    raise RuntimeError("don't configure logging a second time")
logging.basicConfig = lbc


temp_dir = ContextVar("temp_dir")

required = [
        "__future__",
        "functools",
        "collections",
        "collections-deque",
]

def rlink(s,d):
    if s.is_file():
        with suppress(FileExistsError):
            d.symlink_to(s)
    else:
        with suppress(FileExistsError):
            d.mkdir()
        for f in s.iterdir():
            rlink(s/f.name,d/f.name)

class MpyBuf(ProcessBuf):
    """
    A stream that links to MicroPython
    """
#   async def __init__(self, cfg, cff):
#       super().__init__(cfg)
#       self.cff = cff

    async def setup(self):
        self.cfg.setdefault("path", "lib/micropython/ports/unix/build-standard/micropython")
        self.cfg.setdefault("command", ("micropython","micro/tests-mpy/mplex.py"))

        try:
            os.stat("micro/lib")
        except OSError:
            pre = Path(__file__).parents[2]
        else:
            pre = "micro/"

        root = temp_dir.get() / "root"
        lib = root / "stdlib"
        with suppress(FileExistsError):
            root.mkdir()
        with suppress(FileExistsError):
            lib.mkdir()
        with suppress(FileExistsError):
            (root / "tests").symlink_to(Path("tests").absolute())

        std = Path("lib/micropython-lib/python-stdlib")
        for req in required:
            rlink(std.absolute()/req, lib.absolute())

        with (root / "moat.cfg").open("wb") as f:
            f.write(packer(self.cfg["cfg"]))

        self.argv = [
            # "strace","-s300","-o/tmp/bla",
            pre / "lib/micropython/ports/unix/build-standard/micropython",
            pre / "tests-mpy/mplex.py",
            str(root),
            # str(pre),
        ]

        await super().setup()


@asynccontextmanager
async def mpy_stack(temp: Path, cfg:dict|str, cfg2:dict|None):
    """
    Creates a multiplexer.
    """
    if isinstance(cfg,str):
        if "\n" in cfg:
            cfg = yload(cfg, attr=True)
        else:
            with (Path("tests")/"cfg"/(cfg+".cfg")).open("r") as cff:
                cfg = yload(cff, attr=True)

    if cfg2 is not None:
        cfg = combine_dict(cfg2,cfg)

    rst = temp_dir.set(temp)
    try:
        async with TaskGroup() as tg:
            stack = Dispatch(cfg)
            try:
                await tg.spawn(stack.run, _name="Stack")
                await stack.wait_all_ready()
                yield stack
            finally:
                tg.cancel()
    finally:
        temp_dir.reset(rst)


class Loopback(BaseMsg, BaseBuf):
    """
    A simple loopback object.

    The write queue is created locally, the read queue is taken from the
    "other side".

    This object can be self-linked.
    """

    _link = None
    _buf = None

    def __init__(self, qlen=0, loss=0):
        assert 0 <= loss < 1
        self.q_wr, self.q_rd = anyio.create_memory_object_stream(qlen)
        self.loss = loss

    def link(self, other):
        """Tell this loopback to read from some other loopback."""
        self._link = other
        self.set_ready()

    async def send(self, data, _loss=True):  # pylint:disable=arguments-differ
        """Send data."""
        if self._link is None:
            raise anyio.BrokenResourceError(self)
        if _loss and random() < self.loss:
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

    async def rd(self, buf) -> int:
        while True:
            if self._buf:
                n = min(len(self._buf), len(buf))
                buf[0:n] = self._buf[0:n]
                self._buf = self._buf[n:]
                return n
            self._buf = await self.recv()

    async def wr(self, buf) -> int:
        if self.loss:
            b = bytearray(buf)
            l = 1 - (1-self.loss)**(1/len(b)/2)
            # '1-l' is the chance of not killing each single byte 
            # that's required to not kill a message of size len(b)
            # given two chances of mangling each byte

            n = 0
            while n < len(b):
                if random() < l:
                    del b[n]
                else:
                    if random() < l:
                        b[n] = b[n] ^ (1<<int(8*random()))
                    n += 1
        else:
            b = bytes(buf)
        await self.send(bytes(buf), _loss=False)


    async def teardown(self):
        await self.q_wr.aclose()
        if self._link is not None and self._link is not self:
            await self._link.q_rd.aclose()
        await super().teardown()


class Root(Dispatch):
    # an empty root for testing
    def __init__(self):
        super().__init__({})
