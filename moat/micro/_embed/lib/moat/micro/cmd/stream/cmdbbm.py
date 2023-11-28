"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

import sys

from moat.util import NotGiven, ValueEvent, obj2name
from moat.micro.compat import ACM, AC_exit, AC_use, BaseExceptionGroup, Lock, TaskGroup, log, L
from moat.micro.proto.stack import Base, BaseBlk, BaseBuf, BaseMsg, RemoteError, SilentRemoteError

from moat.micro.cmd.base import BaseCmd

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any, Awaitable, Mapping


class BaseCmdBBM(BaseCmd):
    """
    This is a command handler that connects MoaT's Cmd tree to a `BaseBuf`,
    `BaseBlk` or `BaseMsg` instance.

    Override `stream` to return that instance, possibly wrapped with `AC_use`.

    This is a single class that adapts to any of a `BaseMsg`, `BaseBlk`, or
    `BaseBuf` stream.

    The difference between this and a `BaseCmdMsg`-derived class is that
    this class exposes commands that directly access the underlying stream
    (of whatever type).

    In contrast, a `BaseCmdMsg` objects encapsulates arbitrary commands,
    and requires a `BaseCmdMsg` handler on the other side to talk to.
    """

    s = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.w_lock = Lock()

    async def stream(self) -> BaseMsg | BaseBlk | BaseBuf:
        "create the actual data stream. Override this!"
        raise NotImplementedError("setup", self.path)

    async def setup(self):  # noqa:D102
        await super().setup()
        self.s = await self.stream()

    async def run(self):  # noqa:D102
        ACM(self)
        try:
            await super().run()
        finally:
            self.s = None
            await AC_exit(self)

    # Buf: rd/wr = .rd/.wr

    async def cmd_rd(self, n=64):
        """read some data"""
        if L:
            await self.wait_ready()
        b = bytearray(n)
        r = await self.s.rd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def cmd_wr(self, b):
        """write some data"""
        if L:
            await self.wait_ready()
        async with self.w_lock:
            await self.s.wr(b)

    # Blk/Msg: Console crd/cwr = .crd/cwr

    async def cmd_crd(self, n=64) -> bytes:
        """read some console data"""
        b = bytearray(n)
        r = await self.s.crd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def cmd_cwr(self, b):
        """write some console data"""
        async with self.w_lock:
            await self.s.cwr(b)

    # Msg: s/r = .send/.recv

    async def cmd_s(self, m) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """send a message"""
        return self.s.send(m)

    async def cmd_r(self) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """receive a message"""
        return self.s.recv()

    # Blk: sb/rb = .snd/.rcv

    async def cmd_sb(self, m) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """send a binary message"""
        return self.s.snd(m)

    async def cmd_rb(self) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """receive a binary message"""
        return self.s.rcv()
