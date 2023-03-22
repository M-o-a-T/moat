import logging
from weakref import WeakSet

import anyio
from anyio import create_memory_object_stream as _cmos
from outcome import Error, Value

from .impl import NotGiven

logger = logging.getLogger(__name__)

__all__ = [
    "Queue",
    "create_queue",
    "DelayedWrite",
    "DelayedRead",
    "Broadcaster",
    "BroadcastReader",
    "LostData",
]


class Queue:
    """
    Queues have been replaced in trio/anyio by memory object streams, but
    those are more complicated to use.

    This Queue class simply re-implements queues on top of memory object streams.
    """

    def __init__(self, length=0):
        self._s, self._r = _cmos(length)

    async def put(self, x):
        """Send a value, blocking"""
        await self._s.send(Value(x))

    def put_nowait(self, x):
        """Send a value, nonblocking"""
        self._s.send_nowait(Value(x))

    async def put_error(self, x):
        """Send an error value, blocking"""
        await self._s.send(Error(x))

    async def get(self):
        """Get the next value, blocking.
        May raise an exception if one was sent."""
        res = await self._r.receive()
        return res.unwrap()

    def get_nowait(self):
        """Get the next value, nonblocking.
        May raise an exception if one was sent."""
        res = self._r.receive_nowait()
        return res.unwrap()

    def qsize(self):
        """Return the number of elements in the queue"""
        return self._s.statistics().current_buffer_used

    def empty(self):
        """Check whether the queue is empty"""
        return self._s.statistics().current_buffer_used == 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        res = await self._r.__anext__()  # pylint: disable=E1101
        return res.unwrap()

    def close_sender(self):
        """No more messages will be received"""
        return self._s.aclose()

    def close_receiver(self):
        """No more messages may be sent"""
        return self._r.aclose()


def create_queue(length=0):
    """Create a queue. Compatibility method.

    Deprecated; instantiate `Queue` directly."""
    return Queue(length)


class DelayedWrite:
    """
    A module that limits the number of outstanding outgoing messages by
    receiving flow-control messages from a `DelayedRead` instance on the
    other side.
    """

    _delay = None
    _send_lock = None
    _info = None
    _seq = 0

    def __init__(self, length, info=None):
        self.len = length
        self._n_ack = 0
        self._n_sent = 0
        self._send_lock = anyio.Lock()
        if info is None:
            DelayedWrite._seq += 1
            info = f"DlyW.{DelayedWrite._seq}"
        self._info = info

    async def next_seq(self):
        """
        Returns the next seq num for sending.

        May delay until an ack is received.
        """
        async with self._send_lock:
            self._n_sent += 1
            res = self._n_sent
            if self._delay is None and self._n_sent - self._n_ack >= self.len:
                logger.debug("%s: wait: %d/%d", self._info, self._n_sent, self._n_ack)
                self._delay = anyio.Event()
            if self._delay is not None:
                await self._delay.wait()
            return res

    async def recv_ack(self, msg_nr):
        """
        Signal that this ack msg has been received.
        """
        self._n_ack = max(self._n_ack, msg_nr)
        if self._delay is not None and self._n_sent - self._n_ack < self.len:
            logger.debug("%s: go: %d/%d", self._info, self._n_sent, self._n_ack)
            self._delay.set()
            self._delay = None


