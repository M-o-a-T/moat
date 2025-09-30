"""
A heap of compatibility code that adapts CPython and MicroPython
to something roughly equivalent.
"""

from __future__ import annotations

import sys
from inspect import iscoroutine
from time import ticks_add, ticks_diff, ticks_ms

from async_queue import Queue, QueueEmpty, QueueFull  # noqa:F401

import asyncio
from micropython import const

from typing import TYPE_CHECKING  # isort:skip

from rtc import set_rtc

if TYPE_CHECKING:
    from typing import Never


def _l():
    import os  # noqa: PLC0415

    try:
        os.stat("moat.lrg")
    except OSError:
        return False
    else:
        return True


L = _l()
del _l

Event = asyncio.Event
Lock = asyncio.Lock
sleep = asyncio.sleep
sleep_ms = asyncio.sleep_ms
TimeoutError = asyncio.TimeoutError  # noqa:A001
_run = asyncio.run
_tg = asyncio.TaskGroup
CancelledError = asyncio.CancelledError


ExceptionGroup = asyncio.ExceptionGroup  # noqa: A001
BaseExceptionGroup = asyncio.BaseExceptionGroup  # noqa: A001

DEBUG = const(False)


class EndOfStream(Exception):
    "as from anyio"


class BrokenResourceError(Exception):
    "as from anyio"


try:
    from machine import Pin
except ImportError:  # µPy on Linux
    Pin_IN = "IN"
    Pin_OUT = "OUT"
else:
    Pin_IN = Pin.IN
    Pin_OUT = Pin.OUT

WouldBlock = (QueueFull, QueueEmpty)


def byte2utf8(buf):  # noqa: D103
    if not hasattr(buf, "decode"):
        buf = bytes(buf)
    return buf.decode("utf-8")


def print_exc(exc, file=None):
    "forwards to sys.print_exception"
    if file is None:
        file = sys.stderr
    sys.print_exception(exc, file)


def log(s, *x, err=None):
    "Basic logger.debug/error call (depends on @err)"
    if x:
        s = s % x
    print(s, file=sys.stderr)
    if err is not None:
        sys.print_exception(err, sys.stderr)


def at(*a, **kw):  # noqa: D103
    set_rtc("debug", a if not kw else kw if not a else (a, kw), fs=False)


async def idle():
    "sleep forever"
    while True:
        await sleep(60 * 60 * 12)  # half a day


def wait_for(timeout, p, *a, **k):
    """
    asyncio.wait_for() but with sane calling convention
    """
    return asyncio.wait_for(p(*a, **k), timeout)


def wait_for_ms(timeout, p, *a, **k):
    """
    asyncio.wait_for_ms() but with sane calling convention
    """
    return asyncio.wait_for_ms(p(*a, **k), int(timeout))


class _MsecIter:
    tt = None

    def __init__(self, t, p, a, k):
        self.t = t
        self.p, self.a, self.k = p, a, k

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.tt is None:
            self.tt = ticks_add(ticks_ms(), self.t)
        else:
            tn = ticks_ms()
            if (td := ticks_diff(self.tt, tn)) > 0:
                await sleep_ms(td)
                self.tt = ticks_add(self.tt, self.t)
            else:
                # owch, delay too long
                self.tt = ticks_add(tn, self.t)
        return await self.p(*self.a, **self.k)


def every_ms(t, p, *a, **k):
    "call a function every @t milliseconds"
    return _MsecIter(t, p, a, k)


def every(t, p, *a, **k):
    "call a function every @t seconds"
    return every_ms(t * 1000, p, *a, **k)


if DEBUG:

    async def _catch(n, p, *a, **k):
        try:
            print("RRR", n, file=sys.stderr)
            return await p(*a, **k)
        except Exception as exc:
            print("Error:", n, repr(exc), file=sys.stderr)
            print_exc(exc)
            raise
        else:
            print("Done:", n, file=sys.stderr)


class TaskGroup(_tg):
    "anyio.TaskGroup, lightly enhanced"

    async def spawn(self, p, *a, _name=None, **k):
        "Starts a task now. Returns something you can cancel."
        if DEBUG:
            print("RUN", _name, p, a, k, file=sys.stderr)
            return self.create_task(_catch(_name, p, *a, **k))  # , name=_name)
        else:
            return self.create_task(p(*a, **k))  # , name=_name)

    def start_soon(self, p, *a, _name=None, **k):
        "Starts a task soon."
        if DEBUG:
            print("RUN", _name, p, a, k, file=sys.stderr)
            self.create_task(_catch(_name, p, *a, **k))
        else:
            self.create_task(p(*a, **k))


def run(p, *a, **k):
    "like anyio.run"
    return _run(p(*a, **k))


