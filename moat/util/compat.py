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
from contextlib import suppress, AsyncExitStack
from inspect import currentframe, iscoroutinefunction, iscoroutine
from codecs import utf_8_decode

from .queue import Queue as _Queue
from .queue import QueueEmpty, QueueFull
from moat.util.merge import merge

logger = logging.getLogger(__name__)

__all__ = [
    "is_async",
    "doc",
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
    "byte2utf8",
    "TaskGroup",
    "run_server",
    "shield",
    "Event",
    "Lock",
    "L",
    "WouldBlock",
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
TimeoutError = TimeoutError  # noqa:PLW0127,A001
ExceptionGroup = ExceptionGroup  # noqa: PLW0127
BaseExceptionGroup = BaseExceptionGroup  # noqa: PLW0127


def const(_x):
    "µPython compatibility"
    return _x


L = True

Pin_IN = 0
Pin_OUT = 1


def byte2utf8(buf: bytes | bytearray | memoryview) -> str:
    res, n = utf_8_decode(buf)
    if n != len(buf):
        raise ValueError("incomplete utf8")
    return res


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


def print_exc(exc, file=None):
    "print a stack trace to stderr"
    _traceback.print_exception(type(exc), exc, exc.__traceback__, file=file)


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
_tgt = None


def TaskGroup():
    "A TaskGroup subclass (generator) that supports `spawn` and `cancel`"

    global _tg, _tgt  # noqa:PLW0603 pylint:disable=global-statement
    if "pytest" in sys.modules or _tgt is None:
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


def _doc(_c=None, **kw):
    """
    Attach structured documentation to a function.

    This is used for command handlers because we want to (a) not add a heap
    of obscure typing to the Message parameter that'd need to be serialozed
    somehow, (b) support introspectable doc for MicroPython which has no typing
    infrastructure.

    Keywords:
    _c: copy+extend Upstream
    _d: very short Documentation, free text
    _r: Return value
    _i: Input stream type
    _o: Output stream type
    _a: Any keyword params
    _m: first optional field
    _NUM: positional arg
    _99: positional arg trailer
    NAME: keyword arg

    All values are of the form `type`, `type:short documentation`, a dict
    (as above, except no NUMs), or a list (positional values, like typing
    w/ tuples). A trailing question mark on the type indicates "or None".
    (This doesn't necessarily mean the same as not sending the value at all.)

    Typically the return value is a single data item; if not you can set
    '_r' to a dict with the above components.

    The list of possibly-missing fields may include "i" and "o".
    If any positional arguments are optional, only the first should be given.
    Keyword args are always optional.

    The result type "parts" describes a two-element tuple: a dict/list with
    complex items removed plus a list of sub-keys to retrieve for restoring
    the data. This is used to limit the max block size.
    """
    if _c is not None:
        merge(kw, _c._moat__doc, replace=False)

    def mod(fn):
        fn._moat__doc = kw
        return fn

    return mod


# async context stack


def ACM(obj):
    """A bare-bones async context manager / async exit stack.

    Usage::

        class Foo():
            async def __aenter__(self):
                AC = ACM(obj)
                try:
                    ctx1 = await AC(obj1)
                    ctx2 = await AC_use(self, obj2)  # same thing
                    ...
                    return self_or_whatever

                except BaseException:
                    await AC_exit(self, *exc)
                    raise

            async def __aexit__(self, *exc):
                return await AC_exit(self, *exc)

    Calls to `ACM` and `AC_exit` can be nested, even on the same object.
    They **must** balance, hence the above error handling dance.
    """
    # pylint:disable=protected-access
    if not hasattr(obj, "_AC_"):
        obj._AC_ = []

    cm = AsyncExitStack()
    obj._AC_.append(cm)

    # AsyncExitStack.__aenter__ is a no-op. We don't depend on that but at
    # least it shouldn't yield
    # log("AC_Enter",nback=2)
    try:
        # pylint:disable=no-member,unnecessary-dunder-call
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
    """
    Add an async context to this object's AsyncExitStack.

    If the object is a context manager (async or sync), this opens the
    context and return its value.

    Otherwise it's a callable and will run on exit.
    """
    acm = obj._AC_[-1]
    if hasattr(ctx, "__aenter__"):
        return await acm.enter_async_context(ctx)
    elif hasattr(ctx, "__enter__"):
        return acm.enter_context(ctx)
    elif iscoroutinefunction(ctx):
        acm.push_async_callback(ctx)
    elif iscoroutine(ctx):
        raise ValueError(ctx)
    else:
        acm.callback(ctx)
    return None


async def AC_exit(obj, *exc):
    """End the latest AsyncExitStack opened by `ACM`."""
    if not exc:
        exc = (None, None, None)
    return await obj._AC_.pop().__aexit__(*exc)


def is_async(obj):
    if hasattr(obj, "__await__"):
        return True
    return False