class DelayedRead(Queue):
    """
    A queue that limits the number of outstanding incoming messages by
    flow-controlling a `DelayedWrite` instance on the other side.

    You need to override (or pass in)

    * get_seq(msg) -- extract the msgnum from a message
    * async send_ack(seq) -- send an ack for this message
    """

    def __init__(self, length, *, get_seq=None, send_ack=None):
        if length < 4:
            raise RuntimeError("Length <4 doesn't make sense")
        super().__init__(length)
        self._n_last = 0
        self._n_ack = 0
        self._len = length // 3
        if get_seq is not None:
            self.get_seq = get_seq
        if send_ack is not None:
            self.send_ack = send_ack

    @staticmethod
    def get_seq(msg) -> int:  # pylint: disable=method-hidden
        """msgnum extractor. Static method. Override me!"""
        raise NotImplementedError("Override get_seq")

    async def send_ack(self, seq: int):  # pylint: disable=method-hidden
        """Ack sender for a specific seqnum. Override me!"""
        raise NotImplementedError("Override send_flow")

    async def _did_read(self, res):
        self._n_last = max(self._n_last, self.get_seq(res))
        if self._n_last - self._n_ack > self._len:
            self._n_ack = self._n_last
            await self.send_ack(self._n_last)

    async def __anext__(self):
        res = await super().__anext__()
        await self._did_read(res)
        return res

    async def get(self):
        """Receive the next message, send an Ack to the other side."""
        res = await super().get()
        await self._did_read(res)
        return res


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

    Warning: The iterator may return ``LostData`` instances in addition to
    actual data. These contain the number of messages that have been
    dropped due to the reader being too slow.

    Readers may be called to inject values.
    """

    value = NotGiven
    loss = 0

    def __init__(self, parent, length):
        self.parent = parent
        if length <= 0:
            raise RuntimeError("Length must be at least one")
        self._w, self._r = _cmos(length)

    def __aiter__(self):
        return self

    async def __anext__(self):
        # The dance below assures that a last value that's been set
        # before closing is delivered.
        if self.loss > 0:
            n, self.loss = self.loss, 0
            raise LostData(n)

        try:
            return await self._r.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    def __call__(self, value):
        try:
            self._w.send_nowait(value)
        except anyio.WouldBlock:
            x = self._r.receive_nowait()
            logger.debug("Dropped: %r", x)
            self._w.send_nowait(value)
            self.loss += 1

    def close(self):
        "close this reader, detaching it from its parent"
        self._close()
        self.parent._closed_reader(self)  # pylint: disable=protected-access

    def _close(self):
        self._w.close()
        self._w = None

    async def aclose(self):
        "close this reader, detaching it from its parent"
        self.close()


class Broadcaster:
    """
    A simple broadcaster. Messages will be sent to all readers.

    If a queue is full, the oldest message will be discarded. Readers will
    then get a LostData exception that contains the number of dropped
    messages.

    To write, open a context manager (sync or async) and call with a value.

    To read, async-iterate.

        async def rdr(bcr):
            async for msg in bcr:
                print(msg)
                # bcr.close()  # stops just this reader

        async with anyio.create_task_group() as tg, Broadcaster() as bc:
            tg.spawn(rdr, bc)  # or aiter(bc)
            for x in range(5):
                bc(x)
                anyio.sleep(0.01)
            bc(42)
            # bc.close()  # may be used explicitly

    To safely re-sync, do something like this:

        while True:
            with anyio.move_on_after(0.01):
                await anext(bcr)
                continue
            break
        x = await fetch_consistent_state()
        bcr(x)  # if this fails, you've got a problem
        while True:
            y = await anext(bcr)
            if x is y:
                break

    """

    __reader = None

    def __init__(self, length=1):
        self.length = length

    def __enter__(self):
        if self.__reader is not None:
            raise RuntimeError("already entered")
        self.__reader = WeakSet()
        return self

    async def __aenter__(self):
        return self.__enter__()

    def __exit__(self, *tb):
        self.close()

    async def __aexit__(self, *tb):
        self.close()

    def _closed_reader(self, reader):
        self.__reader.remove(reader)

    def __aiter__(self):
        r = BroadcastReader(self, self.length)
        self.__reader.add(r)
        return r.__aiter__()

    def reader(self, length):
        """Create a reader with an explicit queue length"""
        r = BroadcastReader(self, length)
        self.__reader.add(r)
        return aiter(r)

    def __call__(self, value):
        for r in self.__reader:
            r(value)

    def close(self):
        "Close the broadcaster. No more writing."
        if self.__reader is not None:
            for r in self.__reader:
                r._close()  # pylint: disable=protected-access
            self.__reader = None