# Helper task to run a TCP stream server.
# Callbacks (i.e. connection handlers) may run in a different taskgroup.
async def run_server(cb, host, port, backlog=5, taskgroup=None, evt=None) -> Never:
    """
    Task that runs a TCP stream server.
    Callbacks (i.e. connection handlers) may run in a different taskgroup.

    The optional event is set when the socket is listening.
    """
    import socket  # noqa: PLC0415

    # Create and bind server socket.
    host = socket.getaddrinfo(host, port)[0]  # TODO this is blocking!
    s = socket.socket()
    s.setblocking(False)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(host[-1])
    s.listen(backlog)
    if evt is not None:
        evt.set()

    try:
        if taskgroup is None:
            async with TaskGroup() as tg:
                await _run_server(tg, s, cb)
        else:
            await _run_server(taskgroup, s, cb)
    finally:
        s.close()


async def _run_server(tg, s, cb):
    from asyncio import core as _core  # noqa: PLC0415

    while True:
        if DEBUG:
            print("WaitServer", file=sys.stderr)
        yield _core._io_queue.queue_read(s)  # noqa:SLF001
        if DEBUG:
            print("WaitedServer", file=sys.stderr)
        try:
            s2, addr = s.accept()
        except Exception as err:
            # Ignore a failed accept
            print("ErrServer", repr(err), file=sys.stderr)
            continue

        if DEBUG:
            print("GotServer", file=sys.stderr)
        s2.setblocking(False)
        # XXX uasyncio implementation detail
        s2s = asyncio.StreamReader(s2, {"peername": addr})
        await tg.spawn(cb, s2s)


# minimal Outcome clone


class _Outcome:
    def __init__(self, val):
        self.val = val


class _Value(_Outcome):
    def unwrap(self):
        try:
            return self.val
        finally:
            del self.val


class _Error(_Outcome):
    def unwrap(self):
        try:
            raise self.val
        finally:
            del self.val


class ValueEvent:
    """
    A waitable value useful for inter-task synchronization,
    inspired by :class:`threading.Event`.

    An event object manages an internal value, which is initially
    unset, and a task can wait for it to become True.

    Note that the value can only be read once.
    """

    def __init__(self):
        self.event = Event()
        self.value = None

    def set(self, value):
        """
        Set the result to return this value, and wake any waiting task.
        """
        self.value = _Value(value)
        self.event.set()

    def set_error(self, exc):
        """
        Set the result to raise this exception, and wake any waiting task.
        """
        self.value = _Error(exc)
        self.event.set()

    def is_set(self):
        """
        Check whether the event has occurred.
        """
        return self.value is not None

    def cancel(self):
        """
        Send a cancelation to the recipient.
        """
        self.set_error(CancelledError())

    async def get(self):
        """
        Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        return self.value.unwrap()


def ACM(obj):
    """A bare-bones async context manager.

    Usage::

        class Foo():
            async def __aenter__(self):
                AC = ACM(obj)
                ctx1 = await AC(obj1)
                ...
            async def __aexit__(self, *exc):
                return await AC_exit(self, *exc)

    Calls to `ACM` and `AC_exit` can be nested. They **must** balance.
    """

    if hasattr(obj, "_AC_"):
        obj._AC_.append(None)
    else:
        obj._AC_ = []

    def _ACc(ctx):
        return AC_use(obj, ctx)

    return _ACc


async def AC_use(obj, ctx):
    """
    Attach a callback / (async) context manager to this object's AC.
    """
    if hasattr(ctx, "__aenter__"):
        cm = await ctx.__aenter__()
    elif hasattr(ctx, "__enter__"):
        cm = ctx.__enter__()
    else:
        cm = None
    obj._AC_.append(ctx)
    return cm


async def AC_exit(obj, *exc):
    """End the latest async context manager opened by `ACM`."""
    received_exc = exc[0] is not None

    # Callbacks are invoked in LIFO order to match the behaviour of
    # nested context managers.
    if not exc:
        exc = (None, None, None)

    suppressed_exc = False
    pending_raise = False
    while obj._AC_:
        cb = obj._AC_.pop()
        if cb is None:
            break
        try:
            if hasattr(cb, "__aexit__"):
                res = await cb.__aexit__(*exc)
            elif hasattr(cb, "__exit__"):
                res = cb.__exit__(*exc)
            else:
                res = cb()
                if hasattr(res, "throw"):  # async cb
                    res = await res

            if res:  # suppress error
                suppressed_exc = True
                pending_raise = False
                exc = (None, None, None)
        except BaseException as ex:
            exc = (type(ex), ex, getattr(ex, "__traceback__", None))
            pending_raise = True
    if pending_raise:
        raise exc[1]
    return received_exc and suppressed_exc


class _Shield:
    def __enter__(self):
        pass

    def __exit__(self, *tb):
        pass


_shield = _Shield()


def shield():
    "no-op context manager, supposed to shield a (sub)task from cancels"
    return _shield


# "await" for stream read/write-ability

from asyncio import core  # noqa:E402


def _rdq(s):  # async
    yield core._io_queue.queue_read(s)  # noqa:SLF001


def _wrq(s):  # async
    yield core._io_queue.queue_write(s)  # noqa:SLF001


def is_async(obj):  # noqa: D103
    if iscoroutine(obj) or hasattr(obj, "__iter__"):
        return True
    return False
