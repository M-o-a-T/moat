"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import ACM, AC_exit, L, Lock

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.proto.stack import BaseBlk, BaseBuf, BaseMsg

    from collections.abc import Awaitable


class BaseCmdBBM(BaseCmd):
    """
    This is a command handler that connects MoaT's Cmd tree to a `BaseBuf`,
    `BaseBlk` or `BaseMsg` instance.

    Override `stream` to return that instance, possibly wrapped with `AC_use`.

    This is a single class that adapts `BaseMsg`, `BaseBlk`, and
    `BaseBuf` streams.

    The difference between this and a
    :moat.micro.cmd.stream.cmdmsg:`BaseCmdMsg`-derived class is that this
    class exposes commands that directly access the underlying stream
    (of whatever type).

    In contrast, :moat.micro.cmd.stream.cmdmsg:`BaseCmdMsg` encapsulates
    arbitrary commands and requires a
    :moat.micro.cmd.stream.cmdmsg:`BaseCmdMsg` handler on the other side to
    talk to.

    This class cannot wrap a pre-existing stream, by design.
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

    doc_rd = dict(_d="read bytestream", _0="int:len (64)")

    async def cmd_rd(self, n=64) -> bytes:
        """read some data"""
        if L:
            await self.wait_ready()
        b = bytearray(n)
        if self.s is None:
            raise EOFError
        r = await self.s.rd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    doc_wr = dict(_d="write bytestream", _0="bytes:data")

    async def cmd_wr(self, b):
        """write some data"""
        if L:
            await self.wait_ready()
        async with self.w_lock:
            if self.s is None:
                raise EOFError
            await self.s.wr(b)

    # Blk/Msg: Console crd/cwr = .crd/cwr

    doc_crd = dict(_d="read console", _0="int:len (64)")

    async def cmd_crd(self, n=64) -> bytes:
        """read some console data"""
        b = bytearray(n)
        if self.s is None:
            raise EOFError
        r = await self.s.crd(b)
        if r == n:
            return b
        elif r <= n >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    doc_cwr = dict(_d="write console", _0="bytes:data")

    async def cmd_cwr(self, b):
        """write some console data"""
        async with self.w_lock:
            if self.s is None:
                raise EOFError
            await self.s.cwr(b)

    # Msg: s/r = .send/.recv

    doc_s = dict(_d="write message", _0="any:message")

    def cmd_s(self, m) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """send a message"""
        if self.s is None:
            raise EOFError
        return self.s.send(m)

    doc_r = dict(_d="read message", _r="any:message")

    def cmd_r(self) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """receive a message"""
        if self.s is None:
            raise EOFError
        return self.s.recv()

    # Blk: sb/rb = .snd/.rcv

    doc_sb = dict(_d="write block", _0="bytes:encoded message")

    def cmd_sb(self, m) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """send a binary message"""
        if self.s is None:
            raise EOFError
        return self.s.snd(m)

    doc_rb = dict(_d="read block", _r="any:encoded message")

    def cmd_rb(self) -> Awaitable:  # pylint:disable=invalid-overridden-method
        """receive a binary message"""
        if self.s is None:
            raise EOFError
        return self.s.rcv()
