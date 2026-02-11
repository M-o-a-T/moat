"""Signal handling utilities."""

from __future__ import annotations

import anyio
import signal
from contextlib import asynccontextmanager

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskGroup

    from collections.abc import AsyncIterator


class SigCancel(anyio.AsyncContextManagerMixin):
    """
    This is a cancellation-by-signal helper.

    Usage::

        async with SigCancel():
            ... do whatever

    Args:
        exc:
            Exception to raise on signal. The exception will *not* be wrapped in an
            `ExceptionGroup`. If unset, terminate silently.
    """

    def __init__(self, exc: type[BaseException] | None = None) -> None:
        self.exc: type[BaseException] | None = exc
        self.tg: TaskGroup

    async def _sig_handler(self) -> None:
        with anyio.open_signal_receiver(
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGHUP,
        ) as signals:
            async for _ in signals:
                self.tg.cancel_scope.cancel()
                break  # default handlers on next

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncIterator[None]:
        async with anyio.create_task_group() as self.tg:
            self.tg.start_soon(self._sig_handler, name="sig")
            yield None
            if self.tg.cancel_scope.cancel_called and self.exc is not None:
                raise self.exc
            self.tg.cancel_scope.cancel()
