"""
Loopback stream module
"""

import anyio
from moat.micro.proto.stack import _Stacked

class Loop(_Stacked):
    """
    A simple loopback object.

    The write queue is created locally, the read queue is taken from the
    "other side".
    """
    link = None

    def __init__(self, qlen=0):
        super().__init__(None)
        self.q_wr, self.q_rd = anyio.create_memory_object_stream(qlen)

    def link(self, other):
        """Tell this loopback to read from some other loopback."""
        self.link = other

    async def send(self, data):
        """Send data."""
        if self.link is None:
            raise anyio.BrokenResourceError(self)
        await self.q_wr.send(data)

    async def recv(self):
        if self.link is None:
            raise anyio.BrokenResourceError(self)
        return await self.link.q_rd.receive()

    async def aclose(self):
        await self.q_wr.aclose()
