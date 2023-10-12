import sys

from asyncio.queues import Queue

from ..compat import TaskGroup, run_server, AC_use
from ..proto.stream import AIOStream
from moat.util import Lockstep


async def listen_msg(host="0.0.0.0", port=0): # type: Iterator[BaseMsg]
    """
    This async context manager returns an async iterator for new network
    connections on a given host/port listener socket.

    The caller is responsible for properly closing each stream:
    its (async) context must be entered exactly once.
    """


    srv = None
    n = 0
    tg = await AC_use(self, TaskGroup())
    await AC_use(self, tg.cancel)

    class Getter(Lockstep):
        async def __anext__(self):
            s = await super().__anext__()
            return AIOStream(self.s)

        async def put(s, rs):
            assert s == rs
            try:
                await super().put(s)
            except BaseException:
                s.close()
                await s.wait_closed()
                raise

    await tg.spawn(run_server, enq, host, port, _name="run_server")

    return Getter()
