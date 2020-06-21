#
# This code implements the basics for a bus master.

import trio
from contextlib import asynccontextmanager

from .backend import BaseBusHandler
from .message import BusMessage

class Master:
    def __init__(self, backend:BaseBusHandler):
        self._back = backend

    def __aenter__(self):
        self.__ctx = ctx = self._ctx()
        return ctx.__aenter__()

    def __aexit__(self, *tb):
        ctx = self.__ctx
        del self.__ctx
        return ctx.__aexit__(*tb)

    @asynccontextmanager
    async def _ctx(self):
        async with trio.open_nursery() as n:
            await n.start(self._reader)
            try:
                yield self
            finally:
                n.cancel_scope.cancel()

    async def _reader(self, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        async for msg in self._back:
            print(msg)

    async def send(self, src, dest, code, data=b'', prio=0):
        msg = BusMessage()
        msg.start_send()
        msg.src = src
        msg.dst = dest
        msg.code = code
        msg.send_data(data)

        await self._back.send(msg, prio)

    async def reply(self, msg, src=None,dest=None,code=None, data=b'', prio=0):
        if src is None:
            src=msg.dst
        if dest is None:
            dest = msg.src
        if code is None:
            code = 3  # standard reply
        await self.send(src,dest,code,data=data,prio=prio)
