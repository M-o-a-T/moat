from __future__ import annotations

import anyio
from moat.util.queue import Queue

from ..compat import TaskGroup, Event, ACM, AC_exit
from ..stacks.util import BaseConnIter
from ..proto.stream import SingleAnyioBuf

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.


class UnixIter(BaseConnIter):
    def __init__(self, path):
        super().__init__()
        self.path = path

    async def accept(self) -> Never:
        li = await anyio.create_unix_listener(self.path)
        self.ready()
        await li.serve(self._handle)

    async def _handle(self, client):
        await self.add_conn(SingleAnyioBuf(client))
