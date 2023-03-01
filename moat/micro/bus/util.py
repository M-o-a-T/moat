import trio
from contextlib import contextmanager, asynccontextmanager

class CtxObj:
    """
    Add an async context manager that calls `_ctx` to run the context.

    Usage::
        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self # or whatever

        async with Foo() as self_or_whatever:
            pass
    """
    __ctx = None
    def __aenter__(self):
        if self.__ctx is not None:
            raise RuntimeError("Double context")
        self.__ctx = ctx = self._ctx()
        return ctx.__aenter__()

    def __aexit__(self, *tb):
        ctx,self.__ctx = self.__ctx,None
        return ctx.__aexit__(*tb)

class Dispatcher:
    """
    Adds a registry and a dispatcher to an object.
    """
    def __init__(self):
        self.__dispatch = {}
        super().__init__()

    async def dispatch(self, msg):
        """Dispatch a message"""
        k = self.get_code(msg)
        try:
            d = self.__dispatch[k]
        except KeyError:
            logger.debug("No dispatcher for %r in %s",msg,self)
            return
        await d(msg)
    
    def get_code(self, msg):
        """Get dispatch code for this message"""
        raise NotImplementedError("I have no idea how to dispatch anything")

    def register(self, code, dispatcher):
        """Register a control dispatcher"""
        if code in self.__dispatch:
            raise KeyError(code)
        self.__dispatch[code] = dispatcher

    def deregister(self, code):
        """Remove a control dispatcher registration"""
        del self.__dispatch[code]

    @contextmanager
    def with_code(self, code):
        """
        Returns an async iterator for messages with this code,
        defined as whatever `get_code` returns

        This is a (non-async) context manager.
        """
        q_w,q_r = trio.open_memory_channel(100)
        self.register(code, q_w.send)
        try:
            yield q_r
        finally:
            self.deregister(code)

    async def with_code_bg(self, code, func, *args, n=3, timeout=0.1):
        """
        Runs max. `n` functions `func` for handling messages with this code
        in parallel, waiting `timeout` seconds for a free slot before
        starting another worker task.

        Worker tasks don't terminate when fewer would (again) suffice.
        """
        q_w,q_r = trio.open_memory_channel(0)
        self.register(code,put)

        async def runner(q):
            async for msg in q_r:
                await func(msg)

        try:
            async with trio.open_nursery() as tg:
                tg.start_soon(runner)
                n -= 1
                with self.with_code(code) as mq:
                    async for msg in mq:
                        if not n:
                            # All slots occupied. Block.
                            await q_w.send(msg)
                            continue
                        with trio.move_on_after(timeout):
                            # Wait for processing.
                            await q_w.send(msg)
                            continue
                        # Wait was unsuccessful. Start another slot.
                        tg.start_soon(runner)
                        n -= 1
                        await q_w.send(msg)
        finally:
            self.deregister(code)


class _SubServer:
    """
    a subordinate server.
    """
    CODE=None

    def __init__(self, server, code=None):
        self._server = server
        self._back = server._back

        self._code = code if code is not None else self.CODE
        if self._code is None:
            raise NotImplementedError("You neet to override the CODE attribute")

        self.my_id = server.my_id

        self.send = server.send
        self.reply = server.reply
        self.send_msg = server.send_msg
        self.objs = server.objs

        super().__init__()

    async def send_msg(self, msg):
        await self._back.send(msg)


class SubDispatcher(_SubServer, CtxObj, Dispatcher):
    """
    Implements a registered dispatcher.

    Get code-`code` messages from the server.
    """

    @asynccontextmanager
    async def _ctx(self):
        async with trio.open_nursery() as n:
            await n.start(self._dispatch_loop)
            yield self

    async def _dispatch_loop(self, *, task_status=trio.TASK_STATUS_IGNORED):

        with self._server.with_code(self.CODE) as q:
            task_status.started()
            async for msg in q:
                await self.dispatch(msg)


class Processor(_SubServer, CtxObj):
    """
    Implements a dispatcher client.

    This is an async context manager. It yields a channel which you must
    iterate to process the results, assuming your `process` method `put`s
    any.
    """

    async def setup(self):
        """
        Additional initialization code, running when everything's active.
        """
        pass

    async def process(self, msg):
        """
        The actual message processing.
        """
        raise NotImplementedError("You forgot to override %s.process" % (self.__class__.__name__,))

    @asynccontextmanager
    async def _ctx(self):
        async with trio.open_nursery() as n:
            self.__nursery = n
            self._q_w, q_r = trio.open_memory_channel(100)
            await self.setup()
            await n.start(self._process_loop)
            yield q_r

    async def _process_loop(self, *, task_status=trio.TASK_STATUS_IGNORED):
        with self._server.with_code(self.CODE) as q:
            task_status.started()
            async for msg in q:
                await self.process(msg)

    async def put(self, data):
        await self._q_w.send(data)

    async def spawn(self, p,*a, _name=None, **k):
        """
        Start a background task on this processor's nursery.
        Returns a cancel scope which you can use to kill the task.
        """
        async def job(p,a,k,*,task_status=trio.TASK_STATUS_IGNORED):
            with trio.CancelScope() as sc:
                task_status.started(sc)
                await p(*a,**k)

        return await self.__nursery.start(job, p,a,k)


# minifloat granularity
MINI_F = 1/4

def mini2byte(f):
    """
    Convert a float to a byte-sized minifloat.

    The byte-sized minifloat accepted by `mini2byte` and returned by
    `byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
    overrun/infinity signalling (while 0xFF can be used as such if
    desired, that's not covered by this code).

    It can thus accept values from 0…8 in steps of 0.25, 0.5 to 16, 1 to 32,
    and so on, until steps of 4096 from 65536 to 126976 / 122880, which is
    more than a day. It is thus suited well for timeouts with variable
    granularity that don't take up much space.
    """

    f = int(f/MINI_F+0.5)
    if f <= 0x20:  # < 0x10: in theory, but the result is the same
        return f  # exponent=0 is denormalized
    exp = 1
    while f > 0x1F: # the top bit is set because of normalization
        f >>= 1
        exp += 1
    if exp > 0x0F:
        return 0xFF
    return (exp<<4) | (f&0x0F)
    # The mantissa is normalized, i.e. the top bit is always 1, thus it is
    # discarded and not included in the result.

def byte2mini(m):
    """
    Convert a byte-sized minifloat back to a number.
    """
    if m <= 32:  # or 16, doesn't matter
        return m*MINI_F
    exp = (m>>4)-1
    m = 0x10+(m&0xf)  # normalization
    return (1<<exp)*m*MINI_F


if __name__ == "__main__":
    for x in range(256):
        print(x,byte2mini(x),mini2byte(byte2mini(x)))

