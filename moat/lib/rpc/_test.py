"""
Test support
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from random import random

from moat.util import attrdict, combine_dict, ctx_as, yload
from moat.lib.rpc import RootCmd
from moat.lib.stream import BaseBlk, BaseBuf, BaseMsg

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.stream.base import Buffer, MutBuffer

    from collections.abc import Awaitable
    from typing import Any, Protocol

    class _LoopLinkProto(Protocol):
        def xs(self, *, m: Any) -> Awaitable[None]: ...

        def xr(self) -> Awaitable[Any]: ...

        def xsb(self, *, m: Buffer | bytes) -> Awaitable[None]: ...

        def xrb(self) -> Awaitable[Buffer | bytes]: ...

        def xwr(self, *, b: Buffer) -> Awaitable[None]: ...

        def xrd(self, *, n: int) -> Awaitable[Buffer | bytes]: ...

        def xcwr(self, *, b: Buffer) -> Awaitable[None]: ...

        def xcrd(self, *, n: int) -> Awaitable[Buffer | bytes]: ...


temp_dir = ContextVar("temp_dir")


@asynccontextmanager
async def rpc_stack(temp: Path, cfg: dict | str, cfg2: dict | None = None, **kw):
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

    async with ctx_as(temp_dir, temp):
        if isinstance(cfg.get("app"), str):
            cfg = attrdict(app=cfg)
        if "rtc" in cfg:
            from moat.micro.rtc import RTC  # noqa:PLC0415

            RTC.init(cfg["rtc"])
        stack = RootCmd(cfg, **kw)
        async with stack:
            yield stack


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
        link = self._link
        if link is None or isinstance(link, anyio.Event):
            raise anyio.BrokenResourceError(self)
        try:
            return await link.q_rd.receive()
        except (
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            anyio.EndOfStream,
        ):
            raise EOFError from None

    rcv = recv

    async def rd(self, buf: MutBuffer) -> int:
        while True:
            if self._buf:
                n = min(len(self._buf), len(buf))
                buf[0:n] = self._buf[0:n]
                self._buf = self._buf[n:]
                return n
            self._buf = await self.recv()

    async def wr(self, data: Buffer) -> int:
        n = len(data)
        if self.loss:
            b = bytearray(data)
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
            b = bytes(data)
        await self.send(b, _loss=False)
        return n

    async def teardown(self):
        await self.q_wr.aclose()
        link = self._link
        if isinstance(link, Loopback) and link is not self:
            await link.q_rd.aclose()
        await super().teardown()


class LoopBBM(BaseMsg, BaseBuf, BaseBlk):
    """
    A loopback BBM. It talks to a remote LoopLink.

    This BBM is not a command, thus it cannot be linked to.

    The remote LoopLink must have the appropriate buffers,
    i.e. `usage: mM` for messages, etc.
    """

    # pylint:disable=abstract-method

    _link: _LoopLinkProto | None = None

    async def setup(self):
        p = self.cfg["path"]
        if isinstance(p, str):
            raise TypeError(f"Need a path, not {p!r}")
        self._link = self.cfg._moat_cmd.root.sub_at(p)  # noqa:SLF001

    def _r(self) -> _LoopLinkProto:
        link = self._link
        if link is None:
            raise RuntimeError("not set up")
        return link

    async def send(self, m: Any) -> Any:
        """Send message data."""
        return await self._r().xs(m=m)

    async def recv(self) -> Any:
        """Read message data."""
        return await self._r().xr()

    async def snd(self, m: Buffer | bytes) -> None:
        """Send block data."""
        await self._r().xsb(m=m)

    async def rcv(self) -> Buffer | bytes:
        """Read block data."""
        return await self._r().xrb()

    async def wr(self, data: Buffer) -> int:
        """Send bytes."""
        await self._r().xwr(b=data)
        return len(data)

    async def rd(self, buf: MutBuffer) -> int:
        """Read bytes."""
        r = await self._r().xrd(n=len(buf))
        n = len(r)
        buf[:n] = r
        return n

    async def cwr(self, b: Buffer) -> None:
        """Send bytes."""
        await self._r().xcwr(b=b)

    async def crd(self, b: bytearray) -> int:
        """Read bytes."""
        r = await self._r().xcrd(n=len(b))
        n = len(r)
        b[:n] = r
        return n


class Root(RootCmd):
    "an empty root for testing"

    def __init__(self):
        super().__init__({})
