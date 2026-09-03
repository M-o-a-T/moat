"""
Helpers for the MoaT bus server.

This module contains dispatcher base classes used by the bus server
subsystem, plus minifloat conversion helpers used for message timeouts.
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager, contextmanager

from moat.util import CtxObj

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.bus.message import BusMessage

    from collections.abc import AsyncIterator, Awaitable, Callable
    from typing import Any


# minifloat granularity
MINI_F = 1 / 4


class Dispatcher:
    """
    Adds a registry and a dispatcher to an object.
    """

    def __init__(self) -> None:
        self._dispatch: dict[Any, Callable[[BusMessage], Awaitable[None]]] = {}
        super().__init__()

    async def dispatch(self, msg: BusMessage) -> None:
        """Dispatch a message."""
        k = self.get_code(msg)
        try:
            d = self._dispatch[k]
        except KeyError:
            return
        await d(msg)

    def get_code(self, msg: BusMessage) -> Any:
        """Get dispatch code for this message."""
        raise NotImplementedError("I have no idea how to dispatch anything")

    def register(self, code: Any, dispatcher: Callable[[BusMessage], Awaitable[None]]) -> None:
        """Register a control dispatcher."""
        if code in self._dispatch:
            raise KeyError(code)
        self._dispatch[code] = dispatcher

    def deregister(self, code: Any) -> None:
        """Remove a control dispatcher registration."""
        del self._dispatch[code]

    @contextmanager
    def with_code(self, code: Any):
        """
        Returns an async iterator for messages with this code,
        defined as whatever ``get_code`` returns.

        This is a (non-async) context manager.
        """
        q_w, q_r = anyio.create_memory_object_stream(100)
        self.register(code, q_w.send)
        try:
            yield q_r
        finally:
            self.deregister(code)


class _SubServer:
    """
    A subordinate server.
    """

    CODE: int | None = None

    def __init__(self, server: Any, code: int | None = None) -> None:
        self._server = server
        self._back = server._back  # noqa:SLF001

        self._code = code if code is not None else self.CODE
        if self._code is None:
            raise NotImplementedError("You need to override the CODE attribute")

        self.my_id = server.my_id

        self.send = server.send
        self.reply = server.reply
        self.send_msg = server.send_msg
        self.objs = server.objs

        super().__init__()

    async def send_msg(self, msg: BusMessage) -> None:
        await self._back.send(msg)


class SubDispatcher(_SubServer, CtxObj, Dispatcher):
    """
    Implements a registered dispatcher.

    Get code-``code`` messages from the server.
    """

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[SubDispatcher]:
        async with anyio.create_task_group() as n:
            await n.start(self._dispatch_loop)
            yield self

    async def _dispatch_loop(self, *, task_status: TaskStatus[None]) -> None:
        with self._server.with_code(self.CODE) as q:
            task_status.started()
            async for msg in q:
                await self.dispatch(msg)


# Backwards-compatible alias.
SubDispatch = SubDispatcher


class Processor(_SubServer, CtxObj):
    """
    Implements a dispatcher client.

    This is an async context manager.  It yields a channel which you must
    iterate to process the results, assuming your ``process`` method
    ``put``s any.
    """

    async def setup(self) -> None:
        """
        Additional initialization code, running when everything's active.
        """

    async def process(self, msg: BusMessage) -> None:
        """
        The actual message processing.
        """
        raise NotImplementedError(f"You forgot to override {self.__class__.__name__}.process")

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Any]:
        async with anyio.create_task_group() as n:
            self._nursery = n
            self._q_w, q_r = anyio.create_memory_object_stream(100)
            await self.setup()
            await n.start(self._process_loop)
            yield q_r

    async def _process_loop(self, *, task_status: TaskStatus[None]) -> None:
        with self._server.with_code(self.CODE) as q:
            task_status.started()
            async for msg in q:
                await self.process(msg)

    async def put(self, data: Any) -> None:
        """Send data to the output channel."""
        await self._q_w.send(data)

    async def spawn(self, p: Callable[..., Awaitable[Any]], *a: Any, **k: Any) -> Any:
        """
        Start a background task on this processor's nursery.

        Returns a cancel scope which you can use to kill the task.
        """

        async def job(
            p: Callable[..., Awaitable[Any]],
            a: tuple[Any, ...],
            k: dict[str, Any],
            *,
            task_status: TaskStatus[Any],
        ) -> None:
            with anyio.CancelScope() as sc:
                task_status.started(sc)
                await p(*a, **k)

        return await self._nursery.start(job, p, a, k)


def mini2byte(f: float) -> int:
    """
    Convert a float to a byte-sized minifloat.

    The byte-sized minifloat accepted by `mini2byte` and returned by
    `byte2mini` has no sign bit, 4 bit exponent, 4 bit mantissa, no NaN or
    overrun/infinity signalling (while 0xFF can be used as such if
    desired, that's not covered by this code).

    It can thus represent values from 0…8 in steps of 0.25, 0.5 to 16, 1 to 32,
    and so on, until steps of 4096 from 65536 to 126976 (0xFF) / 122880
    (0xFE), which is more than a day if you interpret minifloat values as
    seconds. It is thus suited well for timeouts with variable granularity
    that don't take up more space than absolutely necessary.
    """

    if f < 0:
        raise ValueError("Minifloats can't be negative")
    f = int(f / MINI_F + 0.5)
    if f <= 0x20:  # < 0x10: in theory, but the result is the same
        return f  # exponent=0 is denormalized
    exp = 1
    while f > 0x1F:  # scale the result
        f >>= 1
        exp += 1
    if exp > 0x0F:
        return 0xFF
    # The result is normalized: since the top bit is always 1 when the
    # exponent is non-zero, we can simply not transmit it and gain another
    # bit of "accuracy".
    return (exp << 4) | (f & 0x0F)


def byte2mini(m: int) -> float:
    """
    Convert a byte-sized minifloat back to a number.

    See `mini2byte` for details.
    """
    if m <= 32:  # or 16, doesn't matter
        return m * MINI_F

    exp = (m >> 4) - 1
    m = 0x10 + (m & 0xF)  # normalization
    return (1 << exp) * m * MINI_F


if __name__ == "__main__":
    for x in range(256):
        print(x, byte2mini(x), mini2byte(byte2mini(x)))
