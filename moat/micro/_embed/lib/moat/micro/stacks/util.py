"""
Basic handler for iterating incoming Moat connections.
"""

from __future__ import annotations

from moat.util import Queue
from moat.micro.compat import TaskGroup, ACM, AC_exit, Event, shield, AC_use

class BaseConnIter:
    """
    Iterate incoming connections.

    You need to override "accept".
    """
    def __init__(self):
        self.q = Queue(1)
        self.evt = Event()

    async def __aenter__(self):
        self.tg = await ACM(self)(TaskGroup())
        await self.tg.spawn(self.accept)
        return self

    async def __aexit__(self, *exc):
        await AC_exit(self,*exc)

    def set_ready(self) -> None:
        self.evt.set()

    def is_ready(self) -> Awaitable:
        return self.evt.wait()

    def add_conn(self, c: BaseConn) -> Awaitable:
        return self.q.put(c)

    async def accept(self) -> Never:
        """
        Background task to accept incoming connections.

        Call ``await self.add_conn(conn)`` for each connection.

        Call ``self.ready()`` as soon as the socket-or-whatever is ready to accept links.
        """
        raise NotImplementedError

    def __aiter__(self):
        return self

    def __anext__(self) -> Awaitable[BaseConn]:
        return self.q.get()
