from __future__ import annotations

import anyio
from moat.util.queue import Queue

from ..compat import ACM, AC_exit, Event, TaskGroup
from ..proto.stream import SingleAnyioBuf
from ..stacks.util import BaseConnIter

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Never


class UnixIter(BaseConnIter):
    """
    A connection iterator for Unix sockets
    """

    def __init__(self, path):
        super().__init__()
        self.path = path

    async def accept(self) -> Never:
        li = await anyio.create_unix_listener(self.path)
        async with li:
            self.set_ready()
            await li.serve(self._handle)

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
