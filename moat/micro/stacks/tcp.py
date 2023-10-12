from __future__ import annotations

import anyio

from moat.util.queue import Queue

from ..compat import TaskGroup, Event, ACM, AC_exit
from ..stacks.util import BaseConnIter
from ..proto.stream import SingleAnyioBuf

class TcpIter(BaseConnIter):
    """
    A connection iterator for Unix sockets
    """
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port

    async def accept(self) -> Never:
        li = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        async with li:
            self.ready()
            await li.serve(self._handle)

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
