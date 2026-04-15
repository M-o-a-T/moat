"""
Connection handling for websocket listeners.
"""

from __future__ import annotations

import anyio

from moat.lib.micro import L
from moat.lib.stream import SingleWsBlk

from .util import BaseConnIter

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Never


class WsIter(BaseConnIter):
    """
    A connection iterator for websocket connections.

    @host: address to listen on. No default.

    @port: port to listen on. No default.

    @path: websocket path. Defaults to ``/``.
    """

    def __init__(self, host, port, path="/"):
        super().__init__()
        self.host = host
        self.port = port
        self.path = path

    async def accept(self) -> Never:  # noqa:D102
        li = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        async with li:
            if L:
                self.set_ready()
            await li.serve(self._handle)
        raise RuntimeError("listener stopped")

    async def _handle(self, client):
        await self.add_conn(SingleWsBlk(client, path=self.path))
