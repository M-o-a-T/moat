"""
This module affords a helper class to make "async with OBJECT" map
seamlessly to an async context management method.
"""

from __future__ import annotations

import anyio
from abc import ABC, abstractmethod
from concurrent.futures import CancelledError  # intentionally not asynio/anyio.Cancelled
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from attrs import define, field

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from contextvars import ContextVar, Token
    from types import TracebackType

    from collections.abc import AsyncIterator, Awaitable
    from typing import Any, Literal


__all__ = ["CtxObj", "ctx_as", "timed_ctx"]

T_Ctx = TypeVar("T_Ctx")


class CtxObj(ABC):
    """
    Teach a class instance to act as an async context manager, by
    forwarding ``_aenter__````_aexit__`` to a `_ctx` method
    (which must be an `AsyncContextManager`).

    Usage::
        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self # or whatever

        async with Foo() as whatever:
            pass
    """

    __ctx: AbstractAsyncContextManager | None = None

    @abstractmethod
    def _ctx(self) -> AsyncIterator[T_Ctx]: ...

    async def __aenter__(self) -> T_Ctx:
        if self.__ctx is not None:
            raise RuntimeError("Nested contexts")
        ctx = self._ctx()
        if not hasattr(ctx, "__aenter__"):
            # DEPRECATED
            # legacy code for `_ctx` without @asynccm
            ctx = asynccontextmanager(self._ctx)()
        self.__ctx = ctx
        return await ctx.__aenter__()

    def __aexit__(
        self,
        *tb: *tuple[type[BaseException] | None, BaseException | None, TracebackType | None],
    ) -> Awaitable[bool | None]:
        try:
            assert self.__ctx is not None
            return self.__ctx.__aexit__(*tb)
        finally:
            self.__ctx = None


@define
class timed_ctx(CtxObj):
    """
    A wrapper for an async context manager that times out if entering it
    takes too long.

    Everything else is unaffected.
    """

    timeout: int | float
    mgr: AbstractAsyncContextManager

    async def _timer(self, *, task_status):
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            await anyio.sleep(self.timeout)
            raise TimeoutError(self.timeout)

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as tg:
            sc = await tg.start(self._timer)
            async with self.mgr as mgr:
                sc.cancel()
                yield mgr


class ContextMgr[T_CtxType]:
    """
    This class manages a context for the caller.

    Useful when entering/leaving the context is triggered from state
    machine callbacks or similar event handlers.
    """

    @asynccontextmanager
    async def context(self, *args, **kwargs):
        raise NotImplementedError("Override me!")

    exc: Exception | None = None
    ctx: T_Ctx | Literal[False] | None = None
    stopper: anyio.Event = None
    stopped: anyio.Event = None

    def __init__(self):
        self.qw, self.qr = anyio.create_memory_object_stream(0)

    async def task(self):
        """
        The task that encapsulates the context handler.

        Start this once, when setting up your state machine.
        """
        async for evt, args, kwargs in self.qr:
            self.stopper = anyio.Event()
            self.stopped = anyio.Event()
            self.exc = None
            try:
                async with self.context(*args, **kwargs) as self.ctx:
                    evt.set()
                    evt = self.stopped  # noqa:PLW2901
                    await self.stopper.wait()
                    if self.exc is not None:
                        raise self.exc
            except (CancelledError, Exception) as exc:
                self.exc = exc
            except BaseException:
                self.exc = CancelledError()
                raise
            finally:
                evt.set()
                self.stopped.set()
                self.ctx = None

    def close(self):
        """
        Ends the context task.
        """
        self.qw.close()
        if self.stopper is not None and not self.stopper.is_set():
            self.exc = CancelledError()
            self.stopper.set()

    async def start(self, *args, **kwargs):
        """
        Creates and starts your context, passing the given arguments.

        Raises `RuntimeError` if the context is already open
        (or starting in a different task).
        """
        if self.ctx is not None:
            raise RuntimeError("Context already entered")
        self.ctx = False
        evt = anyio.Event()
        await self.qw.send((evt, args, kwargs))
        try:
            await evt.wait()
        except BaseException:
            if self.exc is None:
                self.exc = CancelledError()
            self.stopper.set()
            with anyio.move_on_after(0.5, shield=True):
                await self.stopped.wait()
            raise

        if self.exc is not None:
            exc, self.exc = self.exc, None
            raise exc
        return self.ctx

    async def stop(self, exc: Exception | None = None):
        """
        Stops your context.

        If @exc is set, it is passed into / raised in the context.

        This method waits until the context ends.
        """
        if self.ctx is None:
            raise RuntimeError("Context not entered")
        if exc is not None:
            self.exc = exc
        self.stopper.set()
        await self.stopped.wait()
        if self.exc is None:
            return
        if self.exc is exc:
            self.exc = None
        else:
            exc, self.exc = self.exc, None
            raise exc


@define
class ctx_as:
    """
    Temporary setting of a context variable. This avoids the
    multi-line try/token=set()/finally/reset(token) dance.

    Usage::

        x = ContextVar("x", default=False)
        [async] with ctx_as(x,True):
            assert x.get() is True
        assert x.get() is False  # or whatever
    """

    var: ContextVar = field()
    value: Any = field()
    token: Token = field(default=None, init=False)

    def __enter__(self) -> None:
        if self.token is not None:
            raise ValueError("nested 'ctx_as' contexts ??")
        self.token = self.var.set(self.value)
        del self.value

    def __exit__(self, *tb) -> None:
        self.var.reset(self.token)
        del self.token

    async def __aenter__(self) -> None:
        self.__enter__()

    async def __aexit__(self, *tb) -> None:
        self.__exit__(*tb)
