"""
trio/anyio no longer have queues, but sometimes a memory object stream is
unwieldy. Thus this re-implemens a simple queue using
`anyio.create_memory_object_stream`.
"""

from __future__ import annotations

import anyio
from anyio import create_memory_object_stream as _cmos

from outcome import Error, Value

from .dict import attrdict

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable

import logging  # isort:skip

logger = logging.getLogger(__name__)

__all__ = [
    "Queue",
    "QueueFull",
    "QueueEmpty",
    "create_queue",
    "DelayedWrite",
    "DelayedRead",
]

QueueFull = anyio.WouldBlock
QueueEmpty = anyio.WouldBlock


class Queue:
    """
    Queues have been replaced in trio/anyio by memory object streams, but
    those are more complicated to use.

    This Queue class simply re-implements queues on top of memory object streams.
    """

    def __init__(self, length=0):
        self._s, self._r = _cmos(length)

    @property
    def _moat(self):
        try:
            return self.__moat
        except AttributeError:
            self.__moat = d = attrdict()  # pylint: disable=attribute-defined-outside-init
            return d

    async def put(self, x):
        """Send a value, blocking"""
        try:
            await self._s.send(Value(x))
        except anyio.ClosedResourceError:
            raise EOFError from None

    def put_nowait(self, x):
        """Send a value, nonblocking"""
        try:
            self._s.send_nowait(Value(x))
        except anyio.ClosedResourceError:
            raise EOFError from None

    async def put_error(self, x):
        """Send an error value, blocking"""
        try:
            await self._s.send(Error(x))
        except anyio.ClosedResourceError:
            raise EOFError from None

    def put_nowait_error(self, x):
        """Send an error, nonblocking"""
        try:
            self._s.send_nowait(Error(x))
        except anyio.ClosedResourceError:
            raise EOFError from None

    async def get(self):
        """Get the next value, blocking.
        May raise an exception if one was sent."""
        try:
            res = await self._r.receive()
        except anyio.EndOfStream:
            raise EOFError from None
        return res.unwrap()

    def get_nowait(self):
        """Get the next value, nonblocking.
        May raise an exception if one was sent."""
        try:
            res = self._r.receive_nowait()
        except anyio.EndOfStream:
            raise EOFError from None
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

    def close_sender(self) -> Awaitable:
        """No more messages will be received"""
        self._s.close()

    close_writer = close_sender

    def close_receiver(self) -> Awaitable:
        """No more messages may be sent"""
        self._r.close()

    close_reader = close_receiver


class Lockstep(Queue):
    "A queue with sender/receiver rendez-vous"

    def __init__(self):
        super().__init__(0)


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
