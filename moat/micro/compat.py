"""
Compatibility wrappers that allows MoaT code to run on CPython/anyio as
well as MicroPython/asyncio.

Well, for the most part.
"""

from __future__ import annotations

import anyio as _anyio
from contextlib import AsyncExitStack
from inspect import iscoroutinefunction

from moat.util.compat import (
    Queue,  # noqa:F401
    TaskGroup,  # noqa:F401
    every,  # noqa:F401
    every_ms,  # noqa:F401
    idle,  # noqa:F401
    log,  # noqa:F401
    print_exc,  # noqa:F401
    run,  # noqa:F401
    run_server,  # noqa:F401
    shield,  # noqa:F401
    sleep_ms,  # noqa:F401
    ticks_add,  # noqa:F401
    ticks_diff,  # noqa:F401
    ticks_ms,  # noqa:F401
    wait_for,  # noqa:F401
    wait_for_ms,  # noqa:F401
)


def const(_x):
    "compatibility with µPy"
    return _x


L = const(True)

ExceptionGroup = ExceptionGroup  # noqa: PLW0127 pylint:disable=redefined-builtin,self-assigning-variable
BaseExceptionGroup = BaseExceptionGroup  # noqa: PLW0127 pylint:disable=redefined-builtin,self-assigning-variable

Pin_IN = 0
Pin_OUT = 1

Event = _anyio.Event
Lock = _anyio.Lock
WouldBlock = _anyio.WouldBlock
sleep = _anyio.sleep
EndOfStream = _anyio.EndOfStream
BrokenResourceError = _anyio.BrokenResourceError
TimeoutError = TimeoutError  # noqa:A001,PLW0127 pylint:disable=redefined-builtin,self-assigning-variable


# async context stack


def ACM(obj):
    """A bare-bones async context manager.

    Usage::

        class Foo():
            async def __aenter__(self):
                AC = ACM(obj)
                try:
                    ctx1 = await AC(obj1)
                    ctx2 = await AC_use(self, obj2)  # same thing
                except BaseException:
                    await AC_exit(self, *exc)
                    raise
                ...
            async def __aexit__(self, *exc):
                return await AC_exit(self, *exc)

    Calls to `ACM` and `AC_exit` can be nested. They **must** balance;
    hence the above error handling dance.
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
    else:
        acm.callback(ctx)
    return None


async def AC_exit(obj, *exc):
    """End the latest AsyncExitStack opened by `ACM`."""
    if not exc:
        exc = (None, None, None)
    return await obj._AC_.pop().__aexit__(*exc)
