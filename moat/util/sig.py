# noqa:D100
from __future__ import annotations

import anyio
import signal
from contextlib import asynccontextmanager


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

    def __init__(self, exc: type[BaseException] | None = None):
        self.exc = exc

    async def _sig_handler(self):
        with anyio.open_signal_receiver(
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGHUP,
        ) as signals:
            async for _ in signals:
                self.tg.cancel_scope.cancel()
                break  # default handlers on next

    @asynccontextmanager
    async def __asynccontextmanager__(self):
        async with anyio.create_task_group() as self.tg:
            self.tg.start_soon(self._sig_handler, name="sig")
            yield None
        if self.tg.cancel_scope.cancel_called and self.exc is not None:
            raise self.exc
