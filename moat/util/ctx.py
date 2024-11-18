"""
This module affords a helper class to make "async with OBJECT" map
seamlessly to an async context management method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType


class CtxObj[T_Ctx](ABC):
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
    def _ctx(self) -> AbstractAsyncContextManager[T_Ctx]: ...

    async def __aenter__(self) -> T_Ctx:
        if self.__ctx is not None:
            raise RuntimeError("Nested contexts")
        self.__ctx = ctx = self._ctx()  # pylint: disable=E1101,W0201
        return await ctx.__aenter__()

    def __aexit__(
        self, *tb: *tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
    ) -> Awaitable[bool | None]:
        try:
            assert self.__ctx is not None
            return self.__ctx.__aexit__(*tb)
        finally:
            self.__ctx = None
