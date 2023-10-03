
import anyio

from moat.micro.proto.ip import Link as IPLink
from moat.micro.stacks.console import console_stack
from moat.micro.cmd.stream import StreamCmd, BaseBBMCmd
from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import AC_use


class Raw(BaseBBMCmd):
    """Sends/receives raw data"""
    def stream(self):
        return IPLink(self.cfg.host, self.cfg.port)


class Link(StreamCmd):
    """Sends/receives MoaT messages"""
    async def stream(self):
        return await AC_use(self, console_stack(IPLink(self.cfg.host, self.cfg.port), self.cfg))


class Port(BaseCmd):
    """Accepts client connections"""
    async def _handle(self, client):
        fd = client.fileno()
        async with console_stack(SingleAnyioBuf(client), self.cfg) as s:

            sc = SingleStreamCmd(s)
            self.attach(fd, sc)

    async def run(self):
        listener = await anyio.create_tcp_listener(local_host=self.cfg.get("host","0.0.0.0"), local_port=self.cfg["port"])
        self.set_ready()
        await listener.serve(handle)

    def cmd_lc(self):
        """list connections"""
        return list(self._sub.keys())

    def cmd_ic(self, n):
        """show details of a single connection"""
        return {"e":"TODO"}

    def cmd_cls(self, n):
        """close a connection"""
        self.detach(n)

