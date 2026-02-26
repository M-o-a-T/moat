"""
Stream link-up support for MoaT commands
"""

from __future__ import annotations

from moat.lib.stream import Base, BaseBlk, BaseBuf, BaseMsg

__all__ = ["BlkCmd", "BufCmd", "MsgCmd"]

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.stream.base import Buffer, MutBuffer

    from typing import Any


class BBMCmd(Base):
    """
    Generic base for *Cmd.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cmd = cfg._moat_cmd  # noqa:SLF001

    async def setup(self):
        await Base.setup(self)
        # not using super() because {Msg,Buf,Base}Cmd pull in inheritance
        # from BaseConn which calls ``.stream`` which we don't have, or want
        self.s = self.cmd.root.sub_at(self.cfg["path"])


class MsgCmd(BBMCmd, BaseMsg):
    """
    A stream handler that forwards send/recv (and console) requests via MoaT.

    This is the reverse of a CmdBBM for messages, i.e. a stream handler that forwards
    send/recv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method

    async def send(self, m: Any) -> Any:  # pylint:disable=invalid-overridden-method
        "send a message"
        return await self.s.s(m=m)

    async def recv(self) -> Any:  # pylint:disable=invalid-overridden-method
        "receive a message"
        return await self.s.r()

    async def cwr(self, buf: Buffer) -> None:  # pylint:disable=invalid-overridden-method
        "write console data"
        await self.s.cwr(b=buf)

    async def crd(self, buf: MutBuffer) -> int:
        "read console data"
        msg = await self.s.crd(n=len(buf))
        buf[: len(msg)] = msg
        return len(msg)


class BufCmd(BBMCmd, BaseBuf):
    """
    A stream handler that forwards snd/rcv (and console) requests via MoaT.

    This is the reverse of a CmdBBM for buffers, i.e. a stream handler that forwards
    snd/rcv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method
    # `stream` needs to be implemented by a subclass

    async def wr(self, data: Buffer) -> int:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        return await self.s.wr(data)

    async def rd(self, buf: MutBuffer) -> int:  # noqa:D102
        msg = await self.s.rd(n=len(buf))
        buf[: len(msg)] = msg
        return len(msg)


class BlkCmd(BBMCmd, BaseBlk):
    """
    A stream handler that forwards snd/rcv (and console) requests via MoaT.

    This is the reverse of a CmdBBM for blocks, i.e. a stream handler that forwards
    snd/rcv (and console) requests via MoaT.

    The remote link is addressed by the config item "path".
    """

    # pylint:disable=abstract-method

    crd = MsgCmd.crd
    cwr = MsgCmd.cwr

    async def snd(self, m: Buffer | bytes) -> None:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        await self.s.sb(m=m)

    async def rcv(self) -> Buffer | bytes:  # noqa:D102
        # pylint: disable=invalid-overridden-method
        return await self.s.rb()
