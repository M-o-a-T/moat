"""
Connection handling for Unix sockets
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


class UnixIter(BaseConnIter):
    """
    A connection iterator for Unix sockets.

    @path: the socket file to listen on
    """

    def __init__(self, path):
        super().__init__()
        self.path = path

    async def accept(self) -> Never:  # noqa:D102
        li = await anyio.create_unix_listener(self.path)
        async with li:
            if L:
                self.set_ready()
            await li.serve(self._handle)

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
