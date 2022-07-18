import sys

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.

from ..compat import run_server, Event, print_exc
from ..cmd import Request
from ..proto.stream import MsgpackHandler

async def network_stack_iter(log=False, multiple=False, host="0.0.0.0", port=27176):
    # an iterator for network connections / their stacks. Yields one t,b
    # pair for each successful connection.

    # If @multiple is False there can be only one connection, i.e. you run
    # the returned stack directly, the listener socket will be re-opened
    # when you re-enter the iterator.
    #
    # Otherwise there can be multiple connections, i.e. run the returned
    # stack in a taskgroup.

    if log:
        from .proto import Logger

    q=Queue(2)
    async def make_stack(s,rs):
        assert s is rs
        await q.put(s)

    try:
        async with TaskGroup() as tg:
            srv = None
            n = 0
            while True:
                n += 1
                if srv is None:
                    srv = await tg.spawn(uasyncio.run_server, make_stack, self.host,self.port)

                s = await q.get()
                if not multiple:
                    srv.cancel()
                    srv = None

                t = b = MsgpackHandler(s)
                if log:
                    t = t.stack(Logger, txt="N%d" % n)
                t = t.stack(request_factory)
                await q.put((t,b))
                yield t,b

    except SystemExit:
        raise
    except BaseException as exc:
        print_exc(exc)
        if srv is not None:
            srv.cancel()


