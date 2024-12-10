"""
Compatibility wrappers that allows MoaT code to run on CPython/anyio as
well as MicroPython/uasyncio.

Well, for the most part.
"""

from __future__ import annotations

import anyio as _anyio
import logging
import os
import sys
import time as _time
import traceback as _traceback
from concurrent.futures import CancelledError
from contextlib import suppress
from inspect import currentframe

from .queue import Queue as _Queue
from .queue import QueueEmpty, QueueFull

try:
    import greenback
except ImportError:
    greenback = None


logger = logging.getLogger(__name__)

__all__ = [
    "log",
    "const",
    "CancelScope",
    "Queue",
    "print_exc",
    "ticks_ms",
    "sleep_ms",
    "wait_for",
    "wait_for_ms",
    "every_ms",
    "every",
    "idle",
    "ticks_add",
    "ticks_diff",
    "run",
    "TaskGroup",
    "run_server",
    "shield",
]


Pin_IN = 0
Pin_OUT = 1

Event = _anyio.Event
Lock = _anyio.Lock
WouldBlock = _anyio.WouldBlock
sleep = _anyio.sleep
EndOfStream = _anyio.EndOfStream
BrokenResourceError = _anyio.BrokenResourceError
ClosedResourceError = _anyio.ClosedResourceError
TimeoutError = TimeoutError  # noqa:PLW0127,A001 pylint:disable=redefined-builtin,self-assigning-variable


def const(_x):
    "µPython compatibility"
    return _x


class CancelScope:
    """
    An async-await-able CancelScope wrapper
    """

    def __init__(self):
        self.sc = _anyio.CancelScope()

    async def __aenter__(self):
        self.sc.__enter__()
        return self

    async def __aexit__(self, *tb):
        return self.sc.__exit__(*tb)

    def cancel(self):
        "Cancel the scope"
        self.sc.cancel()

    @property
    def cancelled(self):
        "Was 'cancel' called on this scope?"
        return self.sc.cancel_called()


def log(s, *x, err=None, nback=1):
    "Basic logger.debug/error call (depends on @err)"
    caller = currentframe()
    for _ in range(nback):
        if caller.f_back is None:
            break
        caller = caller.f_back
    log_ = logging.getLogger(caller.f_globals["__name__"])
    (log_.debug if err is None else log_.error)(s, *x, exc_info=err, stacklevel=1 + nback)
    if err and int(os.getenv("LOG_BRK", "0")):
        breakpoint()  # noqa:T100 pylint:disable=forgotten-debug-statement


def print_exc(exc):
    "print a stack trace to stderr"
    _traceback.print_exception(type(exc), exc, exc.__traceback__)


def ticks_ms():
    "return a monotonic timer, in milliseconds"
    return _time.monotonic_ns() // 1000000


async def sleep_ms(ms):
    "sleep for @ms milliseconds"
    await sleep(ms / 1000)


async def wait_for(timeout, p, *a, **k):  # noqa:ASYNC109
    "timeout if the call to p(*a,**k) takes longer than @timeout seconds"
    with _anyio.fail_after(timeout):
        return await p(*a, **k)


async def wait_for_ms(timeout, p, *a, **k):  # noqa:ASYNC109
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
    while True:  # noqa:ASYNC110
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
_tgt = None


def TaskGroup():
    "A TaskGroup subclass (generator) that supports `spawn` and `cancel`"

    global _tg, _tgt  # noqa:PLW0603 pylint:disable=global-statement
    if "pytest" in sys.modules or _tgt is None:  # noqa:SIM108
        tgt = type(_anyio.create_task_group())
    else:
        tgt = _tgt
    if tgt is not _tgt:
        _tgt = tgt

        class TaskGroup_(_tgt):
            """An augmented taskgroup"""

            async def spawn(self, p, *a, _name=None, **k):
                """
                Like start(), but returns something you can cancel
                """
                # logger.info("Launch %s %s %s %s",_name, p,a,k)

                async def catch(p, a, k, *, task_status):
                    with _anyio.CancelScope() as s:
                        task_status.started(s)
                        if greenback is not None:
                            await greenback.ensure_portal()
                        with suppress(CancelledError):  # error from concurrent.futures
                            await p(*a, **k)

                return await super().start(catch, p, a, k, name=_name)

            def cancel(self):
                "cancel all tasks in this taskgroup"
                self.cancel_scope.cancel()

        _tg = TaskGroup_
    return _tg()


async def run_server(cb, host, port, backlog=5, taskgroup=None, reuse_port=True, evt=None):
    """Listen to and serve a TCP stream.

    This mirrors [u]asyncio, except that the callback gets the socket once.
    """
    listener = await _anyio.create_tcp_listener(
        local_host=host,
        local_port=port,
        backlog=backlog,
        reuse_port=reuse_port,
    )
    async with listener:
        if evt is not None:
            evt.set()
        await listener.serve(cb, task_group=taskgroup)


def shield():
    """A wrapper shielding the contents from external cancellation.

    Equivalent to ``CancelScope(shield=True)``.
    """
    return _anyio.CancelScope(shield=True)


class Queue(_Queue):
    """
    compatibility mode: raise `EOFError` and `QueueEmpty`/`QueueFull`
    instead of `anyio.EndOfStream` and `anyio.WouldBlock`
    """

    async def get(self):  # noqa:D102
        try:
            return await super().get()
        except _anyio.EndOfStream:
            raise EOFError from None

    def get_nowait(self):  # noqa:D102
        try:
            return super().get_nowait()
        except _anyio.EndOfStream:
            raise EOFError from None
        except _anyio.WouldBlock:
            raise QueueEmpty from None

    def put_nowait(self, x):  # noqa:D102
        try:
            super().put_nowait(x)
        except _anyio.WouldBlock:
            raise QueueFull from None
