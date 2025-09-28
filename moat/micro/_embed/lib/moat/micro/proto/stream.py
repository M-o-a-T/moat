"""
Adaptor for MicroPython streams.
"""

from __future__ import annotations

from moat.lib.codec import get_codec
from moat.util.compat import AC_use

from ._stream import _CBORMsgBlk, _CBORMsgBuf
from .stack import BaseBuf


class CBORMsgBuf(_CBORMsgBuf):
    """
    structured messages > stream of bytes

    Use this if the layer below does not support/require byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec(self.cfg.get("codec", "std-cbor"))


class CBORMsgBlk(_CBORMsgBlk):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec(self.cfg.get("codec", "std-cbor"))


class AIOBuf(BaseBuf):
    """
    Adapts an asyncio stream to MoaT.

    Implement an async context handler @stream to set the stream up
    (and close it when done).
    """

    s = None

    def __init__(self):
        pass

    async def stream(self):  # noqa:D102
        raise NotImplementedError

    async def wr(self, buf):
        "translates to ``.write`` + ``.drain``"
        self.s.write(buf)
        await self.s.drain()
        return len(buf)

    async def rd(self, buf):
        "translates to ``.readinto``"
        s = self.s
        res = await s.readinto(buf)
        if not res:
            raise EOFError
        return res


class SingleAIOBuf(AIOBuf):
    """
    Adapts an asyncio stream to MoaT.

    The stream is passed to the class constructor and can only be used
    once.
    """

    def __init__(self, stream):
        self._s = stream

    async def stream(self):  # noqa:D102
        if self._s is None:
            raise RuntimeError("used twice")
        s, self._s = self._s, None
        await AC_use(self, self._destr)
        return s

    def _destr(self):
        if hasattr(self.s, "deinit"):
            self.s.deinit()
        elif hasattr(self.s, "close"):
            self.s.close()
