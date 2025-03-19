"""
This module affords a helper class to make "async with OBJECT" map
seamlessly to an async context management method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from attrs import define
import anyio

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
    from types import TracebackType


__all__ = ["CtxObj", "timed_ctx"]


class CtxObj(ABC):  ## [T_Ctx](ABC):
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

    @overload
    def _ctx(self) -> AsyncIterator[T_Ctx]:
        ...

    @abstractmethod
    def _ctx(self) -> AbstractAsyncContextManager[T_Ctx]:
        ...

    async def __aenter__(self) -> T_Ctx:
        if self.__ctx is not None:
            raise RuntimeError("Nested contexts")
        ctx = self._ctx()  # pylint: disable=E1101,W0201
        if not isinstance(ctx, AbstractAsyncContextManager):
            # No @asynccontextmanager wrapper on `_ctx`.
            # Kill the "coroutine not awaited" warning.
            try:
                await ctx.athrow(StopAsyncIteration)
            except StopAsyncIteration:
                pass
            else:
                raise RuntimeError(f"Failure to stop {ctx!r}")

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
