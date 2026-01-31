"""
Broadcasting support
"""

from __future__ import annotations

from moat.util import NotGiven, Queue
from moat.lib.micro import EndOfStream, WouldBlock

from typing import TYPE_CHECKING, Generic, TypeVar, cast

if TYPE_CHECKING:
    from typing import Self

try:
    from weakref import WeakSet
except ImportError:
    WeakSet = set  # type:ignore[assignment]

TData = TypeVar("TData")


# TODO build something nicer
try:
    import logging
except ImportError:
    logger = None
else:
    logger = logging.getLogger(__name__)

__all__ = [
    "BroadcastReader",
    "Broadcaster",
    "LostData",
]


class LostData(Exception):
    """
    Indicator of data loss.

    Attribute ``n`` contains the number of dropped messages.
    """

    def __init__(self, n: int) -> None:
        self.n = n


class BroadcastReader(Generic[TData]):
    """
    The read side of a broadcaster.

    Simply iterate over it.

    Warning: The iterator may raise ``LostData`` exceptions.
    These contain the number of messages that have been dropped
    due to the reader being too slow.

    Call this object to inject a value.
    """

    def __init__(
        self,
        parent: Broadcaster,
        length: int = 1,
        skip: bool = False,
    ) -> None:
        self.parent = parent
        self.length = length
        self.skip = skip
        self.value: TData = NotGiven
        self.loss: int = 0

        if self.length <= 0:
            raise RuntimeError("Length must be at least one")
        self._q: Queue = Queue(self.length)

    def __hash__(self) -> int:
        return id(self)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TData:
        if not self.skip and self.loss > 0:
            n, self.loss = self.loss, 0
            raise LostData(n)

        try:
            return await self._q.get()
        except (AttributeError, EndOfStream, EOFError):
            raise StopAsyncIteration from None

    def __enter__(self):
        return self

    async def __aenter__(self):
        return self

    def __exit__(self, *tb) -> None:
        self.close()

    async def __aexit__(self, *tb) -> None:
        self.close()

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


class Broadcaster(Generic[TData]):
    """
    A simple broadcaster. Messages will be sent to all readers.

    Args:
        length:
            readers' default queue length.
        send_last:
            if set, a new reader immediately gets the last-sent value,
            if any. Otherwise it strictly waits for new data.

    If a queue is full, the oldest message will be discarded. Readers will
    then get a LostData exception that contains the number of dropped
    messages.

    Writing requires a context manager (sync or async).
    Then simply call with a value.

    ::

        async with anyio.create_task_group() as tg, Broadcaster() as bc:
            tg.start_soon(rdr, aiter(bc))
            for x in range(5):
                bc(x)
                await anyio.sleep(0.01)
            bc(42)

    To read, async-iterate::

        async def rdr(bcr: Broadcaster):
            async with bcr.reader() as mq:
                async for msg in mq:
                    print(msg)

    alternately::

        async def rdr(bcr: BroadcastReader|Broadcaster):
            async with aclosing(aiter(bcr)) as mq:
                async for msg in mq:
                    print(msg)

    Do **not** skip the *aclosing*, esp. on MicroPython.

    To safely re-sync, do something like this::

        bcr.flush()
        x = fetch_consistent_state()  # this really should be sync
        bcr(x)  # if this fails, you've got a problem
        while True:
            y = await anext(bcr)
            if x is y:
                break

    """

    def __init__(
        self,
        length: int = 1,
        send_last: bool = False,
    ) -> None:
        self.length = length
        self.send_last = send_last
        self._rdr: WeakSet[BroadcastReader] | None = None
        self.value: TData = NotGiven

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

    def _closed_reader(self, reader: BroadcastReader[TData]) -> None:
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

    def reader(
        self, length: int, send_last: bool | None = None, skip: bool = False
    ) -> BroadcastReader[TData]:
        """Create a reader with an explicit queue length.

        Args:
            length: Queue size.
            skip: if `True`, ignore overflows.
        """
        assert self._rdr is not None

        if send_last is None:
            send_last = self.send_last
        r: BroadcastReader[TData] = BroadcastReader(self, length, skip)
        self._rdr.add(r)
        if send_last and self.value is not NotGiven:
            if not length:
                raise ValueError("This would deadlock. Use length>0.")
            r(cast("TData", self.value))
        return r

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

    def close(self) -> None:
        "Close the broadcaster. No more writing."
        if self._rdr is not None:
            for r in self._rdr:
                r._close()  # noqa:SLF001 pylint: disable=protected-access
            self._rdr = None
