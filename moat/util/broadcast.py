"""
Broadcasting support
"""

from __future__ import annotations

try:
    from weakref import WeakSet
except ImportError:
    WeakSet = set

from .compat import EndOfStream, WouldBlock
from .impl import NotGiven
from .queue import Queue

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


class BroadcastReader:
    """
    The read side of a broadcaster.

    Simply iterate over it.

    Warning: The iterator may raise ``LostData`` exceptions.
    These contain the number of messages that have been dropped
    due to the reader being too slow.

    Readers may be called to inject values.
    """

    value = NotGiven
    loss = 0

    def __init__(self, parent, length):
        self.parent = parent
        if length <= 0:
            raise RuntimeError("Length must be at least one")
        self._q = Queue(length)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.loss > 0:
            n, self.loss = self.loss, 0
            raise LostData(n)

        try:
            return await self._q.get()
        except (AttributeError, EndOfStream, EOFError):
            raise StopAsyncIteration from None

    def flush(self):
        """
        Clean the queue.

        Useful for re-sync after you get a `LostData` error.
        """
        try:
            while True:
                self._q.get_nowait()
        except WouldBlock:
            return

    def __call__(self, value):
        """enqueue a value, to this reader only"""
        try:
            self._q.put_nowait(value)
        except WouldBlock:
            x = self._q.get_nowait()
            if logger is not None:
                logger.debug("Dropped: %r", x)
            self._q.put_nowait(value)
            self.loss += 1

    def _close(self):
        self._q.close_writer()

    def close(self):
        "close this reader, detaching it from its parent"
        self._close()
        self.parent._closed_reader(self)  # noqa:SLF001 pylint: disable=protected-access

    async def aclose(self):
        "close this reader, detaching it from its parent"
        self.close()


class Broadcaster:
    """
    A simple broadcaster. Messages will be sent to all readers.

    @length is each reader's default queue length.

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

    _rdr = None
    value = NotGiven

    def __init__(self, length=1):
        self.length = length

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.length} ({len(self._rdr)})>"

    def open(self):
        """Open the broadcaster.

        Consider using a context instead of this method.
        """
        if self._rdr is not None:
            raise RuntimeError("already entered/opened")
        self._rdr = WeakSet()
        return self

    def __enter__(self):
        return self.open()

    async def __aenter__(self):
        return self.open()

    def __exit__(self, *tb):
        self.close()

    async def __aexit__(self, *tb):
        self.close()

    def _closed_reader(self, reader):
        self._rdr.remove(reader)

    def __aiter__(self):
        """Create a reader with the predefined queue length"""
        r = BroadcastReader(self, self.length)
        self._rdr.add(r)
        return aiter(r)

    def reader(self, length):
        """Create a reader with an explicit queue length"""
        r = BroadcastReader(self, length)
        self._rdr.add(r)
        return aiter(r)

    def __call__(self, value):
        """Enqueue a value to all readers"""
        self.value = value
        for r in self._rdr:
            r(value)

    async def read(self):
        "just gets the value"
        return self.value

    def close(self):
        "Close the broadcaster. No more writing."
        if self._rdr is not None:
            for r in self._rdr:
                r._close()  # noqa:SLF001 pylint: disable=protected-access
            self._rdr = None
