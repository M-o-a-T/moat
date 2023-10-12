from __future__ import annotations

from moat.micro.proto.tcp import Link as TcpLink
from moat.micro.stacks.console import console_stack
from moat.micro.cmd.stream import StreamCmd, BaseBBMCmd, SingleStreamCmd, ExtStreamCmd
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.tree import BaseLayerCmd, BaseSubCmd, BaseListenCmd
from moat.micro.compat import AC_use, TaskGroup
from moat.micro.stacks.tcp import TcpIter


class Raw(BaseBBMCmd):
    """Sends/receives raw data"""
    def stream(self) -> Awaitable:
        return AC_use(TcpLink(self.port))

class Link(SingleStreamCmd):
    """
    An app that connects to a remote socket.
    """
    async def stream(self):
        return await AC_use(self, console_stack(TcpLink(self.cfg.get("host","127.0.0.1"), self.cfg["port"]), self.cfg))

class LinkIn(BaseListenCmd):
    """
    An app that accepts a single connection from a remote socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """
    def listener(self):
        return TcpIter(self.cfg.get("host","127.0.0.1"), self.cfg["port"])


class Port(BaseSubCmd):
    """
    An app that accepts multiple TCP connections.
    """
    step = 3

    async def _handle(self, client):
        n = len(self.sub)
        while n in self.sub:
            n += self.step+3
            self.step = (self.step+1)%9
            # arbitrary complicator to make immediate reuse somewhat unlikely
        # use the file descriptor as the command's "name"
        # somewhat-small, integer, guaranteed to be unique
        async with console_stack(client, self.cfg) as s:
            sc = ExtStreamCmd(s)
            await self.attach(n, sc)
            await sc._stopped.wait()

    async def run(self):
        async with TcpIter(self.cfg.get("host","127.0.0.1"), self.cfg["port"]) as stp:
            self.set_ready()
            async for s in stp:
                await self.tg.spawn(self._handle, s)
