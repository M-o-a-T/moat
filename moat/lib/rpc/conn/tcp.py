"""
Connection handling for TCP sockets
"""

from __future__ import annotations

import anyio
from anyio.abc import SocketAttribute

from moat.lib.micro import L
from moat.lib.stream import SingleAnyioBuf

from .util import BaseConnIter

# Typing
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Never


class TcpIter(BaseConnIter):
    """
    A connection iterator for TCP sockets

    @host: address to listen on. No default!

    @port: port to listen on. Use 0 for an OS-assigned port;
        the actual port is available via
        :attr:`~moat.lib.rpc.conn.util.BaseConnIter.port` after startup.
    """

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port

    async def accept(self) -> Never:  # noqa:D102
        assert self.port is not None
        li = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        if self.port == 0:
            self.port = cast(int, li.listeners[0].extra(SocketAttribute.local_address)[1])
            self._port_assigned()
        async with li:
            if L:
                self.set_ready()
            await li.serve(self._handle)
        raise RuntimeError("listener stopped")

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
