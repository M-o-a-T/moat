import logging

import anyio
from anyio import create_memory_object_stream as _cmos
from outcome import Error, Value

logger = logging.getLogger(__name__)

__all__ = ["Queue", "create_queue", "DelayedWrite", "DelayedRead"]


class Queue:
    def __init__(self, length=0):
        self._s, self._r = _cmos(length)

    async def put(self, x):
        await self._s.send(Value(x))

    async def put_error(self, x):
        await self._s.send(Error(x))

    async def get(self):
        res = await self._r.receive()
        return res.unwrap()

    def qsize(self):
        return len(self._s._state.buffer)  # ugh

    def empty(self):
        return not len(self._s._state.buffer)  # ugh

    def __aiter__(self):
        return self

    async def __anext__(self):
        res = await self._r.__anext__()  # pylint: disable=E1101
        return res.unwrap()

    def close_sender(self):
        return self._s.aclose()

    def close_receiver(self):
        return self._r.aclose()


def create_queue(length=0):
    return Queue(length)


class DelayedWrite:
    """
    A queue that limits the number of outstanding outgoing messages by
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

        May need to delay until an ack is received.
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
    def get_seq(msg):  # pylint: disable=method-hidden
        raise NotImplementedError("Override get_seq")

    async def send_ack(self, seq):  # pylint: disable=method-hidden
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
        res = await super().get()
        await self._did_read(res)
        return res

    async def recv_flow(self, n):
        self._n_ack = n
