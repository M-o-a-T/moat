"""
Test runner
"""

from __future__ import annotations

import anyio
import os
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from random import random

import moat.micro
from moat.util import attrdict, combine_dict, ctx_as, yload
from moat.lib.codec import get_codec
from moat.micro.cmd.tree.dir import Dispatch

# from moat.micro.main import Request, get_link, get_link_serial
# from moat.micro.proto.multiplex import Multiplexer
from moat.micro.proto.stack import BaseBlk, BaseBuf, BaseMsg
from moat.micro.proto.stream import ProcessBuf
from moat.util.compat import L, TaskGroup

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable

temp_dir = ContextVar("temp_dir")

required = [
    "__future__",
    "copy",
    "errno",
    "pprint",
    "typing",
    "types",
    "functools",
    "contextlib",
    "ucontextlib",
    "collections",
    "inspect",
]


def rlink(s, d):
    "recursive linking"
    if s.is_file():
        with suppress(FileExistsError):
            d.symlink_to(s)
    else:
        with suppress(FileExistsError):
            d.mkdir()
        for f in s.iterdir():
            rlink(s / f.name, d / f.name)


class MpyBuf(ProcessBuf):
    """
    A stream that links to MicroPython.

    If the config option "mplex" is `True`, this starts a standard
    multiplexer. Otherwise you get a plain micropython interpreter;
    if `False` (instead of missing or `None`), your directory contains a
    "stdlib" folder and MICROPYPATH will point to it.

    Using this option requires either running as part of a MpyStack,
    or setting the ``cwd`` config to a suitable directory.

    If "mplex" is a string, it is interpreted as the "state" argument to
    ``main.go()``. The default for ``mplex=True`` is "once".
    """

    async def setup(self):
        codec = get_codec("std-cbor")
        mplex = self.cfg.get("mplex", None)
        if mplex is not None:
            pre = Path(__file__).parents[2]
            upy = pre / "ext/micropython"

            root = self.cfg.get("cwd", None)
            if root is None:
                root = temp_dir.get() / "root"
            else:
                root = Path(root).absolute()
            lib = root / "stdlib"
            lib2 = root / "lib"
            with suppress(FileExistsError):
                root.mkdir()
            with suppress(FileExistsError):
                lib.mkdir()
            with suppress(FileExistsError):
                lib2.mkdir()
            if mplex:
                with suppress(FileExistsError):
                    (root / "tests").symlink_to(Path("tests").absolute())

            std = (upy / "lib/micropython-lib/python-stdlib").absolute()
            ustd = (upy / "lib/micropython-lib/micropython").absolute()
            for req in required:
                if (std / req).exists():
                    rlink(std / req, lib)
                elif (ustd / req).exists():
                    rlink(ustd / req, lib)
                else:
                    raise FileNotFoundError(std / req)

            aio = Path("lib/micropython/extmod/asyncio").absolute()
            with suppress(FileExistsError):
                (lib / "asyncio").symlink_to(aio)

            libp = []
            for p in moat.micro.__path__:
                p = Path(p) / "_embed"  # noqa:PLW2901
                if p.exists():
                    libp.append(p)
                if (p / "lib").exists():
                    libp.append(p / "lib")
            libp.append(".frozen")

            self.env = {
                "MICROPYPATH": os.pathsep.join(str(x) for x in (lib, lib2, *libp)),
            }
            self.cwd = root

        if mplex:
            with (root / "moat.cfg").open("wb") as f:
                f.write(codec.encode(self.cfg["cfg"]))
            if self.cfg.get("large", True):
                with (root / "moat.lrg").open("wb") as f:
                    pass

            self.argv = [
                # "strace","-s300","-o/tmp/bla",
                upy / "ports/unix/build-standard/micropython",
                pre / "packaging/moat-micro/tests-mpy/mplex.py",
            ]
            if isinstance(mplex, str):
                self.argv.append(mplex)
        else:
            self.argv = [
                upy / "ports/unix/build-standard/micropython",
                "-e",
            ]

        await super().setup()


@asynccontextmanager
async def mpy_stack(temp: Path, cfg: dict | str, cfg2: dict | None = None):
    """
    Creates a multiplexer.
    """
    if isinstance(cfg, str):
        if "\n" in cfg:
            cfg = yload(cfg, attr=True)
        else:
            with (Path("tests") / "cfg" / (cfg + ".cfg")).open("r") as cff:
                cfg = yload(cff, attr=True)

    if cfg2 is not None:
        cfg = combine_dict(cfg2, cfg, cls=attrdict)

    async with ctx_as(temp_dir, temp), TaskGroup() as tg:
        stack = Dispatch(cfg)
        try:
            await tg.spawn(stack.run)
            if L:
                await stack.wait_ready()
            yield stack
        finally:
            tg.cancel()


