"""
Adaptor for MicroPython streams.
"""
from __future__ import annotations

from asyncio import core

from moat.micro.compat import Lock, TimeoutError, wait_for_ms

from .stack import BaseBuf


def _rdq(s):  # async
    yield core._io_queue.queue_read(s)  # noqa:SLF001


def _wrq(s):  # async
    yield core._io_queue.queue_write(s)  # noqa:SLF001


class FileBuf(BaseBuf):
    """
    Bytestream > sync MicroPython stream

    Reads a byte at a time if the stream doesn't have an "any()" method.

    Times out short reads if no more data arrives.

    @force_write must be set if the write side doesn't support polling.

    Override the `setup` async context manager to set up and tear down the
    stream. It must yield either a single file or a stdin/stdout tuple.
    """

    _buf = None
    _any = lambda: 1  # noqa:E731

    def __init__(self, cfg={}, force_write=False, timeout=100):
        super().__init__(cfg)
        self._wlock = Lock()
        self.force_write = force_write
        self.timeout = timeout

    async def setup(self):  # noqa:D102
        s = await self.stream()
        if isinstance(s, tuple):
            self.rs, self.ws = s
        else:
            self.rs = self.ws = s
        self._any = getattr(self.rs, "any", lambda: 1)

    async def stream(self):  # noqa:D102
        raise NotImplementedError

    async def rd(self, buf):
        "forwards to ``.read(into)``"
        n = 0
        m = memoryview(buf)
        while len(m):
            if n == 0 or self.timeout is None:
                await _rdq(self.rs)
            else:
                try:
                    await wait_for_ms(self.timeout, _rdq, self.rs)
                except TimeoutError:
                    break
            d = self.rs.readinto(m[: min(self._any(), len(m))])
            if not d:
                break
            m = m[d:]
            n += d
        return n

    async def wr(self, buf):
        "forwards to ``.write``"
        async with self._wlock:
            m = memoryview(buf)
            i = 0
            while i < len(buf):
                if not self.force_write:  # XXX *sigh*
                    await _wrq(self.ws)
                n = self.ws.write(m[i:])
                if n:
                    i += n
            self._buf = None
            return i
