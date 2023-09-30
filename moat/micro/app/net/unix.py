from contextlib import asynccontextmanager

import anyio

from moat.micro.proto.unix import Link as UnixLink
from moat.micro.stacks.console import console_stack
from moat.micro.cmd.stream import StreamCmd, BaseBBMCmd
from moat.micro.cmd.base import BaseCmd


class Raw(BaseBBMCmd):
    """Sends/receives raw data"""
    def stream(self):
        return UnixLink(self.port)

class Link(StreamCmd):
    @asynccontextmanager
    async def stream(self):
        async with console_stack(UnixLink(self.port), self.cfg) as stream:
            yield stream


class Port(BaseCmd):
    async def _handle(self, client):
        fd = client.fileno()
        async with console_stack(SingleAnyioBuf(client), self.cfg) as s:

            sc = SingleStreamCmd(s)
            self._parent.attach(fd, sc)

    async def run(self):
        listener = await anyio.create_unix_listener(self.cfg["port"])
        self.set_ready()
        await listener.serve(handle)