class Loopback(BaseMsg, BaseBuf, BaseBlk):
    """
    A simple loopback object.

    The write queue is created locally, the read queue is taken from the
    "other side".

    This object can be self-linked.
    """

    # pylint:disable=abstract-method

    _link = None
    _buf = None

    def __init__(self, qlen=0, loss=0):
        super().__init__({})
        assert 0 <= loss < 1
        self.q_wr, self.q_rd = anyio.create_memory_object_stream(qlen)
        self.loss = loss

    async def setup(self):
        if self._link is None:
            raise RuntimeError("Link before setup!")
        elif isinstance(self._link, anyio.Event):
            await self._link.wait()

    def link(self, other: Loopback | anyio.Event):
        """Tell this loopback to read from some other loopback."""
        evt, self._link = self._link, other
        if isinstance(evt, anyio.Event):
            evt.set()

    async def send(self, m, _loss=True):  # pylint:disable=arguments-differ
        """Send data."""
        if self._link is None:
            raise anyio.BrokenResourceError(self)
        if _loss and random() < self.loss:
            return
        try:
            await self.q_wr.send(m)
        except (
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            anyio.EndOfStream,
        ) as exc:
            raise EOFError from exc

    snd = send

    async def recv(self):  # pylint:disable=arguments-differ
        if self._link is None:
            raise anyio.BrokenResourceError(self)
        try:
            return await self._link.q_rd.receive()
        except (
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            anyio.EndOfStream,
        ):
            raise EOFError from None

    rcv = recv

    async def rd(self, buf) -> int:
        while True:
            if self._buf:
                n = min(len(self._buf), len(buf))
                buf[0:n] = self._buf[0:n]
                self._buf = self._buf[n:]
                return n
            self._buf = await self.recv()

    async def wr(self, buf) -> int:
        n = len(buf)
        if self.loss:
            b = bytearray(buf)
            loss = 1 - (1 - self.loss) ** (1 / len(b) / 2)
            # '1-loss' is the chance of not killing each single byte
            # that's required to not kill a message of size len(b)
            # given two chances of mangling each byte

            n = 0
            while n < len(b):
                if random() < loss:
                    del b[n]
                else:
                    while random() < loss:
                        b[n] = b[n] ^ (1 << int(8 * random()))
                    n += 1
        else:
            b = bytes(buf)
        await self.send(bytes(buf), _loss=False)
        return n

    async def teardown(self):
        await self.q_wr.aclose()
        if self._link is not None and self._link is not self:
            await self._link.q_rd.aclose()
        await super().teardown()


class LoopBBM(BaseMsg, BaseBuf, BaseBlk):
    """
    A loopback BBM. It talks to a remote LoopLink.

    This BBM is not a command, thus it cannot be linked to.

    The remote LoopLink must have the appropriate buffers,
    i.e. `usage: mM` for messages, etc.
    """

    # pylint:disable=abstract-method

    _link = None

    async def setup(self):
        p = self.cfg["path"]
        if isinstance(p, str):
            raise TypeError(f"Need a path, not {p!r}")
        self._link = self.cfg["_cmd"].root.sub_at(p)

    def send(self, m) -> Awaitable[None]:
        """Send message data."""
        return self._link.xs(m=m)

    def recv(self) -> Awaitable[None]:
        """Read message data."""
        return self._link.xr()

    def snd(self, m) -> Awaitable[None]:
        """Send block data."""
        return self._link.xsb(m=m)

    def rcv(self) -> Awaitable[bytes | bytearray]:
        return self._link.xrb()
        """Read block data."""

    def wr(self, b: bytes | bytearray) -> Awaitable[None]:
        """Send bytes."""
        return self._link.xwr(b=b)

    async def rd(self, b):
        """Read bytes."""
        r = await self._link.xrd(n=len(b))
        n = len(r)
        b[:n] = r
        return n

    def cwr(self, b: bytes | bytearray | memoryview) -> Awaitable[int]:
        """Send bytes."""
        return self._link.xcwr(b=b)

    async def crd(self, b) -> bytes | bytearray:
        """Read bytes."""
        r = await self._link.xcrd(n=len(b))
        n = len(r)
        b[:n] = r
        return n


class Root(Dispatch):
    "an empty root for testing"

    def __init__(self):
        super().__init__({})


# Fake "machine" module

machine = attrdict()


class FakeI2C:
    def __init__(self, c, d, **_):
        self._c = c
        self._d = d


class FakePin:
    def __init__(self, pin, **_):
        self._pin = pin


machine.Pin = FakePin
machine.I2C = FakeI2C
machine.SoftI2C = FakeI2C
