import sys

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.

import logging
logger = logging.getLogger(__name__)

async def console_stack(stream=sys.stdin.buffer, s2=None, reliable=False, log=False, log_bottom=False, console=False, force_write=False):
    # Set s2 for a separate write stream.
    #
    # Set force_write if select-for-write doesn't work on your stream.
    # 
    # set @reliable if your console already guarantees lossless
    # transmission (e.g. via USB).
    from .cmd import Request

    if log or log_bottom:
        from .proto import Logger
    if hasattr(stream,"aclose"):
        assert s2 is None
        assert not force_write
        s = stream
    else:
        from .proto.stream import AsyncStream
        s = AsyncStream(stream, s2, force_write)

    cons_h = None
    if console:
        c_b = bytearray()
        def cons_h(b):
            nonlocal c_b
            if b == 10:
                logger.info("C:%s", c_b.decode("ascii"))
                c_b = bytearray()
            elif b != 13:
                c_b.append(b)

    if reliable:
        from .proto.stream import MsgpackStream
        t = b = MsgpackStream(s, console=cons_h)
    else:
        from .proto.stream import MsgpackHandler, SerialPackerStream

        t = b = SerialPackerStream(s, console=cons_h)
        t = t.stack(MsgpackHandler)

        if log_bottom:
            t = t.stack(Logger, txt="Rel")
        from .proto.reliable import Reliable
        t = t.stack(Reliable)
    if log:
        t = t.stack(Logger, txt="Msg")
    t = t.stack(Request)
    return t,b


async def network_stack_iter(log=False, multiple=False, host="0.0.0.0", port=27176):
    # an iterator for network connections / their stacks. Yields one t,b
    # pair for each successful connection.

    # If @multiple is False there can be only one connection, i.e. you run
    # the returned stack directly, the listener socket will be re-opened
    # when you re-enter the iterator.
    #
    # Otherwise there can be multiple connections, i.e. run the returned
    # stack in a taskgroup.

    from moat.compat import run_server, Event
    from .proto.stream import MsgpackHandler
    from .cmd import Request
    if log:
        from .proto import Logger

    async def runner(h,e,s,rs):
        assert s is rs
        h[0] = MsgpackHandler(s)
        e.set()

    try:
        async with TaskGroup() as tg:
            srv = None
            while True:
                e = Event()
                h = [None]
                if srv is None:
                    srv = await tg.spawn(uasyncio.run_server,partial(runner,h,e),self.host,self.port, taskgroup=tg)
                await e.wait()
                if not multiple:
                    srv.cancel()
                    srv = None

                t = h[0]
                if log:
                    t = t.stack(Logger, txt="Msg")
                t = t.stack(Request)
                yield t,h[0]

    except BaseException as exc:
        print_exc(exc)
        if srv is not None:
            srv.cancel()


