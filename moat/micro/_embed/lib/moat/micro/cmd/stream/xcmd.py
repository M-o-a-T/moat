"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

from moat.micro.proto.stack import Base, BaseBlk, BaseBuf, BaseMsg

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


class _BBMCmd(Base):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.cmd = cfg["_cmd"]

    async def setup(self):
        await Base.setup(self)
        # not using super() because {Msg,Buf,Base}Cmd pull in inheritance
        # from BaseConn which calls ``.stream`` which we don't have, or want
        self.s = self.cmd.root.sub_at(self.cfg["path"])


class MsgCmd(_BBMCmd, BaseMsg):
    """
    This is the reverse of a CmdBBM for messages, i.e. a stream handler that forwards
    send/recv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method

    def send(self, m) -> Awaitable:  # pylint:disable=invalid-overridden-method
        "send a message"
        return self.s.s(m=m)

    def recv(self) -> Awaitable:  # pylint:disable=invalid-overridden-method
        "receive a message"
        return self.s.r()

    def cwr(self, buf) -> Awaitable:  # pylint:disable=invalid-overridden-method
        "write console data"
        return self.s.cwr(b=buf)

    async def crd(self, buf):
        "read console data"
        msg = await self.s.crd(n=len(buf))
        buf[: len(msg)] = msg
        return len(msg)


class BufCmd(_BBMCmd, BaseBuf):
    """
    This is the reverse of a CmdBBM for blocks, i.e. a stream handler that forwards
    snd/rcv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method
    # `stream` needs to be implemented by a subclass

    def wr(self, buf) -> Awaitable:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        return self.s.wr(buf)

    async def rd(self, buf):  # noqa:D102
        msg = await self.s.rd(n=len(buf))
        buf[: len(msg)] = msg
        return len(msg)


class BlkCmd(_BBMCmd, BaseBlk):
    """
    This is the reverse of a CmdBBM for blocks, i.e. a stream handler that forwards
    snd/rcv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method

    crd = MsgCmd.crd
    cwr = MsgCmd.cwr

    def snd(self, m) -> Awaitable:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        return self.s.sb(m=m)

    def rcv(self) -> Awaitable:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        return self.s.rb()
