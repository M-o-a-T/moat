from __future__ import annotations

from moat.micro.cmd.stream import BaseCmdBBM, CmdMsg
from moat.micro.cmd.tree import BaseListenCmd, BaseListenOneCmd
from moat.micro.proto.unix import Link as UnixLink
from moat.micro.stacks.console import console_stack
from moat.micro.stacks.unix import UnixIter


class Raw(BaseCmdBBM):
    """Sends/receives raw data"""

    def stream(self) -> Awaitable:
        return AC_use(UnixLink(self.port))


class Link(CmdMsg):
    """
    An app that connects to a remote socket.
    """

    def __init__(self, cfg):
        stack = console_stack(UnixLink(cfg["port"]), cfg)
        super().__init__(stack, cfg)


class LinkIn(BaseListenOneCmd):
    """
    An app that accepts a single connection from a remote socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """

    def listener(self):
        return UnixIter(self.cfg["port"])


class Port(BaseListenCmd):
    """
    An app that accepts multiple Unix connections.
    """

    def listener(self):
        return UnixIter(self.cfg["port"])
