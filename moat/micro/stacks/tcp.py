"""
Connection handling for TCP sockets
"""

from __future__ import annotations

import anyio

from moat.micro.proto.stream import SingleAnyioBuf
from moat.util.compat import L

from .util import BaseConnIter

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Never


class TcpIter(BaseConnIter):
    """
    A connection iterator for TCP sockets

    @host: address to listen on. No default!

    @port: port to listen on. No default.
    """

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port

    async def accept(self) -> Never:  # noqa:D102
        li = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        async with li:
            if L:
                self.set_ready()
            await li.serve(self._handle)

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
