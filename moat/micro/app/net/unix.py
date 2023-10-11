import anyio

from moat.micro.proto.unix import Link as UnixLink
from moat.micro.proto.stream import SingleAnyioBuf
from moat.micro.stacks.console import console_stack
from moat.micro.cmd.stream import StreamCmd, BaseBBMCmd, SingleStreamCmd, ExtStreamCmd
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.tree import BaseLayerCmd, BaseSubCmd
from moat.micro.compat import AC_use


class Raw(BaseBBMCmd):
    """Sends/receives raw data"""
    def stream(self):
        return UnixLink(self.port)

class Link(SingleStreamCmd):
    async def stream(self):
        return await AC_use(self, console_stack(UnixLink(self.cfg["port"]), self.cfg))


class Port(BaseSubCmd):
    async def _handle(self, client):
        fd = client.extra(anyio.abc.SocketAttribute.raw_socket).fileno()
        async with console_stack(SingleAnyioBuf(client), self.cfg) as s:

            sc = ExtStreamCmd(s)
            await self.attach(fd, sc)
            await sc._stopped.wait()

    async def run(self):
        listener = await anyio.create_unix_listener(self.cfg["port"])
        self.set_ready()
        await listener.serve(self._handle)
