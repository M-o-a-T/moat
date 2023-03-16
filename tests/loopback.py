"""
Loopback stream module
"""

import anyio
from moat.micro.proto.stack import _Stacked
from random import random

class Loop(_Stacked):
    """
    A simple loopback object.

    The write queue is created locally, the read queue is taken from the
    "other side".
    """
    link = None

    def __init__(self, qlen=0, loss=0):
        assert 0 <= loss < 1

        super().__init__(None)
        self.q_wr, self.q_rd = anyio.create_memory_object_stream(qlen)
        self.loss = loss

    def link(self, other):
        """Tell this loopback to read from some other loopback."""
        self.link = other

    async def send(self, data):
        """Send data."""
        if self.link is None:
            raise anyio.BrokenResourceError(self)
        if random() < self.loss:
            return
        try:
            await self.q_wr.send(data)
        except (anyio.ClosedResourceError,anyio.BrokenResourceError,anyio.EndOfStream):
            raise EOFError

    async def recv(self):
        if self.link is None:
            raise anyio.BrokenResourceError(self)
        try:
            return await self.link.q_rd.receive()
        except (anyio.ClosedResourceError,anyio.BrokenResourceError,anyio.EndOfStream):
            raise EOFError

    async def run(self):
        try:
            await super().run()
        finally:
            await self.aclose()

    async def aclose(self):
        await self.q_wr.aclose()
        if self.link is not None:
            await self.link.q_rd.aclose()
