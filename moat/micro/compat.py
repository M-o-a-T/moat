"""
Compatibility wrappers that allows MoaT code to run on CPython/anyio as
well as MicroPython/asyncio.

Well, for the most part.
"""
import logging
import time as _time
import traceback as _traceback
from concurrent.futures import CancelledError

import anyio as _anyio
import greenback

def const(_x):
    return _x

logger = logging.getLogger(__name__)

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

def log(s, *x, err=None):
    caller = currentframe().f_back
    logger = logging.getLogger(caller.f_globals["__name__"])
    (logger.debug if err is None else logger.error)(s,*x, exc_info=err)


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
                nonlocal logger
                logger.info("Launch %s %s %s %s",_name, p,a,k)

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

