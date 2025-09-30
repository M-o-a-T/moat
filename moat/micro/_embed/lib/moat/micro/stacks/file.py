"""
Adaptor for MicroPython streams.
"""

from __future__ import annotations

from moat.micro.proto.stack import BaseBuf
from moat.util.compat import TimeoutError, _rdq, _wrq, wait_for_ms  # noqa:A004


class FileBuf(BaseBuf):
    """
    Bytestream > sync MicroPython stream

    Reads a byte at a time if the stream doesn't have an "any()" method.

    @timeout times out short reads if no more data arrives, if >0.

    @force_write must be set if the write side doesn't support polling.

    Override the `setup` async context manager to set up and tear down the
    stream. It must yield either a single file or a stdin/stdout tuple.
    """

    _buf = None
    _any = lambda: 1  # noqa:E731

    def __init__(self, cfg: dict | None = None, force_write=False, timeout=100):
        super().__init__(cfg or {})
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
        while m:
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
        "forwards to ``.write``, handles short writes"
        buf = memoryview(buf)
        t = len(buf)
        while buf:
            if not self.force_write:  # XXX *sigh*
                await _wrq(self.ws)
            n = self.ws.write(buf)
            if n is None:
                n = len(buf)
            buf = buf[n:]
        return t
