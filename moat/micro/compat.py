"""
Compatibility wrappers that allows MoaT code to run on CPython/anyio as
well as MicroPython/asyncio.

Well, for the most part.
"""
import os
import logging
import time as _time
import traceback as _traceback
from concurrent.futures import CancelledError
from contextlib import AsyncExitStack
from inspect import iscoroutinefunction

import anyio as _anyio
import greenback

def const(_x):
    return _x

logger = logging.getLogger(__name__)

ExceptionGroup = ExceptionGroup
BaseExceptionGroup = BaseExceptionGroup

Pin_IN = 0
Pin_OUT = 1

Event = _anyio.Event
Lock = _anyio.Lock
WouldBlock = _anyio.WouldBlock
sleep = _anyio.sleep
EndOfStream = _anyio.EndOfStream
BrokenResourceError = _anyio.BrokenResourceError
TimeoutError = TimeoutError  # pylint:disable=redefined-builtin,self-assigning-variable

from inspect import currentframe

def log(s, *x, err=None, nback=1):
    caller = currentframe()
    while nback:
        if caller.f_back is None:
            break
        caller = caller.f_back
        nback -= 1
    logger = logging.getLogger(caller.f_globals["__name__"])
    (logger.debug if err is None else logger.error)(s,*x, exc_info=err)
    if err and int(os.getenv("LOG_BRK",False)):
        breakpoint()
        pass # ERROR: err


def print_exc(exc):
    "print a stack trace to stderr"
    _traceback.print_exception(type(exc), exc, exc.__traceback__)


def ticks_ms():
    "return a monotonic timer, in milliseconds"
    return _time.monotonic_ns() // 1000000


async def sleep_ms(ms):
    "sleep for @ms milliseconds"
    await sleep(ms / 1000)


async def wait_for(timeout, p, *a, **k):
    "timeout if the call to p(*a,**k) takes longer than @timeout seconds"
    with _anyio.fail_after(timeout):
        return await p(*a, **k)


async def wait_for_ms(timeout, p, *a, **k):
    "timeout if the call to p(*a,**k) takes longer than @timeout milliseconds"
    with _anyio.fail_after(timeout / 1000):
        return await p(*a, **k)


async def every_ms(t, p, *a, **k):
    "every t milliseconds, call p(*a,**k)"
    tt = ticks_add(ticks_ms(), t)
    while True:
        try:
            yield await p(*a, **k)
        except StopAsyncIteration:
            return
        tn = ticks_ms()
        td = ticks_diff(tt, tn)
        if td > 0:
            await sleep_ms(td)
            tt += t
        else:
            # owch, delay too long
            tt = ticks_add(tn, t)


def every(t, p, *a, **k):
    "every t seconds, call p(*a,**k)"
    return every_ms(t * 1000, p, *a, **k)


async def idle():
    "sleep forever"
    while True:
        await _anyio.sleep(60 * 60 * 12)  # half a day


def ticks_add(a, b):
    "returns a+b"
    return a + b


def ticks_diff(a, b):
    "returns a-b"
    return a - b


def run(p, *a, **k):
    "wrapper for anyio.run"
    return _anyio.run(p, a, k)


_tg = None


def TaskGroup():
    "A TaskGroup subclass (generator) that supports `spawn` and `cancel`"
    global _tg  # pylint:disable=global-statement

    caller = currentframe().f_back
    logger = logging.getLogger(caller.f_globals["__name__"])

    if _tg is None:
        _tgt = type(_anyio.create_task_group())

        class TaskGroup_(_tgt):
            """An augmented taskgroup"""

            async def spawn(self, p, *a, _name=None, **k):
                """\
                    Like start(), but returns something you can cancel
                """
                # nonlocal logger
                # logger.info("Launch %s %s %s %s",_name, p,a,k)

                async def catch(p, a, k, *, task_status):
                    with _anyio.CancelScope() as s:
                        task_status.started(s)
                        await greenback.ensure_portal()
                        try:
                            await p(*a, **k)
                        except CancelledError:  # error from concurrent.futures
                            pass

                return await super().start(catch, p, a, k, name=_name)

            def cancel(self):
                "cancel all tasks in this taskgroup"
                self.cancel_scope.cancel()

        _tg = TaskGroup_
    return _tg()


async def run_server(cb, host, port, backlog=5, taskgroup=None, reuse_port=True):
    """Listen to and serve a TCP stream.

    This mirrors [u]asyncio, including the fact that the callback gets the
    socket twice.
    """
    listener = await _anyio.create_tcp_listener(
        local_host=host, local_port=port, backlog=backlog, reuse_port=reuse_port
    )

    await listener.serve(lambda sock: cb(sock, sock), task_group=taskgroup)

# async context stack


def ACM(obj):
    """A bare-bones async context manager.
    
    Usage::

        class Foo():
            async def __aenter__(self):
                AC = ACM(obj)  
                ctx1 = await AC(obj1)
                ctx2 = await AC_use(self, obj2)  # same thing
                ...
            async def __aexit__(self, *exc):
                return await AC_exit(self, *exc)
    
    Calls to `ACM` and `AC_exit` can be nested. They **must** balance.
    """
        
    if not hasattr(obj,"_AC_"):
        obj._AC_ = []

    cm = AsyncExitStack()
    obj._AC_.append(cm)

    # AsyncExitStack.__aenter__ is a no-op. We don't depend on that but at
    # least it shouldn't yield
    # log("AC_Enter",nback=2)
    try:
        cr = cm.__aenter__()
        cr.send(None)
    except StopIteration as s:
        cm = s.value
    else:
        raise RuntimeError("AExS ??")

    def _ACc(ctx):
        return AC_use(obj, ctx)
    return _ACc

async def AC_use(obj, ctx):
    acm = obj._AC_[-1]
    # log("AC_Use %r",ctx,nback=2)
    if hasattr(ctx,"__aenter__"):
        return await acm.enter_async_context(ctx)
    elif hasattr(ctx,"__enter__"):
        return acm.enter_context(ctx)
    elif iscoroutinefunction(ctx):
        acm.push_async_callback(ctx)
    else:
        acm.callback(ctx)
    return None

async def AC_exit(obj, *exc):
    # log("AC_End",nback=2)
    if not exc:
        exc = (None,None,None)
    return await obj._AC_.pop().__aexit__(*exc)
