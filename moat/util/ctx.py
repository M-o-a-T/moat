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

from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from anyio.abc import ObjectReceiveStream, ObjectSendStream, TaskStatus
    from contextvars import ContextVar, Token
    from types import TracebackType

    from collections.abc import AsyncIterator, Awaitable
    from typing import Any, Literal


__all__ = ["CtxObj", "ctx_as", "timed_ctx"]

T_Ctx = TypeVar("T_Ctx")
T_CtxType = TypeVar("T_CtxType")


class CtxObj(ABC, Generic[T_Ctx]):
    """
    Teach a class instance to act as an async context manager, by
    forwarding ``__aenter__`` and ``__aexit__`` to a ``_ctx`` method
    (which must be an ``AsyncContextManager``).

    Usage::

        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self  # or whatever

        async with Foo() as whatever:
            pass
    """

    __ctx: AbstractAsyncContextManager[T_Ctx, bool | None] | None = None

    @abstractmethod
    def _ctx(self) -> AsyncIterator[T_Ctx]: ...

    async def __aenter__(self) -> T_Ctx:
        if self.__ctx is not None:
            raise RuntimeError("Nested contexts")
        ctx_iter = self._ctx()
        if not hasattr(ctx_iter, "__aenter__"):
            # DEPRECATED
            # legacy code for `_ctx` without @asynccm
            ctx: AbstractAsyncContextManager[T_Ctx, bool | None] = asynccontextmanager(self._ctx)()  # type: ignore[assignment]  # legacy support
        else:
            ctx = ctx_iter  # AsyncIterator with __aenter__ is an ACM
        self.__ctx = ctx  # type: ignore[assignment]  # mixed types for legacy support
        return await ctx.__aenter__()  # type: ignore[union-attr]  # both branches have __aenter__

    def __aexit__(
        self,
        *tb: type[BaseException] | None | BaseException | TracebackType,
    ) -> Awaitable[bool | None]:
        try:
            assert self.__ctx is not None
            return self.__ctx.__aexit__(*tb)  # type: ignore[arg-type]  # variadic unpacking
        finally:
            self.__ctx = None


@define
class timed_ctx(CtxObj[T_Ctx]):
    """
    A wrapper for an async context manager that times out if entering it
    takes too long.

    Everything else is unaffected.
    """

    timeout: int | float
    mgr: AbstractAsyncContextManager[T_Ctx, bool | None]

    async def _timer(self, *, task_status: TaskStatus[anyio.CancelScope]) -> None:
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            await anyio.sleep(self.timeout)
            raise TimeoutError(self.timeout)

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[T_Ctx]:
        async with anyio.create_task_group() as tg:
            sc = await tg.start(self._timer)
            async with self.mgr as mgr:
                sc.cancel()
                yield mgr


class ContextMgr(Generic[T_CtxType]):
    """
    This class manages a context for the caller.

    Useful when entering/leaving the context is triggered from state
    machine callbacks or similar event handlers.
    """

    @asynccontextmanager
    async def context(self, *args: Any, **kwargs: Any) -> AsyncIterator[T_CtxType]:  # noqa: ARG002  # abstract method signature
        raise NotImplementedError("Override me!")
        yield  # NotImplementedError prevents reaching this

    exc: Exception | None = None
    ctx: T_CtxType | Literal[False] | None = None
    stopper: anyio.Event | None = None
    stopped: anyio.Event | None = None
    qw: ObjectSendStream[tuple[anyio.Event, tuple[Any, ...], dict[str, Any]]]
    qr: ObjectReceiveStream[tuple[anyio.Event, tuple[Any, ...], dict[str, Any]]]

    def __init__(self) -> None:
        self.qw, self.qr = anyio.create_memory_object_stream(0)

    async def task(self) -> None:
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
                    assert self.stopper is not None  # set above
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
                assert self.stopped is not None  # set above
                self.stopped.set()
                self.ctx = None

    def close(self) -> None:
        """
        Ends the context task.
        """
        self.qw.close()  # type: ignore[attr-defined]  # close() exists on MemoryObjectSendStream
        if self.stopper is not None and not self.stopper.is_set():
            self.exc = CancelledError()
            self.stopper.set()

    async def start(self, *args: Any, **kwargs: Any) -> T_CtxType:
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
            assert self.stopper is not None  # set in task()
            self.stopper.set()
            with anyio.move_on_after(0.5, shield=True):
                assert self.stopped is not None  # set in task()
                await self.stopped.wait()
            raise

        if self.exc is not None:
            exc, self.exc = self.exc, None
            raise exc
        assert self.ctx is not False  # set in task() after evt is set
        return self.ctx

    async def stop(self, exc: Exception | None = None) -> None:
        """
        Stops your context.

        If @exc is set, it is passed into / raised in the context.

        This method waits until the context ends.
        """
        if self.ctx is None:
            raise RuntimeError("Context not entered")
        if exc is not None:
            self.exc = exc
        assert self.stopper is not None  # set in task()
        self.stopper.set()
        assert self.stopped is not None  # set in task()
        await self.stopped.wait()
        if self.exc is None:
            return
        if self.exc is exc:
            self.exc = None
        else:
            exc_to_raise, self.exc = self.exc, None
            raise exc_to_raise


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

    var: ContextVar[Any] = field()
    value: Any = field()
    token: Token[Any] | None = field(default=None, init=False)

    def __enter__(self) -> Any:
        if self.token is not None:
            raise ValueError("nested 'ctx_as' contexts ??")
        self.token = self.var.set(self.value)
        try:
            return self.value
        finally:
            del self.value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.token is not None  # set in __enter__
        self.var.reset(self.token)
        del self.token

    async def __aenter__(self) -> Any:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)
