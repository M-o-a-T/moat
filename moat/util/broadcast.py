"""
Broadcasting support
"""

from __future__ import annotations

from weakref import WeakSet

from attrs import define, field

from .compat import EndOfStream, WouldBlock
from . import NotGiven
from .queue import Queue

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Literal, Self

# TODO build something nicer
try:
    import logging
except ImportError:
    logger = None
else:
    logger = logging.getLogger(__name__)

__all__ = [
    "Broadcaster",
    "BroadcastReader",
    "LostData",
]


class LostData(Exception):
    """
    Indicator of data loss.

    Attribute ``n`` contains the number of dropped messages.
    """

    def __init__(self, n):
        self.n = n


@define
class BroadcastReader: ## TYPE [TData]:
    """
    The read side of a broadcaster.

    Simply iterate over it.

    Warning: The iterator may raise ``LostData`` exceptions.
    These contain the number of messages that have been dropped
    due to the reader being too slow.

    Readers may be called to inject values.
    """

    parent: Broadcaster = field()
    length: int = field(default=1)
    value: TData | Literal[NotGiven] = field(default=NotGiven, init=False)

    loss: int = field(init=False, default=0)
    _q: Queue = field(init=False)

    def __attrs_post_init__(self) -> None:
        if self.length <= 0:
            raise RuntimeError("Length must be at least one")
        self._q = Queue(self.length)

    def __hash__(self):
        return id(self)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TData:
        if self.loss > 0:
            n, self.loss = self.loss, 0
            raise LostData(n)

        try:
            return await self._q.get()
        except (AttributeError, EndOfStream, EOFError):
            raise StopAsyncIteration from None

    def flush(self) -> None:
        """
        Clean the queue.

        Useful for re-sync after you get a `LostData` error.
        """
        try:
            while True:
                self._q.get_nowait()
        except WouldBlock:
            return

    def __call__(self, value: TData) -> None:
        """enqueue a value, to this reader only"""
        try:
            self._q.put_nowait(value)
        except WouldBlock:
            x = self._q.get_nowait()
            if logger is not None:
                logger.debug("Dropped: %r", x)
            self._q.put_nowait(value)
            self.loss += 1

    def _close(self) -> None:
        self._q.close_writer()

    def close(self) -> None:
        "close this reader, detaching it from its parent"
        self._close()
        self.parent._closed_reader(self)  # noqa:SLF001 pylint: disable=protected-access

    async def aclose(self) -> None:
        "close this reader, detaching it from its parent"
        self.close()


@define
class Broadcaster: ## TYPE [TData]:
    """
    A simple broadcaster. Messages will be sent to all readers.

    @length is each reader's default queue length.

    If @send_last is set, a new reader immediately gets the last-sent
    value. Otherwise it waits for new data.

    If a queue is full, the oldest message will be discarded. Readers will
    then get a LostData exception that contains the number of dropped
    messages.

    To write, open a context manager (sync or async) and call with a value.

    To read, async-iterate::

        async def rdr(bcr: BroadcastReader|Broadcaster):
            async for msg in bcr:
                print(msg)

        async with anyio.create_task_group() as tg, Broadcaster() as bc:
            tg.start_soon(rdr, aiter(bc))
            for x in range(5):
                bc(x)
                await anyio.sleep(0.01)
            bc(42)

    To safely re-sync, do something like this::

        bcr.flush()
        x = fetch_consistent_state()  # this really should be sync
        bcr(x)  # if this fails, you've got a problem
        while True:
            y = await anext(bcr)
            if x is y:
                break

    """

    length: int = field(default=1)
    send_last: bool = field(default=False)

    _rdr: WeakSet[BroadcastReader] | None = field(init=False, default=None, repr=False)
    value: TData | Literal[NotGiven] = field(init=False, default=NotGiven)

    def open(self) -> Self:
        """Open the broadcaster.

        Consider using a context instead of this method.
        """
        if self._rdr is not None:
            raise RuntimeError("already entered/opened")
        self._rdr = WeakSet()
        return self

    def __enter__(self) -> Self:
        return self.open()

    async def __aenter__(self) -> Self:
        return self.open()

    def __exit__(self, *tb) -> None:
        self.close()

    async def __aexit__(self, *tb) -> None:
        self.close()

    def _closed_reader(self, reader) -> None:
        assert self._rdr is not None

        self._rdr.remove(reader)

    def __aiter__(self) -> BroadcastReader[TData]:
        """Create a reader with the predefined queue length"""
        assert self._rdr is not None

        r: BroadcastReader[TData] = BroadcastReader(self, self.length)
        self._rdr.add(r)
        if self.send_last and self.value is not NotGiven:
            r(cast("TData", self.value))
        return aiter(r)

    def reader(self, length: int, send_last:bool|None=None) -> BroadcastReader[TData]:
        """Create a reader with an explicit queue length"""
        assert self._rdr is not None

        if send_last is None:
            send_last = self.send_last
        r: BroadcastReader[TData] = BroadcastReader(self, length)
        self._rdr.add(r)
        if send_last and self.value is not NotGiven:
            if not length:
                raise ValueError("This would deadlock. Use length>0.")
            r(cast("TData", self.value))
        return aiter(r)

    def __call__(self, value: TData) -> None:
        """Enqueue a value to all readers"""
        assert self._rdr is not None

        self.value = value
        for r in self._rdr:
            r(value)

    async def read(self) -> TData:
        "gets the last value (waits until there is one)"
        if self.value is NotGiven:
            return await anext(aiter(self))
        return self.value

    def close(self):
        "Close the broadcaster. No more writing."
        if self._rdr is not None:
            for r in self._rdr:
                r._close()  # noqa:SLF001 pylint: disable=protected-access
            self._rdr = None
