from __future__ import annotations

from moat.micro.proto.tcp import Link as TcpLink
from moat.micro.stacks.console import console_stack
from moat.micro.cmd.stream import CmdMsg, BaseCmdBBM
from moat.micro.cmd.tree import BaseListenCmd, BaseListenOneCmd
from moat.micro.compat import AC_use
from moat.micro.stacks.tcp import TcpIter


class Raw(BaseCmdBBM):
    """Sends/receives raw data"""
    def stream(self) -> Awaitable:
        return AC_use(TcpLink(self.port))

class Link(CmdMsg):
    """
    An app that connects to a remote socket.
    """
    def __init__(self, cfg):
        stack = console_stack(TcpLink(cfg.get("host","127.0.0.1"), cfg["port"]), cfg)
        super().__init__(stack, cfg)

class LinkIn(BaseListenOneCmd):
    """
    An app that accepts a single connection from a remote socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """
    def listener(self):
        return TcpIter(self.cfg.get("host","127.0.0.1"), self.cfg["port"])


class Port(BaseListenCmd):
    """
    An app that accepts multiple TCP connections.
    """
    def listener(self):
        return TcpIter(self.cfg.get("host","127.0.0.1"), self.cfg["port"])
