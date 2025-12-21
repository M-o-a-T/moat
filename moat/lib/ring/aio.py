"""
Async front-end for the characer-based ring buffer.
"""

from __future__ import annotations

from moat.util.compat import Event

from ._impl import RingBuffer as _RingBuf


class RingBuffer(_RingBuf):
    """
    This ring buffer can hold a predetermined number of bytes.

    This is the async version.
    """

    _w_evt: Event | None = None
    _r_evt: Event | None = None

    def __init__(self, length: int):
        super().__init__(length)

    async def write(self, buf: bytes) -> int:
        """
        Adds the bytes in `buf` to the end of the buffer.
        """
        if not buf:
            return 0

        buf_len = len(buf)
        n = 0

        while True:
            nb = super().write(buf, drop=False)
            n += nb
            if self._r_evt is not None:
                self._r_evt.set()
                self._r_evt = None
            if n == buf_len:
                return buf_len
            buf = memoryview(buf)[nb:]
            if self._w_evt is None:
                self._w_evt = Event()
            await self._w_evt.wait()

    async def readinto(self, buf: bytearray) -> int:
        """
        Copies as many bytes as will fit (or are available, whichever is
        smaller) into the buffer and advance the read counter.
        """
        if len(buf) == 0:
            return 0
        n = super().readinto(buf)
        while n == 0:
            if self._r_evt is None:
                self._r_evt = Event()
            await self._r_evt.wait()
            n = super().readinto(buf)

        if self._w_evt is not None:
            self._w_evt.set()
            self._w_evt = None

        return n

    async def wait_avail(self) -> None:
        """
        Waits until data are available.
        """
        if self.n_free > 0:
            return
        if self._r_evt is None:
            self._r_evt = Event()
        await self._r_evt.wait()
