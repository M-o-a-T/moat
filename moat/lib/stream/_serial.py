"""
SerialPacker protocol support for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import Lock
from moat.lib.stream import BaseBuf, StackedBlk

from ._console import _CReader


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a CBORHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """

    cons = False

    def __init__(self, stream: BaseBuf, frame: dict, console: bool | int = False):
        super().__init__(None)

        from serialpacker import SerialPacker  # noqa: PLC0415

        self.s = stream
        self.p = SerialPacker(**frame)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.w_lock = Lock()
        if console:
            _CReader.__init__(self, console)

    async def crd(self, buf):
        if not self.cons:
            raise EOFError
        return await _CReader.crd(self, buf)

    async def cwr(self, buf):
        if not self.cons:
            return
        return await super().wr(buf)

    async def recv(self):
        while True:
            while self.i < self.n:
                msg = self.p.feed(self.buf[self.i])
                self.i += 1
                if isinstance(msg, int):
                    if self.cons:
                        _CReader.cput(self, msg)
                elif msg is not None:
                    return msg

            n = await self.s.rd(self.buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n

    async def send(self, msg):
        h, msg, t = self.p.frame(msg)
        async with self.w_lock:
            if not self.cons:
                await self.s.wr(h)
                await self.s.wr(msg)
                await self.s.wr(t)
            else:
                await self.s.wr(h + msg + t)
