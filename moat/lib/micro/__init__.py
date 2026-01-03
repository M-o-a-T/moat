"""
Compatibility wrappers that allows MoaT code to run on CPython/anyio as
well as MicroPython/uasyncio.

Well, for the most part.
"""

# ruff:noqa:F401

from __future__ import annotations

import anyio as _anyio
import logging
import os
import sys
import time as _time
import traceback as _traceback
from codecs import utf_8_decode
from concurrent.futures import CancelledError as CancelledError
from contextlib import AsyncExitStack
from contextlib import aclosing as aclosing
from functools import partial
from inspect import currentframe, iscoroutine, iscoroutinefunction

from moat.util import Queue as _Queue
from moat.util import QueueEmpty, QueueFull, merge

from collections.abc import (  # noqa: TC002
    AsyncIterator,
    Iterable,
    Mapping,
    MutableMapping,
    MutableSequence,
)
from typing import TYPE_CHECKING, Any, TypeVar, overload

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager, AbstractContextManager

    from collections.abc import Awaitable, Callable
    from typing import NoReturn, Self

logger = logging.getLogger(__name__)

__all__ = [
    "ACM",
    "AC_exit",
    "AC_use",
    "CancelScope",
    "Event",
    "L",
    "Lock",
    "Queue",
    "TaskGroup",
    "WouldBlock",
    "aclosing",
    "at",
    "breakpoint",
    "byte2utf8",
    "const",
    "every",
    "every_ms",
    "idle",
    "is_async",
    "log",
    "log_exc",
    "print_exc",
    "run",
    "run_server",
    "shield",
    "sleep_ms",
    "ticks_add",
    "ticks_diff",
    "ticks_ms",
    "to_thread",
    "wait_for",
    "wait_for_ms",
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
ExceptionGroup = ExceptionGroup  # noqa: A001, PLW0127
BaseExceptionGroup = BaseExceptionGroup  # noqa: A001, PLW0127
breakpoint = breakpoint  # noqa: A001, PLW0127


def const[T](_x: T) -> T:
    "µPython compatibility"
    return _x


L = True

Pin_IN = 0
Pin_OUT = 1


def byte2utf8(buf: bytes | bytearray | memoryview) -> str:  # noqa: D103
    res, n = utf_8_decode(buf)
    if n != len(buf):
        raise ValueError("incomplete utf8")
    return res


class CancelScope:
    """
    An async-await-able CancelScope wrapper
    """

    def __init__(self) -> None:
        self.sc = _anyio.CancelScope()

    async def __aenter__(self) -> Self:
        self.sc.__enter__()
        return self

    async def __aexit__(self, *tb) -> bool | None:
        return self.sc.__exit__(*tb)

    def cancel(self) -> None:
        "Cancel the scope"
        self.sc.cancel()

    @property
    def cancelled(self) -> bool:
        "Was 'cancel' called on this scope?"
        return self.sc.cancel_called


def log(s, *x, err=None, nback=1, write: bool = True) -> None:
    "Basic logger.debug/error call (depends on @err)"
    write  # noqa:B018
    caller = currentframe()
    if caller is None:
        caller_name = __name__
    else:
        for _ in range(nback):
            if caller.f_back is None:
                break
            caller = caller.f_back
        caller_name = caller.f_globals["__name__"]
    log_ = logging.getLogger(caller_name)
    (log_.debug if err is None else log_.error)(
        s, *x, exc_info=err if isinstance(err, BaseException) else None, stacklevel=1 + nback
    )
    if err and int(os.getenv("LOG_BRK", "0")):
        breakpoint()


def log_exc(e, s, *a) -> None:  # noqa:D103
    log(s, *a, err=e)


def at(*a, **kw) -> None:  # noqa: D103
    logger.debug("%r %r", a, kw)


def print_exc(exc, file=None) -> None:
    "print a stack trace to stderr"
    _traceback.print_exception(type(exc), exc, exc.__traceback__, file=file)


def ticks_ms() -> int:
    "return a monotonic timer, in milliseconds"
    return _time.monotonic_ns() // 1000000


async def sleep_ms(ms: float) -> None:
    "sleep for @ms milliseconds"
    await sleep(ms / 1000)


async def wait_for[R](timeout: float, p: Callable[..., Awaitable[R]], *a, **k) -> R:
    "timeout if the call to p(*a,**k) takes longer than @timeout seconds"
    with _anyio.fail_after(timeout):
        return await p(*a, **k)


async def wait_for_ms[R](timeout: float, p: Callable[..., Awaitable[R]], *a, **k) -> R:
    "timeout if the call to p(*a,**k) takes longer than @timeout milliseconds"
    with _anyio.fail_after(timeout / 1000):
        return await p(*a, **k)


async def every_ms[R](
    t: float, p: Callable[..., Awaitable[R]] | None = None, *a, **k
) -> AsyncIterator[R | None]:
    "every t milliseconds, call p(*a,**k)"
    tt = ticks_add(ticks_ms(), int(t))
    while True:
        try:
            yield None if p is None else await p(*a, **k)
        except StopAsyncIteration:
            return
        tn = ticks_ms()
        td = ticks_diff(tt, tn)
        if td > 0:
            await sleep_ms(td)
            tt += t
        else:
            # owch, delay too long
            tt = ticks_add(tn, int(t))


def every(t: float, *a, **k) -> AsyncIterator[Any]:
    "every t seconds, call p(*a,**k)"
    return every_ms(t * 1000, *a, **k)


async def idle() -> None:
    "sleep forever"
    await _anyio.sleep_forever()


def ticks_add(a: int, b: int) -> int:
    "returns a+b"
    return a + b


def ticks_diff(a: int, b: int) -> int:
    "returns a-b"
    return a - b


def run[R](p: Callable[..., Awaitable[R]], *a, **k) -> R:
    "wrapper for anyio.run"
    return _anyio.run(p, a, k)


_tg = None
_tgt = None


def TaskGroup() -> Any:  # Returns augmented TaskGroup instance
    "A TaskGroup subclass (generator) that supports `spawn` and `cancel`"

    global _tg, _tgt
    if "pytest" in sys.modules or _tgt is None:
        tgt = type(_anyio.create_task_group())
    else:
        tgt = _tgt
    if tgt is not _tgt:
        _tgt = tgt

        class TaskGroup_(_tgt):  # type: ignore[misc]
            """An augmented taskgroup"""

            async def spawn(
                self, p: Callable[..., Awaitable[Any]], *a, _name: str | None = None, **k
            ) -> _anyio.CancelScope:
                """
                Like start(), but returns something you can cancel
                """
                # logger.info("Launch %s %s %s %s",_name, p,a,k)
                if _name is None:
                    _name = str((p, a, k))

                async def catch(p, a, k, *, task_status) -> None:
                    with _anyio.CancelScope() as s:
                        task_status.started(s)
                        await p(*a, **k)

                return await super().start(catch, p, a, k, name=_name)

            def cancel(self) -> None:
                "cancel all tasks in this taskgroup"
                self.cancel_scope.cancel()

        _tg = TaskGroup_
    return _tg()


async def run_server(
    cb: Callable,
    host: str,
    port: int,
    backlog: int = 5,
    taskgroup: Any = None,
    reuse_port: bool = True,
    evt: _anyio.Event | None = None,
) -> None:
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


def shield() -> _anyio.CancelScope:
    """A wrapper shielding the contents from external cancellation.

    Equivalent to ``CancelScope(shield=True)``.
    """
    return _anyio.CancelScope(shield=True)


class Queue[T](_Queue):
    """
    compatibility mode: raise `EOFError` and `QueueEmpty`/`QueueFull`
    instead of `anyio.EndOfStream` and `anyio.WouldBlock`
    """

    async def get(self) -> T:  # noqa:D102
        try:
            return await super().get()
        except _anyio.EndOfStream:
            raise EOFError from None

    def get_nowait(self) -> T:  # noqa:D102
        try:
            return super().get_nowait()
        except _anyio.EndOfStream:
            raise EOFError from None
        except _anyio.WouldBlock:
            raise QueueEmpty from None

    def put_nowait(self, x: T) -> None:  # noqa:D102
        try:
            super().put_nowait(x)
        except _anyio.WouldBlock:
            raise QueueFull from None


# async context stack


def ACM(obj: Any) -> Callable[[Any], Awaitable[Any]]:
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

                except BaseException as exc:
                    await AC_exit(self, type(exc), exc, None)
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

    def _ACc(ctx: Any) -> Awaitable[Any]:
        return AC_use(obj, ctx)

    return _ACc


@overload
async def AC_use[T](obj: Any, ctx: AbstractAsyncContextManager[T]) -> T: ...


@overload
async def AC_use[T](obj: Any, ctx: AbstractContextManager[T]) -> T: ...


@overload
async def AC_use(obj: Any, ctx: Callable[[], Awaitable[Any]]) -> None: ...


@overload
async def AC_use(obj: Any, ctx: Callable[[], Any]) -> None: ...


async def AC_use(obj: Any, ctx: Any) -> Any:
    """
    Add an async context to this object's AsyncExitStack.

    If the object is a context manager (async or sync), this opens the
    context and return its value.

    Otherwise it's a callable and will run on exit.
    """
    acm: AsyncExitStack = obj._AC_[-1]
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


async def AC_exit(obj: Any, *exc) -> bool | None:
    """End the latest AsyncExitStack opened by `ACM`."""
    if not exc:
        exc = (None, None, None)
    return await obj._AC_.pop().__aexit__(*exc)


def is_async(obj: Any) -> bool:
    """test if the argument is an awaitable"""
    if hasattr(obj, "__await__"):
        return True
    return False


async def to_thread[R](p: Callable[..., R], *a, **k) -> R:
    """run this function in a thread"""
    if k:
        return await _anyio.to_thread.run_sync(partial(p, *a, **k), abandon_on_cancel=True)  # type: ignore[attr-defined]
    return await _anyio.to_thread.run_sync(p, *a, abandon_on_cancel=True)  # type: ignore[attr-defined]
