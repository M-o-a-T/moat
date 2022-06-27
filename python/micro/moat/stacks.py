from .cmd import MsgpackConsHandler,MsgpackHandler,Logger,Request,SerialPackerHandler

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.


async def console_stack(stream=sys.stdin.buffer, reliable=False, log=False, log_bottom=False):
    # TODO
    # 
    # set @reliable if your console already guarantees lossless
    # transmission (e.g. via USB).
    from .proto.stream import MsgpackConsHandler,SerialPackerHandler
    if reliable:
        b = MsgpackConsHandler(AsyncStream(stream))
    else:
        b = SerialPackerHandler(AsyncStream(stream))

    t = b
    if not reliable:
        if log_bottom:
            t = await t.stack(Logger)
        t = await t.stack(Reliable)
    if log:
        t = await t.stack(Logger)
    t = await t.stack(Request)
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
                    t = t.stack(Logger)
                t = await t.stack(Request)
                yield t,h[0]

    except BaseException as exc:
        print_exc(exc)
        if srv is not None:
            srv.cancel()



async def network_stack(log=False, host="0.0.0.0", port=17388):


